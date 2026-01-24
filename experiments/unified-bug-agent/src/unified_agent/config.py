
import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
PHABRICATOR_TOKEN = os.environ.get("PHABRICATOR_TOKEN")

# Model Configuration
# Provider options: "gemini", "openai", "claude", "deepseek"
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini")

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o",
    "claude": "claude-3-5-sonnet-20241022",
    "deepseek": "deepseek-chat"
}

# specific model override, if needed
MODEL_NAME = os.environ.get("MODEL_NAME", DEFAULT_MODELS.get(LLM_PROVIDER, "gemini-2.5-flash"))