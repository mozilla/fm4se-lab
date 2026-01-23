import argparse
import json
import os
import sys

# Add src to python path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from unified_agent.orchestration import UnifiedBugAgent
from unified_agent.utils.logging import setup_logging

def main():
    parser = argparse.ArgumentParser(description="Unified Mozilla Bug Agent")
    parser.add_argument("--bug_id", type=int, required=True, help="Bugzilla Bug ID")
    parser.add_argument("--output", type=str, default="output.json", help="Output JSON file")
    
    args = parser.parse_args()
    
    logger = setup_logging()
    
    agent = UnifiedBugAgent()
    report = agent.run(args.bug_id)
    
    with open(args.output, 'w') as f:
        json.dump(report, f, indent=2)
        
    logger.info(f"Report saved to {args.output}")

if __name__ == "__main__":
    main()
