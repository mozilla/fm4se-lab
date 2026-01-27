
import os
import requests
import json
from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
import google.generativeai as genai
from .utils.logging import get_logger

logger = get_logger(__name__)

class LLMBackend(ABC):
    def __init__(self, api_key: str, model_name: str):
        self.api_key = api_key
        self.model_name = model_name
        self.total_tokens = 0

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate text from the LLM."""
        pass

class GeminiBackend(LLMBackend):
    def __init__(self, api_key: str, model_name: str):
        super().__init__(api_key, model_name)
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

    def generate(self, prompt: str) -> str:
        try:
            response = self.model.generate_content(prompt)
            if response.usage_metadata:
                self.total_tokens += response.usage_metadata.total_token_count
            return response.text
        except Exception as e:
            logger.error(f"Gemini API Error: {e}")
            raise

class OpenAICompatibleBackend(LLMBackend):
    """Generic backend for OpenAI-compatible APIs (OpenAI, DeepSeek)."""
    def __init__(self, api_key: str, model_name: str, base_url: str):
        super().__init__(api_key, model_name)
        self.base_url = base_url.rstrip('/')

    def generate(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7 
        }
        
        try:
            response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            if 'usage' in result:
                self.total_tokens += result['usage'].get('total_tokens', 0)
            return result['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"OpenAI Compatible API Error ({self.base_url}): {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise

class OpenAIBackend(OpenAICompatibleBackend):
    def __init__(self, api_key: str, model_name: str):
        super().__init__(api_key, model_name, "https://api.openai.com/v1")

class DeepSeekBackend(OpenAICompatibleBackend):
    def __init__(self, api_key: str, model_name: str):
        super().__init__(api_key, model_name, "https://api.deepseek.com")

class ClaudeBackend(LLMBackend):
    def __init__(self, api_key: str, model_name: str):
        super().__init__(api_key, model_name)
        self.base_url = "https://api.anthropic.com/v1/messages"

    def generate(self, prompt: str) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        data = {
            "model": self.model_name,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}]
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            if 'usage' in result:
                input_tokens = result['usage'].get('input_tokens', 0)
                output_tokens = result['usage'].get('output_tokens', 0)
                self.total_tokens += input_tokens + output_tokens
            return result['content'][0]['text']
        except Exception as e:
            logger.error(f"Claude API Error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise

def get_llm_backend(provider: str, api_key: str, model_name: str) -> LLMBackend:
    if provider == "gemini":
        return GeminiBackend(api_key, model_name)
    elif provider == "openai":
        return OpenAIBackend(api_key, model_name)
    elif provider == "claude":
        return ClaudeBackend(api_key, model_name)
    elif provider == "deepseek":
        return DeepSeekBackend(api_key, model_name)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
