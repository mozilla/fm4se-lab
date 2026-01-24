
import os
from src.unified_agent.llm import get_llm_backend
from src.unified_agent.config import LLM_PROVIDER

def test_backend():
    print(f"Testing LLM Provider: {LLM_PROVIDER}")
    
    # Mock keys if not present for testing import/instantiation logic
    api_key = os.environ.get("GEMINI_API_KEY") or "fake_key"
    model_name = "gemini-2.5-flash"
    
    if LLM_PROVIDER == "openai":
        api_key = os.environ.get("OPENAI_API_KEY") or "fake_key"
        model_name = "gpt-4o"
    elif LLM_PROVIDER == "claude":
        api_key = os.environ.get("ANTHROPIC_API_KEY") or "fake_key"
        model_name = "claude-3-5-sonnet-20241022"
    elif LLM_PROVIDER == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY") or "fake_key"
        model_name = "deepseek-chat"

    try:
        backend = get_llm_backend(LLM_PROVIDER, api_key, model_name)
        print(f"Backend instantiated: {backend.__class__.__name__}")
        print(f"Model: {backend.model_name}")
        
        # Only try to generate if we have a real key (simple check)
        if "fake_key" not in api_key:
            print("Attempting generation...")
            response = backend.generate("Hello, reply with 'OK' if you can read this.")
            print(f"Response: {response}")
        else:
            print("Skipping generation (no real API key found in env)")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_backend()
