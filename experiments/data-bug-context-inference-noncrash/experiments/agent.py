import requests
import json
from typing import Dict, List, Optional
import time
import google.generativeai as genai
import re
import os
import csv
from dotenv import load_dotenv

load_dotenv()

class ComprehensiveBugAnalyzer:
    """
    A system to create comprehensive bug reports by combining:
    1. Bugzilla bug data
    2. Phabricator differential/fix data
    3. Mozilla services (hg.mozilla.org, searchfox, crash reports, etc.)
    4. LLM-powered analysis and enrichment
    """
    
    def __init__(self, 
                 bugzilla_url: str = "https://bugzilla.mozilla.org",
                 phabricator_url: str = "https://phabricator.services.mozilla.com",
                 hg_url: str = "https://hg.mozilla.org",
                 searchfox_url: str = "https://searchfox.org",
                 crash_stats_url: str = "https://crash-stats.mozilla.org",
                 gemini_api_key: str = None):
        """
        Initialize the comprehensive bug analyzer.
        """
        self.bugzilla_url = bugzilla_url
        self.phabricator_url = phabricator_url
        self.hg_url = hg_url
        self.searchfox_url = searchfox_url
        self.crash_stats_url = crash_stats_url
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        })
        
        # Initialize Gemini
        if gemini_api_key:
            genai.configure(api_key=gemini_api_key)
            self.model = genai.GenerativeModel('gemini-2.5-flash')
        else:
            raise ValueError("Gemini API key is required")
    
    # ==================== BUGZILLA METHODS ====================
    
    def get_bug_data(self, bug_id: int) -> Optional[Dict]:
        """Get comprehensive bug data from Bugzilla API."""
        print(f"Fetching bug data for Bug {bug_id}...")
        
        api_url = f"{self.bugzilla_url}/rest/bug/{bug_id}"
        
        try:
            response = self.session.get(api_url, params={
                'include_fields': '_all'
            })
            response.raise_for_status()
            data = response.json()
            
            if 'bugs' in data and len(data['bugs']) > 0:
                return data['bugs'][0]
            
        except requests.RequestException as e:
            print(f"Error fetching bug data: {e}")
        
        return None
    
    def get_bug_comments(self, bug_id: int) -> List[Dict]:
        """Get all comments for a bug."""
        print(f"Fetching comments for Bug {bug_id}...")
        
        api_url = f"{self.bugzilla_url}/rest/bug/{bug_id}/comment"
        
        try:
            response = self.session.get(api_url)
            response.raise_for_status()
            data = response.json()
            
            if 'bugs' in data and str(bug_id) in data['bugs']:
                return data['bugs'][str(bug_id)]['comments']
            
        except requests.RequestException as e:
            print(f"Error fetching comments: {e}")
        
        return []
    
    def get_bug_history(self, bug_id: int) -> List[Dict]:
        """Get bug history/changes."""
        print(f"Fetching history for Bug {bug_id}...")
        
        api_url = f"{self.bugzilla_url}/rest/bug/{bug_id}/history"
        
        try:
            response = self.session.get(api_url)
            response.raise_for_status()
            data = response.json()
            
            if 'bugs' in data and len(data['bugs']) > 0:
                return data['bugs'][0].get('history', [])
            
        except requests.RequestException as e:
            print(f"Error fetching history: {e}")
        
        return []
    
    def get_bug_attachments(self, bug_id: int) -> List[Dict]:
        """Get bug attachments."""
        print(f"Fetching attachments for Bug {bug_id}...")
        
        api_url = f"{self.bugzilla_url}/rest/bug/{bug_id}/attachment"
        
        try:
            response = self.session.get(api_url)
            response.raise_for_status()
            data = response.json()
            
            if 'bugs' in data and str(bug_id) in data['bugs']:
                return data['bugs'][str(bug_id)]
            
        except requests.RequestException as e:
            print(f"Error fetching attachments: {e}")
        
        return []
    
    # ==================== PHABRICATOR METHODS ====================
    
    def search_phabricator_for_bug(self, bug_id: int) -> List[str]:
        """
        Search Phabricator for differentials related to a bug using multiple strategies.
        """
        print(f"\nSearching Phabricator for Bug {bug_id}...")
        all_diff_ids = set()
        
        # Strategy 1: Direct search query
        search_urls = [
            f"{self.phabricator_url}/search/?query=bug+{bug_id}",
            f"{self.phabricator_url}/search/?query={bug_id}",
        ]
        
        for search_url in search_urls:
            try:
                # print(f"  Trying search URL: {search_url}")
                response = self.session.get(search_url, timeout=120)
                response.raise_for_status()
                html_content = response.text
                
                # Extract differential IDs using regex
                pattern = r'\bD\d{5,7}\b'
                matches = re.findall(pattern, html_content)
                if matches:
                    # print(f"  Found {len(matches)} potential differential(s): {matches}")
                    all_diff_ids.update(matches)
                
            except requests.RequestException as e:
                print(f"  Error searching Phabricator: {e}")
                continue
        
        # Strategy 2: Check bug comments for Phabricator links
        # print(f"  Checking bug comments for Phabricator references...")
        comments = self.get_bug_comments(bug_id)
        for comment in comments:
            text = comment.get('text', '')
            # Look for Phabricator URLs
            phab_pattern = r'(?:https?://)?phabricator\.services\.mozilla\.com/D(\d{5,7})'
            matches = re.findall(phab_pattern, text)
            for match in matches:
                diff_id = f"D{match}"
                all_diff_ids.add(diff_id)
                # print(f"  Found differential in comment: {diff_id}")
            
            # Also look for standalone D##### references
            d_pattern = r'\bD(\d{5,7})\b'
            matches = re.findall(d_pattern, text)
            for match in matches:
                diff_id = f"D{match}"
                all_diff_ids.add(diff_id)
                # print(f"  Found differential reference: {diff_id}")
        
        # Strategy 3: Check bug history for Phabricator URLs
        # print(f"  Checking bug history for Phabricator references...")
        history = self.get_bug_history(bug_id)
        for entry in history:
            changes = entry.get('changes', [])
            for change in changes:
                if 'added' in change:
                    text = str(change.get('added', ''))
                    phab_pattern = r'D(\d{5,7})'
                    matches = re.findall(phab_pattern, text)
                    for match in matches:
                        diff_id = f"D{match}"
                        all_diff_ids.add(diff_id)
                        # print(f"  Found differential in history: {diff_id}")
        
        # Strategy 4: Try differential query directly
        try:
            query_url = f"{self.phabricator_url}/differential/?query=all"
            # print(f"  Trying differential query...")
            response = self.session.get(query_url, timeout=10)
            response.raise_for_status()
            html_content = response.text
            
            # Search for bug references in the page
            if str(bug_id) in html_content:
                pattern = r'\bD\d{5,7}\b'
                matches = re.findall(pattern, html_content)
                for match in matches:
                    # Verify this differential is related to our bug
                    if self.verify_differential_bug_link(match, bug_id):
                        all_diff_ids.add(match)
                        # print(f"  Verified differential: {match}")
        except:
            pass
        
        diff_list = sorted(list(all_diff_ids))
        print(f"\n✓ Total found: {len(diff_list)} differential(s): {diff_list}")
        return diff_list
    
    def verify_differential_bug_link(self, diff_id: str, bug_id: int) -> bool:
        """Verify that a differential is actually linked to the bug."""
        try:
            diff_number = diff_id.replace('D', '')
            url = f"{self.phabricator_url}/D{diff_number}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            # Check if bug ID appears in the differential page
            return str(bug_id) in response.text
        except:
            return False

    def get_differential_data(self, diff_id: str) -> Optional[Dict]:
        """Get comprehensive differential data."""
        print(f"\nFetching differential data for {diff_id}...")
        diff_number = diff_id.replace('D', '')
        url = f"{self.phabricator_url}/D{diff_number}"
        
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            html_content = response.text
            
            # Extract info with LLM
            diff_info = self.extract_diff_info_with_llm(html_content, diff_id, url)
            
            # Get raw diff - try multiple methods
            raw_diff = self.get_raw_diff(diff_id, html_content)
            
            return {
                'differential_id': diff_id,
                'url': url,
                'html_content': html_content,
                'diff_info': diff_info,
                'raw_diff': raw_diff
            }
        except requests.RequestException as e:
            print(f"Error fetching differential: {e}")
            return None

    def extract_diff_info_with_llm(self, html_content: str, diff_id: str, url: str) -> Optional[Dict]:
        """Extract structured differential information using LLM."""
        max_length = 200000
        if len(html_content) > max_length:
            html_content = html_content[:max_length]
        
        prompt = f"""Analyze this Phabricator differential page and extract information.

Differential: {diff_id}
URL: {url}

HTML:
{html_content}

Extract and return as JSON:
{{
  "differential_id": "{diff_id}",
  "url": "{url}",
  "title": "...",
  "author": "...",
  "status": "...",
  "reviewers": [{{"name": "...", "status": "..."}}],
  "summary": "...",
  "test_plan": "...",
  "bug_id": "...",
  "repository": "...",
  "branch": "...",
  "commits": ["..."],
  "files_changed": ["..."],
  "diff_summary": "...",
  "creation_date": "...",
  "last_updated": "..."
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
            print(f"Error extracting diff info: {e}")
            return None

    def get_raw_diff(self, diff_id: str, html_content: str = None) -> Optional[str]:
        """Get raw diff/patch using multiple methods."""
        diff_number = diff_id.replace('D', '')
        
        # Method 1: Try download endpoints
        raw_urls = [
            f"{self.phabricator_url}/D{diff_number}?download=true",
            f"{self.phabricator_url}/D{diff_number}.diff",
        ]
        
        for raw_url in raw_urls:
            try:
                # print(f"  Trying: {raw_url}")
                response = self.session.get(raw_url, timeout=10)
                response.raise_for_status()
                content = response.text
                
                # Check if it looks like a valid diff
                if ('diff' in content.lower()[:500] or 
                    '---' in content[:500] or 
                    '+++' in content[:500] or 
                    '@@ -' in content[:1000]):
                    print(f"  ✓ Found diff via download endpoint")
                    with open(f"mozilla_bug_dataset/raw_patches/{diff_id}.diff", "w", encoding="utf-8") as f:
                        f.write(content)
                    return content
            except Exception as e:
                # print(f"  ✗ Failed: {e}")
                continue
        
        # Method 2: Extract from HTML using LLM
        if html_content:
            print(f"  Attempting to extract diff from HTML with LLM...")
            extracted_diff = self.extract_diff_from_html_with_llm(html_content, diff_id)
            if extracted_diff:
                print(f"  ✓ Extracted diff from HTML")
                return extracted_diff
        
        # Method 3: Try to get latest diff ID from the page
        if html_content:
            print(f"  Trying to find diff version IDs...")
            diff_ids = re.findall(r'diff-(\d+)', html_content)
            if diff_ids:
                # Try the latest diff ID
                latest_diff = max([int(d) for d in diff_ids])
                diff_url = f"{self.phabricator_url}/differential/diff/{latest_diff}/"
                try:
                    # print(f"  Trying: {diff_url}")
                    response = self.session.get(diff_url, timeout=10)
                    response.raise_for_status()
                    # Extract diff from this page
                    extracted = self.extract_diff_from_html_with_llm(response.text, diff_id)
                    if extracted:
                        print(f"  ✓ Extracted diff from diff page")
                        return extracted
                except:
                    pass
        
        print(f"  ✗ Could not retrieve raw diff")
        return None

    def extract_diff_from_html_with_llm(self, html_content: str, diff_id: str) -> Optional[str]:
        """Use LLM to extract the actual diff content from HTML."""
        max_length = 300000
        if len(html_content) > max_length:
            # Try to find the diff section
            diff_markers = ['modules/libpref', 'StaticPrefList', 'diff', '+++', '---', '@@']
            best_start = 0
            for marker in diff_markers:
                idx = html_content.find(marker)
                if idx > 0:
                    best_start = max(0, idx - 10000)
                    break
            html_content = html_content[best_start:best_start + max_length]
        
        prompt = f"""Extract the actual unified diff/patch content from this Phabricator page HTML.

