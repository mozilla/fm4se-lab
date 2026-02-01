import argparse
import os
import sys
import json
import time
import logging
from typing import List

# Add src to python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from unified_agent.utils.logging import setup_logging, get_logger
from unified_agent.orchestration import UnifiedBugAgent
from dotenv import load_dotenv

load_dotenv()

logger = get_logger(__name__)

class LogCapture:
    """Context manager to capture logs to a specific file for a duration."""
    def __init__(self, log_file: str):
        self.log_file = log_file
        self.handler = None
        self.root_logger = logging.getLogger()

    def __enter__(self):
        # Create handler
        self.handler = logging.FileHandler(self.log_file, mode='w')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.handler.setFormatter(formatter)
        self.root_logger.addHandler(self.handler)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.handler:
            self.root_logger.removeHandler(self.handler)
            self.handler.close()

def read_bug_ids(input_file: str) -> List[int]:
    """Read bug IDs from a TXT or CSV file."""
    bug_ids = []
    try:
        with open(input_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                try:
                    bug_id = int(parts[0].strip())
                    bug_ids.append(bug_id)
                except ValueError:
                    logger.warning(f"Skipping invalid line: {line}")
    except Exception as e:
        logger.error(f"Error reading input file: {e}")
        sys.exit(1)
    return bug_ids

def main():
    parser = argparse.ArgumentParser(description="Batch Run Unified Bug Agent")
    parser.add_argument("--input", type=str, required=True, help="Input file containing Bug IDs (TXT or CSV)")
    parser.add_argument("--output-dir", type=str, default="results", help="Directory to save output reports")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
        
    setup_logging()
    
    bug_ids = read_bug_ids(args.input)
    logger.info(f"Found {len(bug_ids)} bugs to process.")
    
    if not bug_ids:
        logger.error("No valid bug IDs found.")
        sys.exit(1)

    if "LLM_PROVIDER" not in os.environ and "GEMINI_API_KEY" in os.environ:
         os.environ["LLM_PROVIDER"] = "gemini"

    search_agent = UnifiedBugAgent()
    
    results_summary = {
        "total": len(bug_ids),
        "success": 0,
        "failed": 0,
        "failures": []
    }
    
    for i, bug_id in enumerate(bug_ids):
        logger.rule("=")
        logger.info(f"Processing Bug {bug_id} ({i+1}/{len(bug_ids)})")
        
        # Create per-bug directory
        bug_dir = os.path.join(args.output_dir, f"{bug_id}")
        if not os.path.exists(bug_dir):
            os.makedirs(bug_dir)
            
        log_file = os.path.join(bug_dir, "execution.log")
        
        # Capture logs for this specific bug run
        with LogCapture(log_file):
            try:
                report = search_agent.run(bug_id)
                
                # 1. Comprehensive Report
                with open(os.path.join(bug_dir, "comprehensive_report.json"), 'w') as f:
                    json.dump(report, f, indent=2)
                    
                # 2. Original Bug Report
                if 'bug_data' in report:
                    with open(os.path.join(bug_dir, "original_bug_report.json"), 'w') as f:
                        json.dump(report['bug_data'], f, indent=2)
                        
                # 3. Generated Fix
                if 'generated_fix' in report:
                    with open(os.path.join(bug_dir, "generated_fix.diff"), 'w') as f:
                        f.write(report['generated_fix'])
                
                logger.success(f"Saved artifacts for Bug {bug_id} in {bug_dir}")
                results_summary["success"] += 1
                
            except Exception as e:
                logger.error(f"Failed to process Bug {bug_id}: {e}")
                results_summary["failed"] += 1
                results_summary["failures"].append({"bug_id": bug_id, "error": str(e)})
            
        time.sleep(1)

    with open(os.path.join(args.output_dir, "batch_summary.json"), 'w') as f:
        json.dump(results_summary, f, indent=2)
        
    logger.info("Batch processing complete.")
    logger.info(f"Success: {results_summary['success']}, Failed: {results_summary['failed']}")

if __name__ == "__main__":
    main()
