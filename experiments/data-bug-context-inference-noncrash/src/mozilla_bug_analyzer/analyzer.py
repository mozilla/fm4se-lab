import json
import time
import os
import re
import google.generativeai as genai
from typing import Dict, List, Optional
from dotenv import load_dotenv
from .clients import (
    BugzillaClient, 
    PhabricatorClient, 
    CrashStatsClient, 
    TreeherderClient,
    MercurialClient, 
    SearchfoxClient
)

# Import custom logging
from .utils.logging import get_logger

logger = get_logger(__name__)

class ComprehensiveBugAnalyzer:
    """
    A system to create comprehensive bug reports by combining:
    1. Bugzilla bug data
    2. Phabricator differential/fix data (via Conduit/API)
    3. Mozilla services (hg.mozilla.org, searchfox, crash-stats, treeherder)
    4. LLM-powered analysis and enrichment
    """
    
    def __init__(self, gemini_api_key: str = None):
        """
        Initialize the comprehensive bug analyzer.
        """
        # Initialize Clients
        self.bugzilla = BugzillaClient()
        self.phabricator = PhabricatorClient()
        self.crash_stats = CrashStatsClient()
        self.treeherder = TreeherderClient()
        self.mercurial = MercurialClient()
        self.searchfox = SearchfoxClient()
        
        # Initialize Gemini
        if gemini_api_key:
            genai.configure(api_key=gemini_api_key)
            self.model = genai.GenerativeModel('gemini-2.5-flash')
        else:
            raise ValueError("Gemini API key is required")

    def _extract_commit_hashes(self, comments: List[Dict]) -> List[str]:
        """Extract commit hashes from bug comments."""
        commit_hashes = []
        for comment in comments:
            text = comment.get('text', '') + comment.get('raw_text', '')
            # Look for hg.mozilla.org URLs with commit hashes
            matches = re.findall(r'hg\.mozilla\.org/[^/]+/rev/([a-f0-9]{12,40})', text)
            commit_hashes.extend(matches)
            # Also look for standalone 12-char hex strings that might be commits
            matches = re.findall(r'\b([a-f0-9]{12})\b', text)
            commit_hashes.extend(matches)
        return list(set(commit_hashes))  # Remove duplicates

    def analyze_bug_with_llm(self, bug_data: Dict, comments: List[Dict], crash_data: List[Dict]) -> Dict:
        """Analyze bug report to extract key information."""
        logger.info("Analyzing bug report with LLM...")
        
        # Prepare bug text
        bug_text = f"""
Bug {bug_data.get('id')}: {bug_data.get('summary')}

Status: {bug_data.get('status')}
Severity: {bug_data.get('severity')}
Priority: {bug_data.get('priority')}
Component: {bug_data.get('component')}
Product: {bug_data.get('product')}

Description:
{bug_data.get('description', 'N/A')}

Comments ({len(comments)} total):
"""
        
        for comment in comments[:10]:  # First 10 comments
            bug_text += f"\n[{comment.get('creator')}]: {comment.get('text', '')[:500]}\n"
            
        if crash_data:
            bug_text += f"\nCrash Reports Linked: {len(crash_data)}\n"
            bug_text += f"Recent Crash Signatures: {[c.get('signature') for c in crash_data[:3]]}\n"
        
        prompt = f"""Analyze this Firefox bug report and extract key information.

{bug_text}

Extract and return as JSON:
{{
  "bug_type": "crash/regression/performance/feature/ui/etc",
  "root_cause": "description of what caused the bug",
  "symptoms": ["user-visible symptom 1", "symptom 2"],
  "affected_components": ["component1", "component2"],
  "reproduction_steps": ["step 1", "step 2"],
  "technical_details": "technical summary",
  "user_impact": "how this affects users",
  "severity_assessment": "low/medium/high/critical",
  "keywords": ["keyword1", "keyword2"],
  "likely_repository_paths": ["path/to/component/", "mobile/android/"]
}}

Return ONLY the JSON object."""

        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                response_text = '\n'.join(lines[1:-1])
            if response_text.startswith('json'):
                response_text = '\n'.join(response_text.split('\n')[1:])
            
            return json.loads(response_text)
            
        except Exception as e:
            logger.error(f"Error analyzing bug: {e}")
            return {}

    def analyze_fix_with_llm(self, diff_content: str, revision_data: Dict) -> Dict:
        """Analyze the fix/differential to understand what was changed."""
        logger.info("Analyzing fix with LLM...")
        
        max_diff_length = 100000
        diff_for_analysis = diff_content[:max_diff_length] if diff_content else "No diff content available"
        
        # Extract title/summary from revision data if available
        title = revision_data.get('fields', {}).get('title', 'Unknown Title')
        summary = revision_data.get('fields', {}).get('summary', 'Unknown Summary')
        
        prompt = f"""Analyze this code fix/patch.

Title: {title}
Summary: {summary}

Diff:
{diff_for_analysis}

Extract and return as JSON:
{{
  "fix_type": "bug fix/feature/refactoring/performance/etc",
  "what_was_fixed": "description",
  "how_it_was_fixed": "technical approach",
  "files_modified": ["file1", "file2"],
  "key_changes": ["change 1", "change 2"],
  "technical_approach": "detailed explanation",
  "potential_side_effects": ["effect 1", "effect 2"],
  "testing_requirements": ["test 1", "test 2"],
  "risk_level": "low/medium/high"
}}

Return ONLY the JSON object."""

        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                response_text = '\n'.join(lines[1:-1])
            if response_text.startswith('json'):
                response_text = '\n'.join(response_text.split('\n')[1:])
            
            return json.loads(response_text)
            
        except Exception as e:
            logger.error(f"Error analyzing fix: {e}")
            return {}

    def generate_comprehensive_report(self, bug_data: Dict, bug_analysis: Dict, 
                                     fix_data: Dict, fix_analysis: Dict,
                                     additional_data: Dict) -> Dict:
        """Generate a comprehensive bug report combining all data."""
        logger.info("Generating comprehensive report with LLM...")
        
        context = f"""
BUG INFORMATION:
Bug ID: {bug_data.get('id')}
Summary: {bug_data.get('summary')}
Status: {bug_data.get('status')}

Bug Analysis:
{json.dumps(bug_analysis, indent=2)}

FIX INFORMATION:
Differential: {fix_data.get('phid', 'N/A')}
Title: {fix_data.get('fields', {}).get('title')}

Fix Analysis:
{json.dumps(fix_analysis, indent=2)}

Additional Context:
- Commits: {len(additional_data.get('commits', []))}
- Related Files: {len(additional_data.get('related_files', []))}
- Crash Reports: {len(additional_data.get('crashes', []))}
- Treeherder Jobs: {additional_data.get('treeherder_status', 'N/A')}
"""
        
        prompt = f"""Create a comprehensive bug report analysis combining the bug report and its fix.

{context}

Generate a detailed report as JSON:
{{
  "executive_summary": "high-level summary of the bug and fix",
  "problem_statement": "clear description of the problem",
  "root_cause_analysis": "what caused the bug",
  "solution_description": "how the bug was fixed",
  "technical_details": {{
    "affected_code": ["file/module descriptions"],
    "changes_made": ["specific changes"],
    "testing_performed": "testing approach"
  }},
  "impact_assessment": {{
    "user_impact": "how users were affected",
    "severity_justification": "why this severity level",
    "affected_versions": ["versions"],
    "platforms_affected": ["platforms"]
  }},
  "quality_metrics": {{
    "code_quality": "assessment of fix quality",
    "test_coverage": "assessment of testing",
    "review_quality": "assessment of code review",
    "risk_level": "low/medium/high"
  }},
  "lessons_learned": ["lesson 1", "lesson 2"],
  "prevention_recommendations": ["recommendation 1", "recommendation 2"],
  "related_bugs": ["similar bugs or follow-ups"],
  "timeline": {{
    "reported": "date",
    "diagnosed": "date", 
    "fixed": "date",
    "landed": "date"
  }},
  "key_people": {{
    "reporter": "name",
    "assignee": "name",
    "reviewers": ["names"],
    "contributors": ["names"]
  }}
}}

Return ONLY the JSON object."""

        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                response_text = '\n'.join(lines[1:-1])
            if response_text.startswith('json'):
                response_text = '\n'.join(response_text.split('\n')[1:])
            
            return json.loads(response_text)
            
        except Exception as e:
            logger.error(f"Error generating report: {e}")
            return {}

    def fetch_repository_context(self, bug_analysis: Dict) -> Dict:
        """
        Fetch repository context (file tree) based on analysis.
        """
        context_data = {}
        paths = bug_analysis.get('likely_repository_paths', [])
        
        # If no paths found, try to guess from component
        # This is a bit specific to Mozilla Central structure
        if not paths:
            return {}
            
        logger.info(f"Fetching file tree for paths: {paths}")
        
        for path in paths[:3]: # Limit to top 3 paths
            # Clean path
            path = path.strip('/')
            
            # Fetch tree from Mercury
            # We assume mozilla-central for now
            files = self.mercurial.get_file_tree('mozilla-central', 'tip', path)
            if files:
                context_data[path] = files
                logger.data(f"Files in {path}", len(files))
                # If small number of files, maybe log them?
                if len(files) < 10:
                    for f in files:
                        logger.data("  -", f)
            else:
                logger.warning(f"No files found for path: {path}")
                
        return context_data


    def _execute_data_request(self, request: Dict) -> Dict:
        """Execute a data request from the LLM."""
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

    def iterative_refinement(self, report: Dict, max_iterations=3) -> Dict:
        """
        Iteratively refine the bug analysis using the research paper checklist.
        """
        logger.section(f"STARTING ITERATIVE REFINEMENT (MAX {max_iterations} ROUNDS)")
        
        checklist = """
CHECKS FOR AI-READY ISSUES:
1. Problem Definition: Is the problem statement clear? Are logs/screenshots included? Is the task scoped? Root cause identified?
2. Technical Context: Are relevant files/modules identified? Is a solution direction proposed? Is the component localized?
3. Acceptance: Is validation guidance provided?
4. Risk: Are side effects or backward compatibility risks considered?
5. Traceability: Is the information self-contained?
"""

        current_analysis = report.get('bug_analysis', {})
        repo_context = report.get('repository_context', {})
        
        # Initialize context list if not present
        if isinstance(repo_context, dict):
            repo_context = {'file_tree': repo_context}
        
        best_analysis = current_analysis
        
        # Directory for saving versions
        json_dir = os.path.join(os.getcwd(), "mozilla_bug_dataset", "json_data")
        
        for i in range(max_iterations):
            logger.step(f"REFINEMENT ITERATION {i+1}/{max_iterations}")
            
            analysis_text = json.dumps(best_analysis, indent=2)
            context_text = json.dumps(repo_context, indent=2)
            
            prompt = f"""You are a senior developer reviewing a bug analysis for an AI agent.
            
            CHECKLIST:
            {checklist}
            
            CURRENT ANALYSIS:
            {analysis_text}
            
            REPOSITORY CONTEXT:
            {context_text}
            
            Task:
            1. Critique the "CURRENT ANALYSIS" based on the checklist.
            2. Score it from 1-10.
            3. Do you need more specific data? (read a file, search for usage/definitions).
            4. Generate an IMPROVED analysis.
            
            Return JSON:
            {{
              "score": 8,
              "critique": "...",
              "data_request": {{ "type": "read_file", "target": "path/to/file.cpp" }} OR {{ "type": "search_code", "target": "ClassName" }} (OR null),
              "improved_analysis": {{ ... }}
            }}
            """
            
            try:
                response = self.model.generate_content(prompt)
                response_text = response.text.replace('```json', '').replace('```', '').strip()
                result = json.loads(response_text)
                
                score = result.get('score', 0)
                critique = result.get('critique', 'No critique')
                data_request = result.get('data_request')
                
                logger.info(f"Score: {score}/10")
                logger.info(f"Critique: {critique[:100]}...")
                
                # Save this version
                if 'improved_analysis' in result:
                     best_analysis = result['improved_analysis']
                     best_analysis['refinement_critique'] = critique
                     
                     # Version saving
                     version_path = os.path.join(json_dir, f"bug_{report.get('bug_id')}_analysis_v{i+1}.json")
                     with open(version_path, 'w') as f:
                         json.dump(best_analysis, f, indent=2)
                     logger.info(f"Saved version {i+1}: {os.path.basename(version_path)}")
                
                if score >= 9 and not data_request:
                    logger.success("Analysis meets quality standards!")
                    return best_analysis
                
                # Handle Data Request
                if data_request:
                    new_data = self._execute_data_request(data_request)
                    if new_data:
                        if 'fetched_files' not in repo_context:
                            repo_context['fetched_files'] = {}
                        repo_context['fetched_files'][new_data['target']] = new_data.get('content', new_data.get('error'))
                        logger.info("Added new data to context for next iteration")
                
            except Exception as e:
                logger.error(f"Error in refinement loop: {e}")
                break
                
        return best_analysis

    def generate_zero_shot_fix(self, report: Dict) -> str:
        """
        Generates a zero-shot fix based on the sanitized bug report.
        """
        logger.info("="*80)
        logger.info("GENERATING ZERO-SHOT FIX (Fix Data Removed)")
        logger.info("="*80)
        
        sanitized_context = {
            'bug_id': report.get('bug_id'),
            'bug_data': report.get('bug_data'),
            'bug_analysis': report.get('bug_analysis'),
            'crash_stats': report.get('crash_stats', []),  # Show crash patterns if any
        }
        
        logger.info("-"*80)
        logger.info("PROBLEM CONTEXT (FIX REMOVED)")
        logger.info("-" * 80)
        logger.info(f"Summary: {sanitized_context['bug_data'].get('summary')}")
        if 'refined_analysis' in report:
            analysis_source = report['refined_analysis']
            logger.info("Using REFINED analysis for fix generation")
        else:
            analysis_source = report.get('bug_analysis', {})
            
        logger.info(f"Summary: {sanitized_context['bug_data'].get('summary')}")
        logger.info(f"Root Cause (Hypothesis): {analysis_source.get('root_cause', 'Unknown')}")
        logger.info(f"Proposed Fix Approach: {analysis_source.get('proposed_fix_approach', 'Unknown')}")
        logger.info("-" * 80)

        prompt = f"""You are an automated program repair agent for Mozilla Firefox.
        
        Your task is to generate a git unified diff (patch) to fix the bug described below.
        You do NOT have access to the actual solution. You must infer the fix based on the bug description and analysis.
        
        CONTEXT:
        {json.dumps(sanitized_context, indent=2, default=str)}
        
        REFINED ANALYSIS (Best Practices):
        {json.dumps(analysis_source, indent=2)}
        
        INSTRUCTIONS:
        1. Analyze the bug description, root cause, and proposed fix approach.
        2. Generate the necessary code changes (C++, JavaScript, Python, etc.).
        3. Output the result as a standard Unified Diff.
        4. If the exact file path is unknown, make a reasonable guess based on the component/product.
        
        Return ONLY the raw Unified Diff content. Do not add markdown formatting or explanations.
        """
        
        try:
            logger.info("Querying LLM for Zero-Shot Fix...")
            response = self.model.generate_content(prompt)
            generated_fix = response.text.strip()
            
            generated_fix = generated_fix.replace("```diff", "").replace("```", "").strip()
            
            logger.info("-"*80)
            logger.info("GENERATED ZERO-SHOT FIX")
            logger.info("-" * 80)
            logger.info(generated_fix[:2000] + ("\n... (truncated)" if len(generated_fix) > 2000 else ""))
            
            return generated_fix
            
        except Exception as e:
            logger.error(f"Error generating zero-shot fix: {e}")
            return f"Error: {e}"

    def create_comprehensive_bug_report(self, bug_id: int) -> Dict:
        """
        Main method: Create a comprehensive bug report combining all data sources.
        """
        logger.header(f"CREATING COMPREHENSIVE BUG REPORT FOR BUG {bug_id}")
        
        report = {
            'bug_id': bug_id,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'data_sources': []
        }
        
        # ===== STEP 1: Get Bugzilla Data =====
        logger.step("STEP 1: FETCHING BUGZILLA DATA")
        
        bug_data = self.bugzilla.get_bug_data(bug_id)
        if not bug_data:
            logger.error("Failed to fetch bug data!")
            return report
        
        logger.success(f"Retrieved bug: {bug_data.get('summary', 'N/A')[:60]}...")
        logger.data("Status", bug_data.get('status'))
        logger.data("Component", bug_data.get('component'))
        logger.data("Severity", bug_data.get('severity'))
            
        report['bug_data'] = bug_data
        report['data_sources'].append('bugzilla')
        
        report['comments'] = self.bugzilla.get_bug_comments(bug_id)
        logger.success(f"Retrieved {len(report['comments'])} comments")
        
        report['history'] = self.bugzilla.get_bug_history(bug_id)
        logger.success(f"Retrieved {len(report['history'])} history events")
        
        report['attachments'] = self.bugzilla.get_bug_attachments(bug_id)
        logger.success(f"Retrieved {len(report['attachments'])} attachments")
        
        # ===== STEP 2: Get Crash Stats =====
        logger.step("STEP 2: FETCHING CRASH STATS")
        
        crashes = self.crash_stats.search_crashes_by_bug(bug_id)
        if crashes:
            logger.success(f"Found {len(crashes)} crash reports")
            # Show top crash signatures
            signatures = list(set([c.get('signature', 'Unknown') for c in crashes[:5]]))
            for sig in signatures[:3]:
                logger.data("Crash", sig[:60])
            report['crash_stats'] = crashes
            report['data_sources'].append('crash-stats')
        else:
            logger.progress("No crash reports found")
            report['crash_stats'] = []

        # ===== STEP 3: Analyze Bug Report =====
        logger.step("STEP 3: ANALYZING BUG WITH LLM")
        
        logger.progress("Sending bug data to Gemini for analysis...")
        bug_analysis = self.analyze_bug_with_llm(bug_data, report['comments'], report['crash_stats'])
        if bug_analysis:
            logger.success("Bug analysis complete")
            logger.data("Bug Type", bug_analysis.get('bug_type', 'Unknown'))
            logger.data("Severity", bug_analysis.get('severity_assessment', 'Unknown'))
        report['bug_analysis'] = bug_analysis
        
        # ===== STEP 3.5: Fetch Repository Context =====
        logger.step("STEP 3.5: FETCHING REPOSITORY CONTEXT")
        if bug_analysis:
            repo_context = self.fetch_repository_context(bug_analysis)
            report['repository_context'] = repo_context
            if repo_context:
                report['data_sources'].append('repository_tree')
                logger.success(f"Fetched file tree for {len(repo_context)} paths")
        else:
            logger.warning("Skipping repository context (no bug analysis)")

        
        # ===== STEP 4: Get Phabricator Fix Data =====
        logger.step("STEP 4: FETCHING PHABRICATOR FIX DATA")
        
        revisions = self.phabricator.search_revisions_by_bug_id(bug_id)
        
        if revisions:
            logger.success(f"Found {len(revisions)} Phabricator revision(s)")
            report['revisions'] = revisions
            report['data_sources'].append('phabricator')
            
            # Use the first revision (usually most relevant)
            primary_rev = revisions[0]
            diff_id = primary_rev.get('id')
            logger.data("Revision", f"D{diff_id}")
            logger.data("Title", primary_rev.get('fields', {}).get('title', 'N/A')[:60])
            
            diff_content = None
            if diff_id:
                logger.progress(f"Fetching diff for D{diff_id}...")
                diff_content = self.phabricator.get_revision_diff(diff_id)
                # Validate that we got actual diff content, not HTML
                if diff_content and ('<!DOCTYPE html>' in diff_content or '<html>' in diff_content):
                    logger.warning("Received HTML instead of diff - authentication may be required")
                    diff_content = None
                elif diff_content:
                    logger.success(f"Retrieved diff ({len(diff_content)} bytes)")
                    
                report['raw_diff'] = diff_content
            
            # ===== STEP 5: Analyze Fix =====
            logger.step("STEP 5: ANALYZING FIX WITH LLM")
            
            if diff_content:
                logger.progress("Sending diff to Gemini for analysis...")
                fix_analysis = self.analyze_fix_with_llm(diff_content, primary_rev)
                if fix_analysis:
                    logger.success("Fix analysis complete")
                    logger.data("Fix Type", fix_analysis.get('fix_type', 'Unknown'))
                    logger.data("Risk Level", fix_analysis.get('risk_level', 'Unknown'))
                report['fix_analysis'] = fix_analysis
            else:
                logger.warning("No valid diff content available for analysis")
                report['fix_analysis'] = {}
        else:
            logger.progress("No Phabricator revisions found")

        # ===== STEP 6: Get Mercurial/Commit Data & Treeherder =====
        logger.step("STEP 6: FETCHING COMMIT & TREEHERDER DATA")
        
        commits = []
        commit_hashes = self._extract_commit_hashes(report['comments'])
        
        if commit_hashes:
            logger.progress(f"Found {len(commit_hashes)} potential commit hash(es)")
            repos = ['mozilla-central', 'autoland', 'integration/autoland']
            
            for commit_hash in commit_hashes[:5]:  # Limit to first 5
                for repo in repos:
                    commit_data = self.mercurial.get_commit(repo, commit_hash)
                    if commit_data:
                        logger.success(f"Found commit {commit_hash[:12]} in {repo}")
                        commits.append(commit_data)
                        report['data_sources'].append('mercurial')
                        
                        # Try to get Treeherder data
                        logger.progress(f"Checking Treeherder for {commit_hash[:12]}...")
                        push_health = self.treeherder.get_push_health(commit_hash, repo)
                        if push_health:
                            if 'treeherder_data' not in report:
                                report['treeherder_data'] = []
                            report['treeherder_data'].append(push_health)
                            report['data_sources'].append('treeherder')
                            logger.success("Retrieved Treeherder data")
                        break
        else:
            logger.progress("No commit hashes found in comments")
        
        report['commits'] = commits
        
        # ===== STEP 7: Search Searchfox for Related Code =====
        logger.step("STEP 7: SEARCHING SEARCHFOX")
        
        related_files = []
        if 'fix_analysis' in report and report['fix_analysis'].get('files_modified'):
             logger.progress(f"Searching for {len(report['fix_analysis']['files_modified'])} file(s)...")
             for file_path in report['fix_analysis']['files_modified'][:5]:
                 context = self.searchfox.get_content(file_path)
                 if context:
                     related_files.append({'file': file_path})
                     if 'searchfox' not in report['data_sources']:
                         report['data_sources'].append('searchfox')
                     logger.success(f"Found: {file_path}")
        else:
            logger.progress("No files to search (no fix analysis)")
        
        report['related_files'] = related_files

        # ===== STEP 8: Generate Comprehensive Report =====
        logger.step("STEP 8: GENERATING COMPREHENSIVE ANALYSIS")
        
        additional_data = {
            'commits': commits,
            'related_files': related_files,
            'crashes': report.get('crash_stats', []),
            'treeherder_status': f"Found {len(report.get('treeherder_data', []))} push(es)" if report.get('treeherder_data') else "No data"
        }
        
        if 'revisions' in report and report['revisions']:
            logger.progress("Generating final comprehensive analysis with Gemini...")
            comprehensive_analysis = self.generate_comprehensive_report(
                bug_data,
                bug_analysis,
                report['revisions'][0],
                report.get('fix_analysis', {}),
                additional_data
            )
            if comprehensive_analysis:
                logger.success("Comprehensive analysis complete")
            report['comprehensive_analysis'] = comprehensive_analysis

        # ===== STEP 9: Check List Refinement (New) =====
        logger.step("STEP 9: ITERATIVE REFINEMENT")
        
        logger.progress("Starting iterative refinement loop (max 3 rounds)...")
        
        refined_analysis = self.iterative_refinement(report)
        if refined_analysis:
            report['refined_analysis'] = refined_analysis
            logger.success("Analysis refined successfully")
            if 'refinement_critique' in refined_analysis:
                logger.info(f"Critique: {refined_analysis['refinement_critique']}")
        else:
            logger.warning("Refinement failed")


        
        logger.header("COMPREHENSIVE BUG REPORT COMPLETE")
        logger.success(f"Data sources used: {', '.join(set(report.get('data_sources', [])))}")
        
        return report

    def print_comprehensive_report(self, report: Dict):
        """Pretty print the comprehensive bug report."""
        logger.info("="*80)
        logger.info("COMPREHENSIVE BUG REPORT")
        logger.info("="*80)
        logger.info(f"\nBug ID: {report['bug_id']}")
        logger.info(f"Data Sources: {', '.join(set(report.get('data_sources', [])))}")
        
        if 'comprehensive_analysis' in report:
            logger.info("-"*80)
            logger.info("EXECUTIVE SUMMARY")
            logger.info("-" * 80)
            logger.info(report['comprehensive_analysis'].get('executive_summary', 'N/A'))