The diff shows changes to files. Look for lines starting with:
- "---" (old file)
- "+++" (new file)
- "@@ -" (hunk headers)
- "-" (removed lines)
- "+" (added lines)
- " " (context lines)

HTML Content:
{html_content}

Return ONLY the raw diff content in standard unified diff format, nothing else.
If you cannot find a diff, return "NO_DIFF_FOUND"."""
        
        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Clean up the response
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                # Remove first and last line (``` markers)
                response_text = '\n'.join(lines[1:-1])
                # Remove diff/patch language marker if present
                if response_text.startswith('diff') or response_text.startswith('patch'):
                    response_text = '\n'.join(response_text.split('\n')[1:])
            
            if response_text == "NO_DIFF_FOUND" or len(response_text) < 50:
                return None
            
            # Validate it looks like a diff
            if ('---' in response_text and '+++' in response_text) or '@@ -' in response_text:
                return response_text
            
            return None
        except Exception as e:
            print(f"  Error extracting diff with LLM: {e}")
            return None
    
    # ==================== MERCURIAL/HG METHODS ====================
    
    def get_commit_from_diff(self, diff_info: Dict) -> Optional[Dict]:
        """Get commit information from Mercurial."""
        # print(f"Searching for commit in Mercurial...")
        
        commits = diff_info.get('commits', [])
        if not commits:
            return None
        
        # Try mozilla-central first
        repos = ['mozilla-central', 'autoland', 'try']
        
        for commit_hash in commits:
            for repo in repos:
                commit_data = self.get_hg_commit(repo, commit_hash)
                if commit_data:
                    return commit_data
        
        return None
    
    def get_hg_commit(self, repo: str, commit_hash: str) -> Optional[Dict]:
        """Get commit data from hg.mozilla.org."""
        url = f"{self.hg_url}/{repo}/json-rev/{commit_hash}"
        
        try:
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
            
        except:
            return None
    
    # ==================== SEARCHFOX METHODS ====================
    
    def search_searchfox(self, query: str, repo: str = "mozilla-central") -> Optional[Dict]:
        """Search code on Searchfox."""
        print(f"Searching Searchfox for: {query}")
        
        url = f"{self.searchfox_url}/{repo}/search"
        
        try:
            response = self.session.get(url, params={
                'q': query,
                'limit': 20
            })
            response.raise_for_status()
            return response.json()
            
        except:
            return None
    
    def get_file_context(self, file_path: str, repo: str = "mozilla-central") -> Optional[str]:
        """Get file content from Searchfox."""
        # print(f"Getting file context: {file_path}")
        
        url = f"{self.searchfox_url}/{repo}/source/{file_path}"
        
        try:
            response = self.session.get(url)
            response.raise_for_status()
            return response.text
            
        except:
            return None

    
    # ==================== LLM ANALYSIS METHODS ====================
    
    def analyze_bug_with_llm(self, bug_data: Dict, comments: List[Dict]) -> Dict:
        """Analyze bug report to extract key information."""
        print("Analyzing bug report with LLM...")
        
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
  "keywords": ["keyword1", "keyword2"]
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
            print(f"Error analyzing bug: {e}")
            return {}
    
    def analyze_fix_with_llm(self, diff_data: Dict) -> Dict:
        """Analyze the fix/differential to understand what was changed."""
        print("Analyzing fix with LLM...")
        
        raw_diff = diff_data.get('raw_diff', '')
        diff_info = diff_data.get('diff_info', {})
        
        max_diff_length = 100000
        diff_for_analysis = raw_diff[:max_diff_length] if raw_diff else "No diff content available"
        
        prompt = f"""Analyze this code fix/patch.

