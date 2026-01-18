import argparse
import time
import os
import sys
from typing import List
from dotenv import load_dotenv

# Import custom logging
from mozilla_bug_analyzer.utils.logging import setup_logging, get_logger
from mozilla_bug_analyzer.analyzer import ComprehensiveBugAnalyzer

# Setup logging
setup_logging()
logger = get_logger(__name__)

load_dotenv()

def ensure_directories(base_dir="mozilla_bug_dataset"):
    paths = {
        "base": base_dir,
        "json": os.path.join(base_dir, "json_data"),
        "patches": os.path.join(base_dir, "raw_patches"),
        "reports": os.path.join(base_dir, "human_reports"),
        "generated": os.path.join(base_dir, "generated_fixes"),
    }
    for path in paths.values():
        os.makedirs(path, exist_ok=True)
    return paths

def load_bug_ids(file_path: str) -> List[int]:
    """Load bug IDs from a text file."""
    if not os.path.exists(file_path):
        logger.error(f"Bug ID file not found: {file_path}")
        return []
    
    with open(file_path, 'r') as f:
        # Read lines, strip whitespace, filtering out empty lines and comments
        lines = [l.strip() for l in f.readlines() if l.strip() and not l.strip().startswith('#')]
    
    bug_ids = []
    for line in lines:
        try:
            bug_ids.append(int(line))
        except ValueError:
            logger.warning(f"Skipping invalid bug ID: {line}")
            
    return bug_ids

def run_batch(bug_ids: List[int], delay: int = 60):
    """Run analysis on a batch of bugs."""
    api_key = os.getenv('GOOGLE_API_KEY')
    if not api_key:
        logger.error("GOOGLE_API_KEY not found in environment variables")
        return

    analyzer = ComprehensiveBugAnalyzer(gemini_api_key=api_key)
    dirs = ensure_directories()
    
    total_bugs = len(bug_ids)
    logger.header(f"STARTING BATCH PROCESSING: {total_bugs} BUGS")
    
    for i, bug_id in enumerate(bug_ids):
        logger.section(f"PROCESSING BUG {i+1}/{total_bugs}: {bug_id}")
        
        # Check if already processed
        json_path = os.path.join(dirs['json'], f"bug_{bug_id}.json")
        if os.path.exists(json_path):
            logger.warning(f"Bug {bug_id} already processed. Skipping.")
            continue
            
        try:
            report = analyzer.create_comprehensive_bug_report(bug_id)
            
            # Save artifacts
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, default=str)
            logger.success(f"Saved JSON: {json_path}")
            
            if 'raw_diff' in report and report['raw_diff']:
                diff_path = os.path.join(dirs['patches'], f"bug_{bug_id}.diff")
                with open(diff_path, 'w', encoding='utf-8') as f:
                    f.write(report['raw_diff'])
            
            # Generate Zero-Shot Fix
            zero_shot_fix = analyzer.generate_zero_shot_fix(report)
            if zero_shot_fix and not zero_shot_fix.startswith("Error"):
                fix_path = os.path.join(dirs['generated'], f"bug_{bug_id}_zeroshot.diff")
                with open(fix_path, 'w', encoding='utf-8') as f:
                    f.write(zero_shot_fix)
            
            logger.success(f"Completed Bug {bug_id}")
            
        except Exception as e:
            logger.error(f"Failed to process Bug {bug_id}: {e}")
            
        # Rate Limiting Delay
        if i < total_bugs - 1:
            logger.info(f"Sleeping for {delay} seconds to respect rate limits...")
            time.sleep(delay)

    logger.header("BATCH PROCESSING COMPLETE")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run bug analysis on a batch of bugs.")
    parser.add_argument("--bug_ids", nargs="+", type=int, help="List of bug IDs to process")
    parser.add_argument("--file", type=str, help="Path to text file containing bug IDs (one per line)")
    parser.add_argument("--delay", type=int, default=60, help="Delay in seconds between bugs (default: 60)")
    
    args = parser.parse_args()
    
    ids = []
    if args.bug_ids:
        ids.extend(args.bug_ids)
    if args.file:
        ids.extend(load_bug_ids(args.file))
        
    ids = list(set(ids)) # Deduplicate
    
    if not ids:
        logger.error("No bug IDs provided. Use --bug_ids or --file.")
        sys.exit(1)
        
    run_batch(ids, args.delay)
