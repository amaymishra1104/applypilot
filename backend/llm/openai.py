import logging
import os
from typing import Any, Optional, Type
from pydantic import BaseModel
from openai import AsyncOpenAI

from llm.base import BaseLLMProvider, parse_json_tolerant, is_retryable_error

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseLLMProvider):
    MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-4.5-preview"]
    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._client = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is not None:
            return self._client
        key = self.api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("AI is not configured: OPENAI_API_KEY is not set")
        self.api_key = key
        self._client = AsyncOpenAI(api_key=key)
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
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
        )
        return resp.choices[0].message.content or ""

    async def generate_text(self, system: str, prompt: str, model: Optional[str] = None) -> str:
        target_model = model or self.get_default_model()
        return await self.execute_with_retry(self._call_generate_text, system, prompt, target_model)

    async def _call_generate_json(
        self, system: str, prompt: str, schema: Optional[Type[BaseModel]], model: str
    ) -> Any:
        client = self._get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        if schema is not None and hasattr(client, "beta") and hasattr(client.beta, "chat"):
            try:
                completion = await client.beta.chat.completions.parse(
                    model=model,
                    messages=messages,
                    response_format=schema,
                )
                message = completion.choices[0].message
                if hasattr(message, "parsed") and message.parsed is not None:
                    if isinstance(message.parsed, BaseModel):
                        return message.parsed.model_dump()
                    return message.parsed
                if message.content:
                    parsed = parse_json_tolerant(message.content)
                    if parsed is not None:
                        return parsed
            except Exception as e:
                if is_retryable_error(e):
                    raise e
                logger.warning("OpenAI structured parse failed, falling back to json_object: %s", e)

        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        parsed = parse_json_tolerant(text)
        if parsed is not None:
            return parsed
        logger.error("OpenAI returned unparseable JSON: %s", text[:300])
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
