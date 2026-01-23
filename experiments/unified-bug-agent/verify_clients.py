import os
import sys

# Add src to path
sys.path.append('/Users/mehilshah/Downloads/Research/fm4se-lab/experiments/unified-bug-agent/src')

from unified_agent.clients import CrashStatsClient, SearchfoxClient, PhabricatorClient, BugzillaClient
from unified_agent.utils.logging import get_logger

logger = get_logger(__name__)

def verify():
    print("Verifying Clients...")
    
    # 1. CrashStats
    print("\n--- CrashStatsClient ---")
    cs = CrashStatsClient()
    try:
        hits = cs.search_crashes_by_bug(1800000, limit=1)
        print(f"Search Crashes Result: {len(hits)} hits found (Success)")
    except Exception as e:
        print(f"FAILED CrashStats: {e}")

    # 2. Searchfox
    print("\n--- SearchfoxClient ---")
    sf = SearchfoxClient()
    try:
        res = sf.search("test")
        print(f"Search Searchfox Result: {res} (Expected None if not JSON)")
    except Exception as e:
        print(f"FAILED Searchfox: {e}")

    # 3. Phabricator
    print("\n--- PhabricatorClient ---")
    ph = PhabricatorClient()
    print(f"Token present: {'Yes' if ph.token else 'No'}")

    # 4. Bugzilla Search (New)
    print("\n--- BugzillaClient (Search) ---")
    bz = BugzillaClient()
    sig = "shutdownhang | mozilla::SpinEventLoopUntil | nsThreadPool::ShutdownWithTimeout"
    bugs = bz.search_bugs(sig, limit=2) # Use variable
    try:
        print(f"Search Bugs Result: Found {len(bugs)} bugs.")
        for b in bugs:
            print(f" - Bug {b['id']}: {b['summary'][:50]}...")
    except Exception as e:
         print(f"FAILED Bugzilla Search: {e}")

    # 5. Patch Parsing (New)
    print("\n--- AdvancedTools (Patch Parsing) ---")
    # Mock clients for advanced tools
    from unified_agent.advanced_tools import AdvancedContextTools
    at = AdvancedContextTools(cs, sf, None, bz, ph)
    
    try:
        # Use signature that is known to have bugs with patches (e.g., from the bugzilla search above)
        if bugs:
             # Just test the method itself
             results = at.collect_similar_bugs_with_phab_patches(sig)
             print(f"Collected {len(results)} similar bugs with context.")
             for res in results:
                 if res.get('touched_files'):
                     print(f" - Bug {res['bug_id']} touched files: {res['touched_files']}")
                     break
             else:
                 print(" - No touched files found in sample (might be expected if no diffs available/parsed)")
        else:
            print("Skipping patch parsing test (no bugs found)")

    except Exception as e:
        print(f"FAILED Patch Parsing: {e}")

    # 6. GitHub Fallback (New)
    print("\n--- GitHubClient ---")
    try:
        from unified_agent.clients import GitHubClient
        gh = GitHubClient()
        
        # Test directory listing which failed in Mercurial
        files = gh.get_tree("gfx")
        print(f"Directory listing for 'gfx': {len(files)} items found")
        if files:
            print(f" - Sample: {files[:3]}")
    except Exception as e:
        print(f"FAILED GitHubClient: {e}")

if __name__ == "__main__":
    verify()
