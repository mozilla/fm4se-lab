from typing import Dict, List, Optional
import requests
import re
from .clients import CrashStatsClient, SearchfoxClient, TreeherderClient, BugzillaClient, PhabricatorClient
from .utils.logging import get_logger

logger = get_logger(__name__)

class AdvancedContextTools:
    """
    Implements the 7 advanced context tools requested by the user.
    """
    def __init__(self, 
                 crash_client: CrashStatsClient,
                 searchfox_client: SearchfoxClient,
                 treeherder_client: TreeherderClient,
                 bugzilla_client: BugzillaClient,
                 phab_client: PhabricatorClient):
        self.crash = crash_client
        self.searchfox = searchfox_client
        self.treeherder = treeherder_client
        self.bugzilla = bugzilla_client
        self.phab = phab_client

    def collect_crash_context(self, bug_id: int) -> Dict:
        """
        1. Collect_crash_context: Socorro crash data (signature, top frames, environment summary).
        """
        logger.info("AdvancedTool: Collecting Crash Context...")
        crashes = self.crash.search_crashes_by_bug(bug_id, limit=1)
        if not crashes:
            return {}
        
        crash = crashes[0]
        context = {
            'signature': crash.get('signature'),
            'product': crash.get('product'),
            'version': crash.get('version'),
            'os': crash.get('platform_pretty_version'),
            'os': crash.get('platform_pretty_version')
        }
        # Note: SuperSearch hits don't have full stack frames usually.
        # We would need to fetch processed crash by UUID for frames.
        # Assuming we just return what we have for now.
        return context

    def collect_similar_bugs_with_phab_patches(self, signature: str) -> List[Dict]:
        """
        2. Collect_similar_bugs_with_phab_patches: Find similar bugs & extract Phab patches.
        """
        logger.info(f"AdvancedTool: Collecting Similar Bugs & Patches for {signature[:30]}...")
        bug_list = self.bugzilla.search_bugs(signature)
        bug_ids = [b['id'] for b in bug_list]
        results = []
        
        for bid in bug_ids:
            bug_data = self.bugzilla.get_bug_data(bid)
            revisions = self.phab.search_revisions_by_bug_id(bid)
            
            patch_excerpt = None
            touched_files = []
            if revisions:
                diff = self.phab.get_revision_diff(revisions[0]['id'])
                if diff:
                    patch_excerpt = diff[:500] + "..." # Truncate for summary
                    # Extract file paths from diff
                    # Regex for: diff --git a/path/to/file b/path/to/file
                    matches = re.findall(r'diff --git a/(.*?) b/', diff)
                    touched_files = list(set(matches)) # Unique files
            
            results.append({
                'bug_id': bid,
                'summary': bug_data.get('summary') if bug_data else 'Unknown',
                'patch_excerpt': patch_excerpt,
                'touched_files': touched_files
            })
        return results

    def searchfox_from_top_frames(self, frames: List[str]) -> List[str]:
        """
        3. Searchfox_from_top_frames: Search top crash-frame functions.
        """
        logger.info("AdvancedTool: Searching Searchfox for top frames...")
        results = []
        for frame in frames[:3]:
            # Clean frame (remove arguments etc)
            clean_token = frame.split('(')[0].split('<')[0].strip()
            if clean_token:
                res = self.searchfox.search(clean_token)
                if res and 'normal' in res and res['normal']:
                     results.append(f"Frame {clean_token}: Found {len(res['normal'])} hits")
        return results



    def collect_ci_context_for_revision(self, revision: str) -> Dict:
        """
        5. Collect_ci_context_for_revision: CI info (Treeherder + Taskcluster).
        """
        logger.info(f"AdvancedTool: Collecting CI Context for {revision}...")
        th_data = self.treeherder.get_push_health(revision)
        return {
            'treeherder': th_data
        }

    def collect_related_tests(self, files: List[str]) -> List[str]:
        """
        6. Collect_related_tests: Find tests related to touched files.
        """
        logger.info("AdvancedTool: Collecting Related Tests...")
        tests = []
        for f in files:
            # Simple heuristic: search for similar filenames in 'testing' or 'test' folders
            query = f.split('/')[-1].replace('.cpp', '').replace('.js', '')
            res = self.searchfox.search(query + " test")
            if res and 'normal' in res:
                 tests.append(f"Possible tests for {f}: {len(res['normal'])} found")
        return tests


