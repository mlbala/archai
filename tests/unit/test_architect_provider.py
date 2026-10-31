from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from archai.application.extraction import apply_quoted_suggestions, interview_suggestions
from archai.architect_providers.base import Usage, inline_json_schema
from archai.architect_providers.factory import create_provider, selected_model
from archai.architect_providers.gemini import GeminiArchitectProvider
from archai.architect_providers.openai import OpenAIArchitectProvider
from archai.config import Settings
from archai.errors import ProviderError
from archai.schemas.proposals import RequirementsAnalysis, scoped_proposal_model


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
    assert kwargs["config"].response_json_schema["properties"]["value"]["type"] == "string"
    assert kwargs["config"].response_schema is None
    assert kwargs["config"].temperature is None


def test_current_default_model_selection():
    from archai.architect_providers.factory import DEFAULT_MODELS

    assert DEFAULT_MODELS == {
        "openai": "gpt-6-sol",
        "anthropic": "claude-opus-5-5",
        "gemini": "gemini-3.1-pro-preview",
        "deepseek": "deepseek-v4-pro",
    }


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
    assert selected_model(settings, "openai", None) == "gpt-6-sol"
    assert selected_model(settings, "openai", "my-model") == "my-model"


def _analysis(*suggestions: dict[str, str]) -> RequirementsAnalysis:
    return RequirementsAnalysis.model_validate(
        {
            "summary": "s",
            "suggestions": list(suggestions),
            "clarifying_questions": [],
            "detected_risks": [],
        }
    )


def test_extraction_rejects_unsupported_quotes_and_preserves_answers():
    analysis = _analysis(
        {
            "field": "business_outcome",
            "value": "reduce cost",
            "rationale": "",
            "source_quote": "reduce cost",
        },
        {"field": "users", "value": "finance", "rationale": "", "source_quote": "not in source"},
        {"field": "archetypes", "value": "RAG", "rationale": "", "source_quote": "use RAG"},
        {"field": "tool_side_effects", "value": "allowed", "rationale": "", "source_quote": ""},
    )
    merged = apply_quoted_suggestions(
        analysis, {"business_outcome": "manual"}, "We want to reduce cost and use RAG"
    )
    assert merged["business_outcome"] == "manual"
    assert "users" not in merged
    assert merged["archetypes"] == ["RAG"]
    assert "tool_side_effects" not in merged


def test_assumptions_only_for_noncritical_fields_when_allowed():
    analysis = _analysis(
        {"field": "latency_p95_ms", "value": "6000", "rationale": "chat", "source_quote": ""},
        {"field": "monthly_budget", "value": "5000", "rationale": "guess", "source_quote": ""},
    )
    blocked = apply_quoted_suggestions(analysis, {}, "text")
    assert "latency_p95_ms" not in blocked
    allowed = apply_quoted_suggestions(analysis, {}, "text", allow_assumptions=True)
    assert allowed["latency_p95_ms"] == 6000
    assert "monthly_budget" not in allowed
    assert allowed["assumptions"][0]["id"] == "assumption-latency-p95-ms"


def test_interview_suggestions_are_typed_and_skip_answered_fields():
    analysis = _analysis(
        {
            "field": "archetypes",
            "value": "1, tool-using-agent",
            "rationale": "r",
            "source_quote": "grounded answers",
        },
        {"field": "region", "value": "westeurope", "rationale": "EU users", "source_quote": ""},
        {"field": "avg_rps", "value": "not a number", "rationale": "", "source_quote": ""},
    )
    suggestions = interview_suggestions(analysis, {"region": "eastus"})
    assert suggestions["archetypes"].value == ["enterprise-rag", "tool-using-agent"]
    assert "grounded answers" in suggestions["archetypes"].rationale
    assert "region" not in suggestions
    assert "avg_rps" not in suggestions


def test_proposal_schemas_are_strict_and_inlinable():
    model = scoped_proposal_model("cloud", ["system", "data", "infra"])
    schema = inline_json_schema(model)
    assert "$ref" not in str(schema)
    assert set(schema["required"]) == {"services", "data_stores", "infra", "decisions"}
    assert schema["additionalProperties"] is False


def test_openai_sends_a_stable_cache_key_and_reports_cached_tokens():
    from archai.architect_providers.base import cache_key

    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(
        status="completed",
        output_parsed=Answer(value="hello"),
        output=[],
        usage=SimpleNamespace(
            input_tokens=5000,
            output_tokens=4,
            input_tokens_details=SimpleNamespace(cached_tokens=3584),
        ),
    )
    provider = OpenAIArchitectProvider("test-key", "test-model")
    provider.client = client
    stable = "instructions " * 400
    first = provider.generate(stable + "\n# Context\nrun one", Answer)
    provider.generate(stable + "\n# Context\nrun two", Answer)
    keys = [call.kwargs["prompt_cache_key"] for call in client.responses.parse.call_args_list]
    assert keys[0] == keys[1] == cache_key(stable + "\n# Context\nanything")
    assert first.usage.cached_input_tokens == 3584
    assert cache_key("short\n# Context\nx") != keys[0]
