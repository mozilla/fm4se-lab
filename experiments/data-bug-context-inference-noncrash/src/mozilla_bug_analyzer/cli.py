import json
import os
import google.generativeai as genai
from dotenv import load_dotenv

# Import custom logging
from mozilla_bug_analyzer.utils.logging import setup_logging, get_logger

# Import the refactored analyzer
from mozilla_bug_analyzer.analyzer import ComprehensiveBugAnalyzer

load_dotenv()

# Setup logging
setup_logging()
logger = get_logger(__name__)

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

def main():
    logger.header("MOZILLA BUG DATASET GENERATOR (API ENHANCED)")
    
    api_key = os.getenv('GOOGLE_API_KEY')
    if not api_key:
        logger.error("GOOGLE_API_KEY not found in environment variables")
        logger.info("Please set GOOGLE_API_KEY in your .env file or environment")
        return
    
    dirs = ensure_directories()
    logger.success(f"Dataset directory: {os.path.abspath(dirs['base'])}")
    
    try:
        bug_id_input = input("\n🔍 Enter Bugzilla Bug ID (e.g., 2001809): ").strip()
        bug_id = int(bug_id_input)
    except ValueError:
        logger.error("Invalid bug ID - must be a number")
        return
    except KeyboardInterrupt:
        logger.info("\nCancelled by user")
        return
    
    analyzer = ComprehensiveBugAnalyzer(gemini_api_key=api_key)
    report = analyzer.create_comprehensive_bug_report(bug_id)
    
    # Save artifacts
    logger.step("SAVING ARTIFACTS")
    
    json_path = os.path.join(dirs['json'], f"bug_{bug_id}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, default=str)
    logger.success(f"JSON: {json_path}")
    
    if 'raw_diff' in report and report['raw_diff']:
        diff_path = os.path.join(dirs['patches'], f"bug_{bug_id}.diff")
        with open(diff_path, 'w', encoding='utf-8') as f:
            f.write(report['raw_diff'])
        logger.success(f"Patch: {diff_path}")
    else:
        logger.progress("No patch to save (diff not available)")

    # Generate Zero-Shot Fix
    zero_shot_fix = analyzer.generate_zero_shot_fix(report)
    if zero_shot_fix and not zero_shot_fix.startswith("Error"):
        fix_path = os.path.join(dirs['generated'], f"bug_{bug_id}_zeroshot.diff")
        with open(fix_path, 'w', encoding='utf-8') as f:
            f.write(zero_shot_fix)
        logger.success(f"Zero-shot fix: {fix_path}")

    logger.header("ALL DONE!")
    logger.info("Check the logs at: bug_analyzer.log")

if __name__ == "__main__":
    main()
