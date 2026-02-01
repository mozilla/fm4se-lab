import sys
sys.path.append('src')
from unified_agent.clients import PhabricatorClient
import requests

print("--- Phabricator Debug ---")
ph = PhabricatorClient()

# Known bug with patches?
# From verify output: Bug 1866944
bug_id = 1866944
print(f"Searching revisions for Bug {bug_id}...")
revs = ph.search_revisions_by_bug_id(bug_id)
print(f"Found {len(revs)} revisions")
for r in revs:
    print(f"ID: {r['id']}, Title: {r['fields']['title']}")
    print(f"Revision Object Keys: {r.keys()}")
    print(f"Fields: {r['fields'].keys()}")
    # Check if we can find diff ID or PHID
    # print(r) # Uncomment to see full object
    
    # Try fetching diff
    print(f"Fetching diff for {r['id']} (DiffID: {r['fields'].get('diffID')})...")
    diff_id = r['fields'].get('diffID')
    if diff_id:
        try:
            # Try conduit getrawdiff
            res = ph._conduit_call('differential.getrawdiff', {'diffID': diff_id})
            if res:
                print("Conduit getrawdiff success!")
                print(res[:200])
            else:
                 print("Conduit getrawdiff returned None")
        except Exception as e:
            print(f"Conduit getrawdiff failed: {e}")
    else:
         print("No diffID found")
