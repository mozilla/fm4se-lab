import time
import json
import os
from typing import Dict, Optional, List

from .config import (
    GEMINI_API_KEY, 
    OPENAI_API_KEY, 
    ANTHROPIC_API_KEY, 
    DEEPSEEK_API_KEY, 
    LLM_PROVIDER
)
from .utils.logging import get_logger
from .clients import (
    BugzillaClient, 
    PhabricatorClient, 
    CrashStatsClient, 
    TreeherderClient,
    MercurialClient, 
    MercurialClient, 
    SearchfoxClient,
    GitHubClient
)
from .agents import BugAnalystAgent, RefinementAgent, FixGeneratorAgent, MissingInfoAgent, SimulatorAgent, FilterAgent, SimilarBugsAgent
from .advanced_tools import AdvancedContextTools

logger = get_logger(__name__)

class UnifiedBugAgent:
    """
    Orchestrator for the unified bug analysis and fix generation process.
    """
    def __init__(self):
        # Initialize Clients
        self.bugzilla = BugzillaClient()
        self.phabricator = PhabricatorClient()
        self.crash_stats = CrashStatsClient()
        self.treeherder = TreeherderClient()
        self.mercurial = MercurialClient()
        self.searchfox = SearchfoxClient()
        self.github = GitHubClient()
        
        # Initialize Advanced Tools
        self.advanced_tools = AdvancedContextTools(
            self.crash_stats,
            self.searchfox,
            self.treeherder,
            self.bugzilla,
            self.phabricator
        )
        
        # Select API Key based on provider
        if LLM_PROVIDER == 'openai':
            api_key = OPENAI_API_KEY
        elif LLM_PROVIDER == 'claude':
            api_key = ANTHROPIC_API_KEY
        elif LLM_PROVIDER == 'deepseek':
            api_key = DEEPSEEK_API_KEY
        else:
            api_key = GEMINI_API_KEY

        # Initialize Agents
        self.analyst = BugAnalystAgent(api_key=api_key)
        self.refiner = RefinementAgent(api_key=api_key)
        self.missing_info_analyst = MissingInfoAgent(api_key=api_key)
        self.simulator = SimulatorAgent(api_key=api_key)
        self.filter = FilterAgent(api_key=api_key)
        self.similar_bugs_analyst = SimilarBugsAgent(api_key=api_key)
        self.fix_generator = FixGeneratorAgent(api_key=api_key)

    def _execute_data_request(self, request: Dict) -> Dict:
        """Execute a data request from the Refinement Agent."""
        req_type = request.get('type')
        target = request.get('target')
        
        if not req_type or not target:
            return None
            
        result = {'type': req_type, 'target': target}
        
        logger.rule("-")
        if req_type == 'read_file':
            logger.info(f"🔍 AGENT ACTION: Reading file '{target}'")
            # Try to fetch from Mercurial (mozilla-central)
            content = self.mercurial.get_file_content('mozilla-central', target)
            if content:
                logger.success(f"Fetched {len(content)} bytes")
                # Truncate if too large
                if len(content) > 10000:
                    content = content[:10000] + "\n... (truncated)"
                result['content'] = content
            else:
                logger.warning(f"Failed to fetch file: {target}")
                result['error'] = "File not found or inaccessible"
                
        elif req_type == 'search_code':
            logger.info(f"🔍 AGENT ACTION: Searching code for '{target}'")
            search_results = self.searchfox.search(target)
            if search_results and 'normal' in search_results:
                hits = search_results['normal']
                logger.success(f"Found {len(hits)} results")
                formatted_hits = []
                for hit in hits[:5]: # Top 5
                    path = hit.get('path', 'unknown')
                    context = hit.get('context', '')
                    formatted_hits.append(f"File: {path}\nContext: {context}")
                result['content'] = "\n---\n".join(formatted_hits)
            else:
                logger.warning(f"No results found for query: {target}")
                result['content'] = "No search results found."
        
        logger.rule("-")
        return result

    def fetch_repository_context(self, bug_analysis: Dict, known_files: List[str] = None) -> Dict:
        """
        Fetch repository context based on analysis and known files.
        known_files: list of specific file paths (e.g. from patches).
        """
        context_data = {}
        paths = bug_analysis.get('likely_repository_paths', [])
        
        # 1. Try to fetch specific known files first (highest value)
        if known_files:
            logger.info(f"Fetching content for {len(known_files)} known files from patches...")
            for fpath in known_files[:5]: # Limit to top 5 files to avoid overload
                content = self.mercurial.get_file_content('mozilla-central', fpath)
                if not content:
                     # Fallback to GitHub
                     content = self.github.get_file_content(fpath)
                
                if content:
                    context_data[fpath] = content[:5000] + "\n... (truncated)" # Truncate for context
                    logger.success(f"Fetched content for {fpath}")
                else:
                    logger.warning(f"Failed to fetch content for {fpath}")

        # 2. Try to list directories (often fails if path semantics differ, but keeping as fallback/supplement)
        if paths:
            logger.info(f"Attempting to fetch file tree for paths: {paths}")
            for path in paths[:3]: # Limit to top 3 paths
                path = path.strip('/')
                files = self.mercurial.get_file_tree('mozilla-central', 'tip', path)
                if not files:
                    # Fallback to GitHub
                    files = self.github.get_tree(path)
                    
                if files:
                    context_data[path] = files
                    logger.data(f"Files in {path}", len(files))
                else:
                    logger.warning(f"No files found (or error listing) for path: {path}")
                
        return context_data

    def run(self, bug_id: int) -> Dict:
        """Main execution flow."""
        logger.header(f"STARTING UNIFIED AGENT FOR BUG {bug_id}")
        
        report = {
            'bug_id': bug_id,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'data_sources': []
        }
        
        # 1. Fetch Bug Data
        logger.step("STEP 1: FETCHING BUG DATA")
        bug_data = self.bugzilla.get_bug_data(bug_id)
        if not bug_data:
            logger.error("Failed to fetch bug data")
            return report
            
        comments = self.bugzilla.get_bug_comments(bug_id)
        # Using Advanced Tool for crash context
        crash_context = self.advanced_tools.collect_crash_context(bug_id)
        crashes = self.crash_stats.search_crashes_by_bug(bug_id)
        
        report['bug_data'] = bug_data
        report['comments'] = comments
        report['crash_context'] = crash_context
        report['crashes'] = crashes
        report['data_sources'].extend(['bugzilla', 'crash-stats'])
        
        # 2. Initial Analysis
        logger.step("STEP 2: INITIAL ANALYSIS")
        analysis = self.analyst.analyze(bug_data, comments, crashes)
        report['bug_analysis'] = analysis
        logger.success("Initial analysis complete")
        
        # 2.5 Similar Bugs Analysis (Updated with Advanced Tools)
        logger.step("STEP 2.5: FINDING SIMILAR BUGS")
        similar_bugs_analysis = {}
        known_files = [] # Collect files from patches here
        if crash_context and crash_context.get('signature'):
            top_sig = crash_context.get('signature')
            logger.info(f"Using signature from context: {top_sig}")
            
            # Use Advanced Tool
            similar_bugs_with_patches = self.advanced_tools.collect_similar_bugs_with_phab_patches(top_sig)
            
            if similar_bugs_with_patches:
                report['similar_bugs_data'] = similar_bugs_with_patches
                # Extract just dicts for analysis agent
                similar_bugs_analysis = self.similar_bugs_analyst.analyze_similar_bugs(bug_data, similar_bugs_with_patches)
                report['similar_bugs_analysis'] = similar_bugs_analysis
                logger.success("Analyzed similar bugs")
            else:
                logger.info("No similar bugs found")
        else:
            logger.info("No signature found in crash context")

        # 3. Fetch Context (Updated with Advanced Tools)
        logger.step("STEP 3: FETCHING CONTEXT")
        if similar_bugs_with_patches:
             for bug_info in similar_bugs_with_patches:
                 if 'touched_files' in bug_info:
                     known_files.extend(bug_info['touched_files'])
        known_files = list(set(known_files)) # Unique
        
        repo_context = self.fetch_repository_context(analysis, known_files)
        report['repository_context'] = repo_context
        
        # Try advanced context tools if we have relevant info
        if crash_context and 'top_frames' in crash_context:
             logger.info("Using top frames from crash context to search Searchfox...")
             frames = crash_context['top_frames'] # Expecting list of strings
             if frames:
                 sf_results = self.advanced_tools.searchfox_from_top_frames(frames)
                 if sf_results:
                     report['searchfox_frames_analysis'] = sf_results
                     logger.success(f"Found {len(sf_results)} Searchfox hits for top frames")
        
        if 'likely_repository_paths' in analysis:
             paths = analysis['likely_repository_paths']
             if paths:
                 tests_found = self.advanced_tools.collect_related_tests(paths)
                 if tests_found:
                     report['related_tests'] = tests_found
                     logger.success(f"Found potential related tests: {len(tests_found)}") 
        
        # 4. Refinement Loop
        logger.step("STEP 4: REFINEMENT LOOP")
        refined_analysis = analysis
        
        # Enrich analysis with similar bugs info if available
        if similar_bugs_analysis:
            refined_analysis['similar_bugs_context'] = similar_bugs_analysis
            
        max_iterations = 3
        for i in range(max_iterations):
            logger.info(f"Refinement Round {i+1}/{max_iterations}")
            
            result = self.refiner.refine(refined_analysis, repo_context)
            
            score = result.get('score', 0)
            data_request = result.get('data_request')
            
            logger.info(f"Score: {score}/10")
            
            if 'improved_analysis' in result:
                refined_analysis = result['improved_analysis']
                refined_analysis['refinement_critique'] = result.get('critique')
            
            if score >= 9 and not data_request:
                logger.success("Analysis meets quality standards!")
                break
                
            if data_request:
                new_data = self._execute_data_request(data_request)
                if new_data:
                    if 'fetched_files' not in repo_context:
                        repo_context['fetched_files'] = {}
                    repo_context['fetched_files'][new_data['target']] = new_data.get('content', new_data.get('error'))
        
        report['refined_analysis'] = refined_analysis
        
        # 5. Missing Info Analysis (New from Crash logic)
        logger.step("STEP 5: MISSING INFO ANALYSIS & SIMULATION")
        missing_info = self.missing_info_analyst.analyze_missing_info(bug_data, refined_analysis)
        report['missing_info'] = missing_info
        
        # 6. Simulation (New from Crash logic)
        simulated_data = self.simulator.simulate_info(bug_data, missing_info)
        report['simulated_data'] = simulated_data
        logger.info("Simulated plausible missing info to aid fix generation")
        
        # 7. Filtering (New from Crash logic)
        logger.step("STEP 6: FILTERING CONTEXT")
        filtered_context = self.filter.filter_report(bug_data, refined_analysis, simulated_data)
        report['filtered_context'] = filtered_context
        
        # 8. Generate Fix
        logger.step("STEP 7: GENERATING FIX")
        # We pass the filtered context if available, else standard analysis
        fix_patch = self.fix_generator.generate_fix(bug_data, filtered_context if filtered_context else refined_analysis)
        report['generated_fix'] = fix_patch
        
        logger.header("WORKFLOW COMPLETE")
        return report
