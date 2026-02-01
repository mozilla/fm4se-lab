import argparse
import requests
import random
import sys
import os

# diverse components to ensure variety
COMPONENTS = [
    ("Core", "Graphics"),
    ("Firefox", "Address Bar"),
    ("Core", "Networking"),
    ("Toolkit", "Add-ons Manager"),
    ("Core", "JavaScript Engine"),
    ("Core", "DOM: Core & HTML"),
    ("Firefox", "Search"),
    ("Toolkit", "Password Manager"),
]

def fetch_bugs(count: int, output_file: str):
    """Fetch resolved bugs from varied components."""
    
    bugs_per_component = (count // len(COMPONENTS)) + 1
    collected_ids = set()
    
    # Check for existing file to avoid duplicates
    if os.path.exists(output_file):
        try:
            with open(output_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            collected_ids.add(int(line))
                        except ValueError:
                            pass
            print(f"Loaded {len(collected_ids)} existing bug IDs from {output_file}.")
        except Exception as e:
            print(f"Warning: Could not read existing file: {e}")

    initial_ids = set(collected_ids)
    new_bugs = []
    
    target_total = len(initial_ids) + count
    print(f"Goal: Fetch {count} new bugs for a total of {target_total} (from {len(COMPONENTS)} components)...")
    
    for product, component in COMPONENTS:
        if len(collected_ids) >= target_total:
            break
            
        print(f"Querying {product} :: {component}...")
        
        # Bugzilla REST API search
        url = "https://bugzilla.mozilla.org/rest/bug"
        params = {
            "product": product,
            "component": component,
            "resolution": "FIXED",
            "status": ["RESOLVED", "VERIFIED"],
            "limit": bugs_per_component * 4,
            "include_fields": "id,summary,status,resolution,last_change_time",
            "order": "changeddate DESC" 
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            bugs = data.get('bugs', [])
            for bug in bugs:
                bid = bug['id']
                if bid not in collected_ids:
                    collected_ids.add(bid)
                    new_bugs.append(bid)
                    if len(collected_ids) >= target_total:
                        break
        except Exception as e:
            print(f"Error fetching for {component}: {e}")
            
    # Append to file
    if new_bugs:
        with open(output_file, 'a') as f:
            for bid in new_bugs:
                f.write(f"{bid}\n")
        print(f"Appended {len(new_bugs)} new unique bug IDs to {output_file}.")
    else:
        print("No new unique bugs found.")
        
    print(f"Total bugs in dataset: {len(collected_ids)}")

def main():
    parser = argparse.ArgumentParser(description="Fetch Diverse Resolved Bugs")
    parser.add_argument("--count", type=int, default=20, help="Number of bugs to fetch")
    parser.add_argument("--output", type=str, default="bugs.txt", help="Output file path")
    
    args = parser.parse_args()
    
    fetch_bugs(args.count, args.output)

if __name__ == "__main__":
    main()
