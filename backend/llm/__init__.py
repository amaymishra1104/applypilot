import os
from typing import Optional
from llm.base import BaseLLMProvider, parse_json_tolerant
from llm.gemini import GeminiProvider
from llm.openai import OpenAIProvider
from llm.anthropic import AnthropicProvider
from llm.groq import GroqProvider

_PROVIDERS = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "groq": GroqProvider,
}


def get_llm_provider(name: Optional[str] = None) -> BaseLLMProvider:
    provider_name = (name or os.environ.get("LLM_PROVIDER", "gemini")).lower().strip()
    cls = _PROVIDERS.get(provider_name)
    if not cls:
        raise ValueError(f"Unknown LLM provider: {provider_name}. Supported: {list(_PROVIDERS.keys())}")
    return cls()


def get_available_models(provider_name: Optional[str] = None) -> list[str]:
    provider = get_llm_provider(provider_name)
    return provider.get_models()


def get_default_model(provider_name: Optional[str] = None) -> str:
    provider = get_llm_provider(provider_name)
    return provider.get_default_model()


__all__ = [
    "BaseLLMProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "GroqProvider",
    "get_llm_provider",
    "get_available_models",
    "get_default_model",
    "parse_json_tolerant",
]
