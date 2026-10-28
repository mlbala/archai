from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from archai.application.extraction import RequirementsExtraction, extract_requirements
from archai.architect_providers.base import StructuredResult, Usage
from archai.architect_providers.factory import create_provider, selected_model
from archai.architect_providers.gemini import GeminiArchitectProvider
from archai.architect_providers.openai import OpenAIArchitectProvider
from archai.config import Settings
from archai.errors import ProviderError


class Answer(BaseModel):
    value: str


def test_openai_responses_parse_and_usage():
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(
        status="completed",
        output_parsed=Answer(value="hello"),
        output=[],
        usage=SimpleNamespace(input_tokens=12, output_tokens=4),
    )
    provider = OpenAIArchitectProvider("test-key", "test-model")
    provider.client = client
    result = provider.generate("extract", Answer)
    assert result.value.value == "hello"
    assert result.usage == Usage(input_tokens=12, output_tokens=4)
    assert client.responses.parse.call_args.kwargs["model"] == "test-model"
    assert client.responses.parse.call_args.kwargs["text_format"] is Answer


def test_gemini_four_uses_structured_output_without_sampling_parameters():
    client = Mock()
    client.models.generate_content.return_value = SimpleNamespace(
        text='{"value":"hello"}',
        usage_metadata=SimpleNamespace(prompt_token_count=8, candidates_token_count=2),
    )
    provider = GeminiArchitectProvider("test-key", "gemini-4-argon")
    provider.client = client
    result = provider.generate("extract", Answer)
    kwargs = client.models.generate_content.call_args.kwargs
    assert result.value.value == "hello"
    assert kwargs["model"] == "gemini-4-argon"
    assert kwargs["config"].response_schema is Answer
    assert kwargs["config"].temperature is None


def test_current_default_model_selection():
    from archai.architect_providers.factory import DEFAULT_MODELS

    assert DEFAULT_MODELS == {"gemini": "gemini-3.1-pro-preview", "openai": "gpt-6-luna"}


def test_openai_refusal_is_reported_without_retry():
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(
        status="completed",
        output_parsed=None,
        output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])],
        usage=None,
    )
    provider = OpenAIArchitectProvider("test-key", "test-model")
    provider.client = client
    with pytest.raises(ProviderError, match="refused"):
        provider.generate("extract", Answer)
    assert client.responses.parse.call_count == 1


def test_missing_key_reports_provider_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ARCHAI_OPENAI_API_KEY", raising=False)
    settings = Settings(_env_file=None, openai_api_key=None)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        create_provider(settings, "openai", "example")


def test_provider_override_does_not_reuse_other_provider_model():
    settings = Settings(
        _env_file=None, architect_provider="gemini", architect_model="gemini-custom"
    )
    assert selected_model(settings, "openai", None) == "gpt-6-luna"
    assert selected_model(settings, "openai", "my-model") == "my-model"


def test_extraction_rejects_unsupported_quotes_and_preserves_answers():
    provider = Mock()
    provider.generate.return_value = StructuredResult(
        value=RequirementsExtraction.model_validate(
            {
                "facts": [
                    {
                        "field": "business_outcome",
                        "value": "reduce cost",
                        "source_quote": "reduce cost",
                    },
                    {"field": "users", "value": "finance", "source_quote": "not in source"},
                    {"field": "archetypes", "value": "RAG", "source_quote": "use RAG"},
                ]
            }
        ),
        usage=Usage(input_tokens=1, output_tokens=2),
    )
    merged, usage = extract_requirements(
        provider, "We want to reduce cost and use RAG", {"business_outcome": "manual"}
    )
    assert merged["business_outcome"] == "manual"
    assert "users" not in merged
    assert merged["archetypes"] == ["RAG"]
    assert "tool_side_effects" not in merged
    assert usage.input_tokens == 1
