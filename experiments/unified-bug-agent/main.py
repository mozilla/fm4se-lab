import argparse
import json
import os
import sys

# Add src to python path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from unified_agent.utils.logging import setup_logging


def main():
    parser = argparse.ArgumentParser(description="Unified Mozilla Bug Agent")
    parser.add_argument("--bug_id", type=int, required=False, help="Bugzilla Bug ID") # Made optional
    parser.add_argument("--output", type=str, default="output.json", help="Output JSON file")
    
    args = parser.parse_args()
    
    logger = setup_logging()

    # --- Interactive Inputs ---
    bug_id = args.bug_id
    if not bug_id:
        try:
            user_input = input("Enter Bugzilla Bug ID: ").strip()
            bug_id = int(user_input)
        except ValueError:
            logger.error("Invalid Bug ID provided.")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nExiting...")
            sys.exit(0)

    # Check and Prompt for Provider/Keys
    # We check environment variables directly BEFORE importing config/orchestration
    # to ensure they are picked up correctly.
    
    # Prompt for provider if not explicitly set
    if "LLM_PROVIDER" not in os.environ:
        print("Select LLM Provider:")
        print("1. gemini (default)")
        print("2. openai")
        print("3. claude")
        print("4. deepseek")
        
        try:
            choice = input("Enter choice (1-4) or name: ").strip().lower()
            if choice in ['1', 'gemini', '']:
                provider = 'gemini'
            elif choice in ['2', 'openai']:
                provider = 'openai'
            elif choice in ['3', 'claude']:
                provider = 'claude'
            elif choice in ['4', 'deepseek']:
                provider = 'deepseek'
            else:
                print(f"Invalid choice '{choice}', defaulting to gemini.")
                provider = 'gemini'
            
            os.environ["LLM_PROVIDER"] = provider
            logger.info(f"Selected provider: {provider}")
        except KeyboardInterrupt:
            print("\nExiting...")
            sys.exit(0)
    else:
        provider = os.environ["LLM_PROVIDER"]
    
    # Map provider to the expected env var name
    key_map = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY"
    }
    
    target_key_var = key_map.get(provider)
    if target_key_var:
        current_key = os.environ.get(target_key_var)
        if not current_key:
            print(f"API Key for {provider} not found in environment ({target_key_var}).")
            try:
                new_key = input(f"Enter {target_key_var}: ").strip()
                if new_key:
                    os.environ[target_key_var] = new_key
                    logger.info(f"Set {target_key_var} for this session.")
                else:
                    logger.error("API Key is required.")
                    sys.exit(1)
            except KeyboardInterrupt:
                print("\nExiting...")
                sys.exit(0)
    
    # --- Import after setting env vars ---
    from unified_agent.orchestration import UnifiedBugAgent
    agent = UnifiedBugAgent()
    report = agent.run(bug_id)
    
    with open(args.output, 'w') as f:
        json.dump(report, f, indent=2)
        
    logger.info(f"Report saved to {args.output}")

if __name__ == "__main__":
    main()
