import json
import logging
import os
from typing import Any, Optional, Type
from pydantic import BaseModel
from anthropic import AsyncAnthropic

from llm.base import BaseLLMProvider, parse_json_tolerant

logger = logging.getLogger(__name__)


class AnthropicProvider(BaseLLMProvider):
    MODELS = ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"]
    DEFAULT_MODEL = "claude-3-5-sonnet-20241022"

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None

    def _get_client(self) -> AsyncAnthropic:
        if self._client is not None:
            return self._client
        key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("AI is not configured: ANTHROPIC_API_KEY is not set")
        self.api_key = key
        self._client = AsyncAnthropic(api_key=key)
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
        resp = await client.messages.create(
            model=model,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
        )
        text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text" or hasattr(b, "text")]
        return "".join(text_parts)

    async def generate_text(self, system: str, prompt: str, model: Optional[str] = None) -> str:
        target_model = model or self.get_default_model()
        return await self.execute_with_retry(self._call_generate_text, system, prompt, target_model)

    async def _call_generate_json(
        self, system: str, prompt: str, schema: Optional[Type[BaseModel]], model: str
    ) -> Any:
        client = self._get_client()
        sys = (system or "") + "\nYou MUST respond with valid STRICT JSON only. Do not wrap in markdown or add explanations."
        if schema is not None:
            sys += f"\nTarget JSON Schema: {json.dumps(schema.model_json_schema())}"

        resp = await client.messages.create(
            model=model,
            system=sys,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
        )
        text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text" or hasattr(b, "text")]
        text = "".join(text_parts)
        parsed = parse_json_tolerant(text)
        if parsed is not None:
            return parsed
        logger.error("Anthropic returned unparseable JSON: %s", text[:300])
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
