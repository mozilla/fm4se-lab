import json
import google.generativeai as genai
from typing import Dict, List
from .utils.logging import get_logger
from .config import DEFAULT_MODEL

logger = get_logger(__name__)

class BaseAgent:
    def __init__(self, api_key: str, model_name: str = DEFAULT_MODEL):
        if not api_key:
            raise ValueError("API key is required")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

    def _generate_json(self, prompt: str) -> Dict:
        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                # Remove first and last lines (```json and ```)
                response_text = '\n'.join(lines[1:-1])
            if response_text.startswith('json'):
                response_text = '\n'.join(response_text.split('\n')[1:])
            
            return json.loads(response_text)
        except Exception as e:
            logger.error(f"Error generating/parsing JSON: {e}")
            return {}

class BugAnalystAgent(BaseAgent):
    """Agent responsible for initial bug analysis."""
    
    def analyze(self, bug_data: Dict, comments: List[Dict], crash_data: List[Dict]) -> Dict:
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

        return self._generate_json(prompt)

class RefinementAgent(BaseAgent):
    """Agent responsible for critiquing and refining the analysis."""
    
    def refine(self, analysis: Dict, repo_context: Dict) -> Dict:
        checklist = """
CHECKS FOR AI-READY ISSUES:
1. Problem Definition: Is the problem statement clear? Are logs/screenshots included? Is the task scoped? Root cause identified?
2. Technical Context: Are relevant files/modules identified? Is a solution direction proposed? Is the component localized?
3. Acceptance: Is validation guidance provided?
4. Risk: Are side effects or backward compatibility risks considered?
5. Traceability: Is the information self-contained?
"""
        analysis_text = json.dumps(analysis, indent=2)
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
        
        return self._generate_json(prompt)

class MissingInfoAgent(BaseAgent):
    """Agent responsible for identifying missing information in a bug report."""
    
    def analyze_missing_info(self, bug_data: Dict, analysis: Dict) -> Dict:
        logger.info("Analyzing missing information...")
        
        prompt = f"""You are a senior Firefox crash engineer.
        
        Given the following bug report and initial analysis, identify what information is MISSING that would be critical for a developer to understand and fix this bug.
        
        BUG SUMMARY: {bug_data.get('summary')}
        
        INITIAL ANALYSIS:
        {json.dumps(analysis, indent=2)}
        
        Identify gaps in:
        1. Reproduction steps (are they complete?)
        2. Environment details (OS, version, hardware)
        3. Crash context (signatures, stacks if applicable)
        4. Logs or specific configuration
        
        Return JSON:
        {{
            "missing_info": [
                {{
                    "category": "Reproduction",
                    "description": "Exact URL where crash happens is missing",
                    "importance": "High"
                }},
                ...
            ],
            "confidence_score": 8,
            "recommendation": "Ask user for URL"
        }}
        """
        return self._generate_json(prompt)

class SimulatorAgent(BaseAgent):
    """Agent responsible for simulating/inventing missing information for testing capability."""
    
    def simulate_info(self, bug_data: Dict, missing_info_analysis: Dict) -> Dict:
        logger.info("Simulating missing information...")
        
        prompt = f"""You are an experienced Firefox engineer.
        
        You have a bug report with missing information. Your goal is to FILL IN these gaps with plausible, realistic fabricated data so we can test if the fix generation works better with complete info.
        
        BUG SUMMARY: {bug_data.get('summary')}
        
        MISSING INFO:
        {json.dumps(missing_info_analysis, indent=2)}
        
        Invent realistic details for the missing items.
        
        Return JSON:
        {{
            "simulated_data": {{
                "reproduction_url": "https://example.com/heavy-webgl-page",
                "os_version": "Windows 11 22H2",
                "graphics_card": "NVIDIA GTX 1060"
            }},
            "rationale": "Common crash vector for this component"
        }}
        """
        return self._generate_json(prompt)

