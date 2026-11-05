import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import Response, Request

sys.path.insert(0, str(Path(__file__).parent.parent))

import ai_service
from llm import (
    AnthropicProvider,
    BaseLLMProvider,
    GeminiProvider,
    OpenAIProvider,
    get_available_models,
    get_default_model,
    get_llm_provider,
    parse_json_tolerant,
)
from llm.schemas import ApplicationEmailDraft, JobDescriptionParsed


@pytest.mark.asyncio
async def test_gemini_provider_success_structured_json(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake_gemini_key")
    provider = GeminiProvider(backoff_base=0.01)

    mock_response = MagicMock()
    mock_response.text = '{"subject": "Software Engineer Application", "body": "Dear Sarah,\\n\\nI am interested in the role."}'
    mock_response.parsed = None

    client_instance = MagicMock()
    client_instance.aio.models.generate_content = AsyncMock(return_value=mock_response)
    provider._client = client_instance

    result = await provider.generate_json(
        system="You are a career coach.",
        prompt="Write an email for software engineer role.",
        schema=ApplicationEmailDraft,
    )

    assert result is not None
    assert result["subject"] == "Software Engineer Application"
    assert "Dear Sarah" in result["body"]
    assert client_instance.aio.models.generate_content.call_count == 1


@pytest.mark.asyncio
async def test_gemini_provider_429_retry(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake_gemini_key")
    provider = GeminiProvider(max_retries=3, backoff_base=0.01)

    from google.genai.errors import APIError

    err_429 = APIError(code=429, response_json={"error": {"message": "Resource exhausted"}})

    mock_response = MagicMock()
    mock_response.text = '{"company_name": "Acme", "job_title": "Backend Dev", "required_skills": ["Python"], "experience_required": "3y", "description_summary": "Great role."}'
    mock_response.parsed = None

    client_instance = MagicMock()
    client_instance.aio.models.generate_content = AsyncMock(side_effect=[err_429, mock_response])
    provider._client = client_instance

    result = await provider.generate_json(
        system="Extract job data.",
        prompt="Job description text...",
        schema=JobDescriptionParsed,
    )

    assert result is not None
    assert result["company_name"] == "Acme"
    assert result["job_title"] == "Backend Dev"
    assert client_instance.aio.models.generate_content.call_count == 2


@pytest.mark.asyncio
async def test_gemini_provider_unset_api_key_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    provider = GeminiProvider()

    # Direct provider call raises clean RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        await provider.generate_text("System", "Prompt")
    assert "GEMINI_API_KEY is not set" in str(exc_info.value)

    # Calling high-level ai_service returns None cleanly without unhandled crash
    result = await ai_service.generate_application_email({"company_name": "Acme", "job_title": "Engineer"})
    assert result is None


@pytest.mark.asyncio
async def test_openai_provider_success_structured_json(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake_openai_key")
    provider = OpenAIProvider(backoff_base=0.01)

    mock_parsed_obj = ApplicationEmailDraft(
        subject="Senior Backend Lead",
        body="Dear Hiring Team,\n\nI am applying for the Senior Backend Lead position.",
    )
    mock_completion = MagicMock()
    mock_completion.choices = [
        MagicMock(message=MagicMock(parsed=mock_parsed_obj, content=None))
    ]

    client_instance = MagicMock()
    client_instance.beta.chat.completions.parse = AsyncMock(return_value=mock_completion)
    provider._client = client_instance

    result = await provider.generate_json(
        system="System",
        prompt="Prompt",
        schema=ApplicationEmailDraft,
    )

    assert result is not None
    assert result["subject"] == "Senior Backend Lead"
    assert "Senior Backend Lead" in result["body"]
    assert client_instance.beta.chat.completions.parse.call_count == 1


@pytest.mark.asyncio
async def test_openai_provider_429_retry(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake_openai_key")
    provider = OpenAIProvider(max_retries=3, backoff_base=0.01)

    import openai

    req = Request("POST", "https://api.openai.com/v1/chat/completions")
    resp_429 = Response(status_code=429, request=req)
    err_429 = openai.RateLimitError(message="Rate limit reached", response=resp_429, body={})

    mock_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = '{"company_name": "Tech Corp", "job_title": "DevOps", "required_skills": ["Docker"], "experience_required": "2y", "description_summary": "Infra role"}'
    mock_choice.message.parsed = None
    mock_completion.choices = [mock_choice]

    client_instance = MagicMock()
    client_instance.beta.chat.completions.parse = AsyncMock(side_effect=[err_429, mock_completion])
    client_instance.chat.completions.create = AsyncMock(return_value=mock_completion)
    provider._client = client_instance

    result = await provider.generate_json(
        system="System",
        prompt="Prompt",
        schema=JobDescriptionParsed,
    )

    assert result is not None
    assert result["company_name"] == "Tech Corp"
    assert client_instance.beta.chat.completions.parse.call_count == 2


@pytest.mark.asyncio
async def test_openai_provider_unset_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIProvider()

    with pytest.raises(RuntimeError) as exc_info:
        await provider.generate_text("System", "Prompt")
    assert "OPENAI_API_KEY is not set" in str(exc_info.value)


@pytest.mark.asyncio
async def test_anthropic_provider_success_structured_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake_anthropic_key")
    provider = AnthropicProvider(backoff_base=0.01)

    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = '{"subject": "Application for Frontend Engineer", "body": "Dear Alex,\\n\\nHere is my application."}'

    mock_response = MagicMock()
    mock_response.content = [mock_block]

    client_instance = MagicMock()
    client_instance.messages.create = AsyncMock(return_value=mock_response)
    provider._client = client_instance

    result = await provider.generate_json(
        system="System",
        prompt="Prompt",
        schema=ApplicationEmailDraft,
    )

    assert result is not None
    assert result["subject"] == "Application for Frontend Engineer"
    assert "Dear Alex" in result["body"]
    assert client_instance.messages.create.call_count == 1


@pytest.mark.asyncio
async def test_anthropic_provider_429_retry(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake_anthropic_key")
    provider = AnthropicProvider(max_retries=3, backoff_base=0.01)

    import anthropic

    req = Request("POST", "https://api.anthropic.com/v1/messages")
    resp_429 = Response(status_code=429, request=req)
    err_429 = anthropic.RateLimitError(message="Rate limit exceeded", response=resp_429, body={})

    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = '{"subject": "Follow-up", "body": "Following up politely."}'
    mock_response = MagicMock(content=[mock_block])

    client_instance = MagicMock()
    client_instance.messages.create = AsyncMock(side_effect=[err_429, mock_response])
    provider._client = client_instance

    result = await provider.generate_json(
        system="System",
        prompt="Prompt",
    )

    assert result is not None
    assert result["subject"] == "Follow-up"
    assert client_instance.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_anthropic_provider_unset_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = AnthropicProvider()

    with pytest.raises(RuntimeError) as exc_info:
        await provider.generate_text("System", "Prompt")
    assert "ANTHROPIC_API_KEY is not set" in str(exc_info.value)


def test_models_config_and_provider_switching(monkeypatch):
    # Gemini defaults
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert get_default_model() == "gemini-2.5-flash"
    gemini_models = get_available_models()
    assert "gemini-2.5-flash" in gemini_models
    assert "gemini-2.5-pro" in gemini_models

    # OpenAI selectable
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert get_default_model() == "gpt-5"
    openai_models = get_available_models()
    assert "gpt-5" in openai_models
    assert "gpt-4o" in openai_models

    # Anthropic selectable
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert get_default_model() == "claude-sonnet-5-5"
    anthropic_models = get_available_models()
    assert "claude-sonnet-5-5" in anthropic_models
    assert "claude-haiku-5-5" in anthropic_models


def test_tolerant_json_parser():
    # Plain JSON
    assert parse_json_tolerant('{"key": "value"}') == {"key": "value"}

    # Markdown block
    md = "```json\n{\n  \"score\": 98,\n  \"name\": \"Alice\"\n}\n```"
    assert parse_json_tolerant(md) == {"score": 98, "name": "Alice"}

    # Prose surrounded
    prose = "Here is the response requested:\n{\"subject\": \"Role\", \"body\": \"Details\"}\nHope this helps."
    assert parse_json_tolerant(prose) == {"subject": "Role", "body": "Details"}

    # Array
    assert parse_json_tolerant('[1, 2, 3]') == [1, 2, 3]

    # Non-parseable
    assert parse_json_tolerant("This is definitely not JSON.") is None
    assert parse_json_tolerant("") is None