Title: {diff_info.get('title')}
Summary: {diff_info.get('summary')}

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
            print(f"Error analyzing fix: {e}")
            return {}
    
    def generate_comprehensive_report(self, bug_data: Dict, bug_analysis: Dict, 
                                     fix_data: Dict, fix_analysis: Dict,
                                     additional_data: Dict) -> Dict:
        """Generate a comprehensive bug report combining all data."""
        print("Generating comprehensive report with LLM...")
        
        # Prepare combined context
        context = f"""
BUG INFORMATION:
Bug ID: {bug_data.get('id')}
Summary: {bug_data.get('summary')}
Status: {bug_data.get('status')}
Severity: {bug_data.get('severity')}
Component: {bug_data.get('component')}
Product: {bug_data.get('product')}

Bug Analysis:
{json.dumps(bug_analysis, indent=2)}

FIX INFORMATION:
Differential: {fix_data.get('differential_id')}
Title: {fix_data.get('diff_info', {}).get('title')}
Author: {fix_data.get('diff_info', {}).get('author')}
Status: {fix_data.get('diff_info', {}).get('status')}

Fix Analysis:
{json.dumps(fix_analysis, indent=2)}

Additional Context:
- Commits: {len(additional_data.get('commits', []))}
- Related Files: {len(additional_data.get('related_files', []))}
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
            print(f"Error generating report: {e}")
            return {}
    
    # ==================== MAIN ORCHESTRATION METHOD ====================
    
    def create_comprehensive_bug_report(self, bug_id: int) -> Dict:
        """
        Main method: Create a comprehensive bug report combining all data sources.
        """
        print(f"\n{'='*80}")
        print(f"CREATING COMPREHENSIVE BUG REPORT FOR BUG {bug_id}")
        print(f"{'='*80}\n")
        
        report = {
            'bug_id': bug_id,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'data_sources': []
        }
        
        # ===== STEP 1: Get Bugzilla Data =====
        print("\n" + "="*80)
        print("STEP 1: FETCHING BUGZILLA DATA")
        print("="*80)
        
        bug_data = self.get_bug_data(bug_id)
        if not bug_data:
            print("Failed to fetch bug data!")
            return report
        
        report['bug_data'] = bug_data
        report['data_sources'].append('bugzilla')
        
        comments = self.get_bug_comments(bug_id)
        report['comments'] = comments
        report['comment_count'] = len(comments)
        
        history = self.get_bug_history(bug_id)
        report['history'] = history
        
        attachments = self.get_bug_attachments(bug_id)
        report['attachments'] = attachments
        
        # ===== STEP 2: Analyze Bug Report =====
        print("\n" + "="*80)
        print("STEP 2: ANALYZING BUG REPORT")
        print("="*80)
        
        bug_analysis = self.analyze_bug_with_llm(bug_data, comments)
        report['bug_analysis'] = bug_analysis
        
        # ===== STEP 3: Get Phabricator Fix Data =====
        print("\n" + "="*80)
        print("STEP 3: FETCHING PHABRICATOR FIX DATA")
        print("="*80)
        
        diff_ids = self.search_phabricator_for_bug(bug_id)
        
        if diff_ids:
            report['differentials'] = []
            report['data_sources'].append('phabricator')
            
            for diff_id in diff_ids:
                diff_data = self.get_differential_data(diff_id)
                if diff_data:
                    report['differentials'].append(diff_data)
            
            # Use the first/primary differential for analysis
            if report['differentials']:
                primary_diff = report['differentials'][0]
                
                # ===== STEP 4: Analyze Fix =====
                print("\n" + "="*80)
                print("STEP 4: ANALYZING FIX")
                print("="*80)
                
                fix_analysis = self.analyze_fix_with_llm(primary_diff)
                report['fix_analysis'] = fix_analysis
        
        # ===== STEP 5: Get Mercurial/Commit Data =====
        print("\n" + "="*80)
        print("STEP 5: FETCHING COMMIT DATA")
        print("="*80)
        
        commits = []
        if 'differentials' in report and report['differentials']:
            for diff_data in report['differentials']:
                diff_info = diff_data.get('diff_info', {})
                commit_data = self.get_commit_from_diff(diff_info)
                if commit_data:
                    commits.append(commit_data)
                    report['data_sources'].append('mercurial')
        
        report['commits'] = commits
        
        # ===== STEP 6: Search Searchfox for Related Code =====
        print("\n" + "="*80)
        print("STEP 6: SEARCHING SEARCHFOX")
        print("="*80)
        
        related_files = []
        if 'differentials' in report and report['differentials']:
            primary_diff = report['differentials'][0]
            diff_info = primary_diff.get('diff_info', {})
            files_changed = diff_info.get('files_changed', [])
            
            for file_path in files_changed[:5]:  # First 5 files
                context = self.get_file_context(file_path)
                if context:
                    related_files.append({
                        'file': file_path,
                        'context': context[:5000]  # First 5000 chars
                    })
                    report['data_sources'].append('searchfox')
        
        report['related_files'] = related_files
        
        
        # ===== STEP 7: Generate Comprehensive Report =====
        print("\n" + "="*80)
        print("STEP 7: GENERATING COMPREHENSIVE ANALYSIS")
        print("="*80)
        
        additional_data = {
            'commits': commits,
            'related_files': related_files,
        }
        
        if 'differentials' in report and report['differentials']:
            comprehensive_analysis = self.generate_comprehensive_report(
                bug_data,
                bug_analysis,
                report['differentials'][0],
                report.get('fix_analysis', {}),
                additional_data
            )
            report['comprehensive_analysis'] = comprehensive_analysis
        
        print("\n" + "="*80)
        print("COMPREHENSIVE BUG REPORT COMPLETE")
        print("="*80)
        
        return report
    
    def print_comprehensive_report(self, report: Dict):
        """Pretty print the comprehensive bug report."""
        
        print("\n" + "="*80)
        print("COMPREHENSIVE BUG REPORT")
        print("="*80)
        
        print(f"\nBug ID: {report['bug_id']}")
        print(f"Generated: {report['timestamp']}")
        print(f"Data Sources: {', '.join(set(report.get('data_sources', [])))}")
        
        # Bug Basic Info
        bug_data = report.get('bug_data', {})
        print("\n" + "-"*80)
        print("BUG INFORMATION")
        print("-"*80)
        print(f"Summary: {bug_data.get('summary')}")
        print(f"Status: {bug_data.get('status')}")
        print(f"Severity: {bug_data.get('severity')}")
        print(f"Priority: {bug_data.get('priority')}")
        print(f"Component: {bug_data.get('component')}")
        print(f"Product: {bug_data.get('product')}")
        print(f"Assigned To: {bug_data.get('assigned_to')}")
        print(f"Reporter: {bug_data.get('creator')}")
        
        # Bug Analysis
        bug_analysis = report.get('bug_analysis', {})
        if bug_analysis:
            print("\n" + "-"*80)
            print("BUG ANALYSIS (LLM)")
            print("-"*80)
            print(f"Type: {bug_analysis.get('bug_type')}")
            print(f"Root Cause: {bug_analysis.get('root_cause')}")
            print(f"User Impact: {bug_analysis.get('user_impact')}")
            print(f"Severity Assessment: {bug_analysis.get('severity_assessment')}")
            
            if bug_analysis.get('symptoms'):
                print("\nSymptoms:")
                for symptom in bug_analysis['symptoms']:
                    print(f"  • {symptom}")
        
        # Fix Information
        if 'differentials' in report and report['differentials']:
            print("\n" + "-"*80)
            print("FIX INFORMATION")
            print("-"*80)
            
            for idx, diff_data in enumerate(report['differentials'], 1):
                diff_info = diff_data.get('diff_info', {})
                print(f"\nDifferential {idx}:")
                print(f"  ID: {diff_data.get('differential_id')}")
                print(f"  URL: {diff_data.get('url')}")
                print(f"  Title: {diff_info.get('title')}")
                print(f"  Author: {diff_info.get('author')}")
                print(f"  Status: {diff_info.get('status')}")
                
                # Show if we have the diff
                has_diff = diff_data.get('raw_diff') is not None
                diff_size = len(diff_data.get('raw_diff', '')) if has_diff else 0
                print(f"  Diff Available: {'Yes' if has_diff else 'No'}")
                if has_diff:
                    print(f"  Diff Size: {diff_size} bytes")
        
        # Fix Analysis
        fix_analysis = report.get('fix_analysis', {})
        if fix_analysis:
            print("\n" + "-"*80)
            print("FIX ANALYSIS (LLM)")
            print("-"*80)
            print(f"Fix Type: {fix_analysis.get('fix_type')}")
            print(f"What Was Fixed: {fix_analysis.get('what_was_fixed')}")
            print(f"How It Was Fixed: {fix_analysis.get('how_it_was_fixed')}")
            print(f"Risk Level: {fix_analysis.get('risk_level')}")
            
            if fix_analysis.get('key_changes'):
                print("\nKey Changes:")
                for change in fix_analysis['key_changes']:
                    print(f"  • {change}")
        
        # Comprehensive Analysis
        comp_analysis = report.get('comprehensive_analysis', {})
        if comp_analysis:
            print("\n" + "="*80)
            print("COMPREHENSIVE ANALYSIS")
            print("="*80)
            
            print(f"\n{comp_analysis.get('executive_summary', 'N/A')}")
            
            print("\n" + "-"*80)
            print("PROBLEM STATEMENT")
            print("-"*80)
            print(comp_analysis.get('problem_statement', 'N/A'))
            
            print("\n" + "-"*80)
            print("ROOT CAUSE ANALYSIS")
            print("-"*80)
            print(comp_analysis.get('root_cause_analysis', 'N/A'))
            
            print("\n" + "-"*80)
            print("SOLUTION DESCRIPTION")
            print("-"*80)
            print(comp_analysis.get('solution_description', 'N/A'))
            
            tech_details = comp_analysis.get('technical_details', {})
            if tech_details:
                print("\n" + "-"*80)
                print("TECHNICAL DETAILS")
                print("-"*80)
                
                if tech_details.get('affected_code'):
                    print("\nAffected Code:")
                    for code in tech_details['affected_code']:
                        print(f"  • {code}")
                
                if tech_details.get('changes_made'):
                    print("\nChanges Made:")
                    for change in tech_details['changes_made']:
                        print(f"  • {change}")
            
            impact = comp_analysis.get('impact_assessment', {})
            if impact:
                print("\n" + "-"*80)
                print("IMPACT ASSESSMENT")
                print("-"*80)
                print(f"User Impact: {impact.get('user_impact')}")
                print(f"Severity Justification: {impact.get('severity_justification')}")
            
            quality = comp_analysis.get('quality_metrics', {})
            if quality:
                print("\n" + "-"*80)
                print("QUALITY METRICS")
                print("-"*80)
                print(f"Code Quality: {quality.get('code_quality')}")
                print(f"Test Coverage: {quality.get('test_coverage')}")
                print(f"Review Quality: {quality.get('review_quality')}")
                print(f"Risk Level: {quality.get('risk_level')}")
            
            if comp_analysis.get('lessons_learned'):
                print("\n" + "-"*80)
                print("LESSONS LEARNED")
                print("-"*80)
                for lesson in comp_analysis['lessons_learned']:
                    print(f"  • {lesson}")
            
            if comp_analysis.get('prevention_recommendations'):
                print("\n" + "-"*80)
                print("PREVENTION RECOMMENDATIONS")
                print("-"*80)
                for rec in comp_analysis['prevention_recommendations']:
                    print(f"  • {rec}")
        
        # Statistics
        print("\n" + "-"*80)
        print("STATISTICS")
        print("-"*80)
        print(f"Comments: {report.get('comment_count', 0)}")
        print(f"History Events: {len(report.get('history', []))}")
        print(f"Attachments: {len(report.get('attachments', []))}")
        print(f"Differentials: {len(report.get('differentials', []))}")
        print(f"Commits: {len(report.get('commits', []))}")
        print(f"Related Files: {len(report.get('related_files', []))}")
        print(f"Crash Reports: {report.get('crash_count', 0)}")

    # ==================== NEW METHOD: ZERO-SHOT FIX ====================

    def generate_zero_shot_fix(self, report: Dict) -> str:
        """
        Generates a zero-shot fix based on the sanitized bug report (excluding fix data).
        """
        print(f"\n{'='*80}")
        print(f"GENERATING ZERO-SHOT FIX (Fix Data Removed)")
        print(f"{'='*80}\n")
        
        # 1. Sanitize the report to remove ground truth fix data
        # We keep bug_data, bug_analysis, comments, etc., but remove differentials/commits/fix_analysis
        
        sanitized_context = {
            'bug_id': report.get('bug_id'),
            'bug_data': report.get('bug_data'),
            'bug_analysis': report.get('bug_analysis'),
            # We explicitly exclude 'differentials', 'fix_analysis', 'commits', and 'comprehensive_analysis'
            # because 'comprehensive_analysis' contains the solution description.
        }
        
        # Display the Sanitized Report (Context for generation)
        print("\n" + "-"*80)
        print("PROBLEM CONTEXT (FIX REMOVED)")
        print("-" * 80)
        print(f"Summary: {sanitized_context['bug_data'].get('summary')}")
        print(f"Root Cause (Hypothesis): {sanitized_context['bug_analysis'].get('root_cause', 'Unknown')}")
        print("-" * 80)

        # 2. Construct Prompt
        prompt = f"""You are an automated program repair agent for Mozilla Firefox.
        
        Your task is to generate a git unified diff (patch) to fix the bug described below.
        You do NOT have access to the actual solution. You must infer the fix based on the bug description and analysis.
        
        CONTEXT:
        {json.dumps(sanitized_context, indent=2, default=str)}
        
        INSTRUCTIONS:
        1. Analyze the bug description and root cause.
        2. Generate the necessary code changes (C++, JavaScript, Python, etc.).
        3. Output the result as a standard Unified Diff.
        4. If the exact file path is unknown, make a reasonable guess based on the component/product.
        
        Return ONLY the raw Unified Diff content. Do not add markdown formatting or explanations.
        """
        
        # 3. Call LLM
        try:
            print("Querying LLM for Zero-Shot Fix...")
            response = self.model.generate_content(prompt)
            generated_fix = response.text.strip()
            
            # Clean up Markdown wrapper if present
            generated_fix = generated_fix.replace("```diff", "").replace("```", "").strip()
            
            print("\n" + "-"*80)
            print("GENERATED ZERO-SHOT FIX")
            print("-" * 80)
            print(generated_fix[:2000] + ("\n... (truncated)" if len(generated_fix) > 2000 else ""))
            
            return generated_fix
            
        except Exception as e:
            print(f"Error generating zero-shot fix: {e}")
            return f"Error: {e}"


def ensure_directories(base_dir="mozilla_bug_dataset"):
    """Creates the necessary directory structure for the dataset."""
    paths = {
        "base": base_dir,
        "json": os.path.join(base_dir, "json_data"),
        "patches": os.path.join(base_dir, "raw_patches"),
        "reports": os.path.join(base_dir, "human_reports"),
        "generated": os.path.join(base_dir, "generated_fixes"), # New directory for generated fixes
    }
    
    for path in paths.values():
        os.makedirs(path, exist_ok=True)
        
    return paths

def main():
    """
    Main function to create comprehensive bug reports and organize for training.
    """
    print("="*80)
    print("MOZILLA BUG DATASET GENERATOR")
    print("="*80)
    
    api_key = os.getenv('GOOGLE_API_KEY')
    if not api_key:
        print("Error: API key is required in .env or environment variables")
        return
    
    # 1. Setup Directories
    dirs = ensure_directories()
    print(f"Dataset location: {os.path.abspath(dirs['base'])}\n")
    
    # 2. Get Input
    bug_id_input = input("Enter Bugzilla Bug ID (e.g., 2001809): ").strip()
    try:
        bug_id = int(bug_id_input)
    except ValueError:
        print("Error: Invalid bug ID")
        return
    
    # 3. Run Analysis (Original Full Pipeline)
    analyzer = ComprehensiveBugAnalyzer(gemini_api_key=api_key)
    report = analyzer.create_comprehensive_bug_report(bug_id)
    
    # 4. Save Structured Data (JSON)
    main_report = report.copy()
    if 'differentials' in main_report:
        for diff in main_report['differentials']:
            if 'html_content' in diff: del diff['html_content']
            if 'raw_diff' in diff: del diff['raw_diff'] 
    
    if 'related_files' in main_report:
        for file_info in main_report['related_files']:
            if 'context' in file_info: del file_info['context'] 
            
    json_filename = f"bug_{bug_id}.json"
    json_path = os.path.join(dirs['json'], json_filename)
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(main_report, f, indent=2, default=str)
    print(f"\n✓ JSON metadata saved: {json_path}")
    
    # 5. Save Patches (Diffs)
    if 'differentials' in report:
        for diff_data in report['differentials']:
            raw_diff = diff_data.get('raw_diff')
            diff_id = diff_data['differential_id']
            
            if raw_diff and len(raw_diff) > 0:
                diff_filename = f"bug_{bug_id}_{diff_id}.diff"
                diff_path = os.path.join(dirs['patches'], diff_filename)
                
                with open(diff_path, 'w', encoding='utf-8') as f:
                    f.write(raw_diff)
                print(f"✓ Raw Patch saved: {diff_path}")

    # 6. Save Human-Readable Report
    report_filename = f"bug_{bug_id}_report.txt"
    report_path = os.path.join(dirs['reports'], report_filename)
    with open(report_path, 'w', encoding='utf-8') as f:
        import sys
        old_stdout = sys.stdout
        sys.stdout = f
        analyzer.print_comprehensive_report(report)
        sys.stdout = old_stdout
    print(f"✓ Human report saved: {report_path}")
    
    generated_fix = analyzer.generate_zero_shot_fix(report)
    
    # Save Generated Fix
    gen_filename = f"bug_{bug_id}_zeroshot.diff"
    gen_path = os.path.join(dirs['generated'], gen_filename)
    with open(gen_path, 'w', encoding='utf-8') as f:
        f.write(generated_fix)
    print(f"\n✓ Zero-Shot Fix saved: {gen_path}")
    
    print("\n" + "="*80)
    print("DATASET UPDATE COMPLETE")
    print("="*80)

if __name__ == "__main__":
    main()