class FilterAgent(BaseAgent):
    """Agent responsible for filtering the bug report to only relevant details for patching."""
    
    def filter_report(self, bug_data: Dict, analysis: Dict, simulated_info: Dict) -> Dict:
        logger.info("Filtering bug report for patch generation...")
        
        prompt = f"""You are a senior Firefox triager.
        
        Your goal is to create a CONCISE summary of the bug that contains ONLY the information necessary for a developer to write a patch. Remove noise.
        
        BUG: {bug_data.get('summary')}
        ANALYSIS: {json.dumps(analysis, indent=2)}
        SIMULATED EXTRA INFO: {json.dumps(simulated_info, indent=2)}
        
        Return JSON:
        {{
            "concise_summary": "...",
            "relevant_files": ["..."],
            "core_symptoms": ["..."],
            "technical_constraints": ["..."]
        }}
        """
        return self._generate_json(prompt)

        return self._generate_json(prompt)

class SimilarBugsAgent(BaseAgent):
    """Agent responsible for analyzing similar bugs found via crash signatures."""
    
    def analyze_similar_bugs(self, original_bug: Dict, similar_bugs_data: List[Dict]) -> Dict:
        logger.info("Analyzing similar bugs...")
        
        # Prepare context
        similar_context = ""
        for b in similar_bugs_data:
            similar_context += f"Bug {b.get('id')}: {b.get('summary')}\n"
            similar_context += f"Status: {b.get('status')}\n"
            similar_context += f"Description: {b.get('description', '')[:200]}...\n\n"
            
        prompt = f"""You are a Firefox crash analyst.
        
        We are investigating Bug {original_bug.get('id')} ({original_bug.get('summary')}).
        We found other bugs that share the same crash signature.
        
        SIMILAR BUGS:
        {similar_context}
        
        Task:
        1. Identify common symptoms across these bugs.
        2. Are any of them resolved? If so, how were they fixed? (Look for clues in summary/status).
        3. Do they suggest a common root cause?
        
        Return JSON:
        {{
            "common_patterns": ["pattern 1", "pattern 2"],
            "potential_root_causes": ["cause 1"],
            "relevant_fix_clues": ["clue 1"],
            "summary": "These similar bugs suggest that..."
        }}
        """
        return self._generate_json(prompt)

class FixGeneratorAgent(BaseAgent):
    """Agent responsible for generating a zero-shot fix."""
    
    def generate_fix(self, bug_data: Dict, analysis: Dict) -> str:
        logger.info("Generating zero-shot fix...")
        
        sanitized_context = {
            'bug_id': bug_data.get('id'),
            'summary': bug_data.get('summary'),
            'root_cause': analysis.get('root_cause'),
            'proposed_fix': analysis.get('proposed_fix_approach', 'Not specified')
        }
        
        prompt = f"""You are an automated program repair agent for Mozilla Firefox.
        
        Your task is to generate a git unified diff (patch) to fix the bug described below.
        You do NOT have access to the actual solution. You must infer the fix based on the bug description and analysis.
        
        CONTEXT:
        {json.dumps(sanitized_context, indent=2)}
        
        DETAILED ANALYSIS:
        {json.dumps(analysis, indent=2)}
        
        INSTRUCTIONS:
        1. Analyze the bug description, root cause, and proposed fix approach.
        2. Generate the necessary code changes (C++, JavaScript, Python, etc.).
        3. Output the result as a standard Unified Diff.
        4. If the exact file path is unknown, make a reasonable guess based on the component/product.
        
        Return ONLY the raw Unified Diff content. Do not add markdown formatting or explanations.
        """
        
        try:
            response = self.model.generate_content(prompt)
            generated_fix = response.text.strip()
            generated_fix = generated_fix.replace("```diff", "").replace("```", "").strip()
            return generated_fix
        except Exception as e:
            logger.error(f"Error generating fix: {e}")
            return f"Error: {e}"
