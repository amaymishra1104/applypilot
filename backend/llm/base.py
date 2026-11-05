import abc
import asyncio
import json
import logging
import os
from typing import Any, Optional, Type
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def parse_json_tolerant(text: str) -> Any:
    """Tolerantly parses JSON from raw LLM output, handling markdown blocks and embedded objects/arrays."""
    if not text or not isinstance(text, str):
        return None
    text = text.strip()
    # Strip markdown code blocks if present
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except Exception:
        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            end = text.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except Exception:
                    continue
    return None


def is_retryable_error(exc: Exception) -> bool:
    """Detects HTTP 429 (rate-limit), 5xx server errors, connection resets, or timeouts."""
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status_code in (429, 500, 502, 503, 504):
        return True
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    if any(k in name for k in ["ratelimit", "resourceexhausted", "servererror", "serviceunavailable", "timeout"]):
        return True
    if any(k in msg for k in ["429", "rate limit", "quota", "overloaded", "503", "502", "500", "timed out"]):
        return True
    return False


class BaseLLMProvider(abc.ABC):
    """Abstract interface for direct LLM providers with concurrency caps, timeouts, and retries."""

    def __init__(
        self,
        concurrency: Optional[int] = None,
        timeout: Optional[float] = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
    ):
        concurrency_val = concurrency or int(os.environ.get("LLM_CONCURRENCY", "5"))
        self.semaphore = asyncio.Semaphore(concurrency_val)
        self.timeout = timeout or float(os.environ.get("LLM_TIMEOUT", "60.0"))
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    async def execute_with_retry(self, fn, *args, **kwargs) -> Any:
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                async with self.semaphore:
                    return await asyncio.wait_for(fn(*args, **kwargs), timeout=self.timeout)
            except Exception as e:
                last_exc = e
                if attempt < self.max_retries - 1 and is_retryable_error(e):
                    delay = self.backoff_base * (2 ** attempt)
                    logger.warning(
                        "LLM call attempt %d failed with retryable error: %s. Retrying in %.2fs",
                        attempt + 1,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise e
        if last_exc:
            raise last_exc

    @abc.abstractmethod
    async def generate_text(self, system: str, prompt: str, model: Optional[str] = None) -> str:
        """Generate plain text from prompt."""
        pass

    @abc.abstractmethod
    async def generate_json(
        self,
        system: str,
        prompt: str,
        schema: Optional[Type[BaseModel]] = None,
        model: Optional[str] = None,
    ) -> Any:
        """Generate structured JSON response, using response schema where available."""
        pass

    @abc.abstractmethod
    def get_models(self) -> list[str]:
        """List of available models for this provider."""
        pass

    @abc.abstractmethod
    def get_default_model(self) -> str:
        """Default model identifier for this provider."""
        pass
