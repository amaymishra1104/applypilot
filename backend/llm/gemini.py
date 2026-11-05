import logging
import os
from typing import Any, Optional, Type
from pydantic import BaseModel
from google import genai
from google.genai import types

from llm.base import BaseLLMProvider, parse_json_tolerant

logger = logging.getLogger(__name__)


class GeminiProvider(BaseLLMProvider):
    MODELS = ["gemini-2.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"]
    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._client = None

    def _get_client(self) -> genai.Client:
        if self._client is not None:
            return self._client
        key = self.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("AI is not configured: GEMINI_API_KEY is not set")
        self.api_key = key
        self._client = genai.Client(api_key=key)
        return self._client

    def get_models(self) -> list[str]:
        custom = os.environ.get("LLM_MODEL")
        models = list(self.MODELS)
        if custom and custom not in models:
            models.append(custom)
        return models

    def get_default_model(self) -> str:
        return os.environ.get("LLM_MODEL") or self.DEFAULT_MODEL

    async def _call_generate_text(self, system: str, prompt: str, model: str) -> str:
        client = self._get_client()
        config = types.GenerateContentConfig(
            system_instruction=system if system else None,
        )
        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        return getattr(response, "text", "") or ""

    async def generate_text(self, system: str, prompt: str, model: Optional[str] = None) -> str:
        target_model = model or self.get_default_model()
        return await self.execute_with_retry(self._call_generate_text, system, prompt, target_model)

    async def _call_generate_json(
        self, system: str, prompt: str, schema: Optional[Type[BaseModel]], model: str
    ) -> Any:
        client = self._get_client()
        config_kwargs = {
            "response_mime_type": "application/json",
            "system_instruction": system if system else None,
        }
        if schema is not None:
            config_kwargs["response_schema"] = schema
        config = types.GenerateContentConfig(**config_kwargs)

        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        if hasattr(response, "parsed") and response.parsed is not None:
            if isinstance(response.parsed, BaseModel):
                return response.parsed.model_dump()
            return response.parsed

        text = getattr(response, "text", "") or ""
        parsed = parse_json_tolerant(text)
        if parsed is not None:
            return parsed
        logger.error("Gemini returned non-JSON text: %s", text[:300])
        return None

    async def generate_json(
        self,
        system: str,
        prompt: str,
        schema: Optional[Type[BaseModel]] = None,
        model: Optional[str] = None,
    ) -> Any:
        target_model = model or self.get_default_model()
        return await self.execute_with_retry(self._call_generate_json, system, prompt, schema, target_model)
