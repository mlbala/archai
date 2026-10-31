from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, ConfigDict
from typer.testing import CliRunner

from archai.architect_providers.anthropic import AnthropicArchitectProvider
from archai.architect_providers.deepseek import DeepSeekArchitectProvider, example_for
from archai.architect_providers.factory import (
    DEFAULT_MODELS,
    PROVIDERS,
    create_provider,
    resolve_role_bindings,
)
from archai.cli import app
from archai.config import Settings, parse_role_models
from archai.errors import ProviderError

runner = CliRunner()


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: str
    kinds: list[str]


def claude_message(text: str, stop_reason: str = "end_turn", fallback: bool = False):
    blocks = (
        [SimpleNamespace(type="text", text='{"service":"wrong","kinds":[]}')] if fallback else []
    )
    if fallback:
        blocks.append(SimpleNamespace(type="fallback"))
    blocks.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
    )


def streaming_client(*messages):
    calls: list[dict] = []
    queue = list(messages)

    @contextmanager
    def stream(**kwargs):
        calls.append(kwargs)
        yield SimpleNamespace(get_final_message=lambda: queue.pop(0))

    client = Mock()
    client.messages.stream.side_effect = stream
    client.beta.messages.stream.side_effect = stream
    return client, calls


def test_claude_uses_json_schema_output_effort_and_refusal_fallbacks():
    client, calls = streaming_client(claude_message('{"service":"Service Bus","kinds":["rag"]}'))
    provider = AnthropicArchitectProvider("key", "claude-opus-5-5")
    provider.client = client
    result = provider.generate("design", Plan)
    assert result.value.service == "Service Bus"
    assert result.usage.input_tokens == 11 and result.usage.output_tokens == 7
    request = calls[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert request["output_config"]["effort"] == "high"
    assert request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert "untrusted" in request["system"]


def test_claude_reads_text_after_fallback_and_skips_fallbacks_for_other_models():
    client, calls = streaming_client(
        claude_message('{"service":"SQS","kinds":["agent"]}', fallback=True)
    )
    provider = AnthropicArchitectProvider("key", "claude-haiku-5-5")
    provider.client = client
    assert provider.generate("design", Plan).value.service == "SQS"
    assert "fallbacks" not in calls[0]
    client.messages.stream.assert_called_once()


def test_claude_repairs_invalid_json_then_reports_refusal_and_truncation():
    client, calls = streaming_client(
        claude_message('{"service": 1}'), claude_message('{"service":"ok","kinds":[]}')
    )
    provider = AnthropicArchitectProvider("key", "claude-sonnet-5-5")
    provider.client = client
    assert provider.generate("design", Plan).value.service == "ok"
    assert "failed local schema validation" in calls[1]["messages"][0]["content"]
    for stop, kind in (("refusal", "refusal"), ("max_tokens", "truncated_output")):
        provider.client, _ = streaming_client(claude_message("{}", stop_reason=stop))
        with pytest.raises(ProviderError) as error:
            provider.generate("design", Plan)
        assert error.value.kind == kind


def test_claude_error_taxonomy():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(429, request=request)
    client = Mock()
    client.beta.messages.stream.side_effect = anthropic.RateLimitError(
        "slow down", response=response, body=None
    )
    provider = AnthropicArchitectProvider("key", "claude-opus-5-5")
    provider.client = client
    with pytest.raises(ProviderError) as error:
        provider.generate("design", Plan)
    assert error.value.kind == "rate_limit"


def test_deepseek_json_mode_with_schema_in_prompt_and_empty_content_retry():
    client = Mock()
    empty = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=""))],
        usage=None,
    )
    good = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content='{"service":"Service Bus","kinds":["rag"]}'),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=9),
    )
    client.chat.completions.create.side_effect = [empty, good]
    provider = DeepSeekArchitectProvider("key", "deepseek-v4-pro")
    provider.client = client
    result = provider.generate("design", Plan)
    assert result.value.kinds == ["rag"]
    assert result.usage.output_tokens == 9
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["model"] == "deepseek-v4-pro"
    prompt = kwargs["messages"][1]["content"]
    assert "json" in prompt and '"service"' in prompt and "Problems" in prompt


def test_deepseek_example_shape_follows_schema():
    from archai.architect_providers.base import inline_json_schema

    assert example_for(inline_json_schema(Plan)) == {"service": "...", "kinds": ["..."]}


def test_registry_defaults_keys_and_role_bindings(monkeypatch):
    assert set(PROVIDERS) == {"openai", "anthropic", "gemini", "deepseek"}
    assert DEFAULT_MODELS["anthropic"] == "claude-opus-5-5"
    assert DEFAULT_MODELS["deepseek"] == "deepseek-v4-pro"
    assert parse_role_models("verifier=anthropic:claude-sonnet-5-5,cloud=deepseek") == {
        "verifier": ("anthropic", "claude-sonnet-5-5"),
        "cloud": ("deepseek", None),
    }
    with pytest.raises(ValueError):
        parse_role_models("verifier=mistral:x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d-key")
    settings = Settings(_env_file=None, architect_provider="anthropic")
    assert isinstance(create_provider(settings, None, None), AnthropicArchitectProvider)
    assert isinstance(create_provider(settings, "deepseek", None), DeepSeekArchitectProvider)
    bindings = resolve_role_bindings(settings, None, None, ["verifier=deepseek:deepseek-flash"])
    assert bindings["cloud"].model == "claude-opus-5-5"
    assert (bindings["verifier"].provider, bindings["verifier"].model) == (
        "deepseek",
        "deepseek-flash",
    )
    with pytest.raises(ProviderError, match="ARCHAI_GEMINI_API_KEY"):
        create_provider(Settings(_env_file=None), "gemini", None)


def test_model_use_show_and_clear_write_private_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["model", "use", "anthropic"])
    assert result.exit_code == 0, result.output
    assert "Using anthropic · claude-opus-5-5 for all architect roles" in result.output
    assert "No anthropic API key found" in result.output
    env = (tmp_path / ".env").read_text()
    assert "ARCHAI_ARCHITECT_PROVIDER='anthropic'" in env
    assert "ARCHAI_ARCHITECT_MODEL='claude-opus-5-5'" in env
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600
    result = runner.invoke(
        app, ["model", "use", "deepseek", "deepseek-flash", "--role", "verifier"]
    )
    assert result.exit_code == 0, result.output
    assert (
        "ARCHAI_ROLE_MODELS='verifier=deepseek:deepseek-flash'" in (tmp_path / ".env").read_text()
    )
    monkeypatch.setattr("archai.config._env_files", lambda: (tmp_path / ".env",))
    shown = runner.invoke(app, ["model", "show"])
    assert shown.exit_code == 0, shown.output
    assert "claude-opus-5-5" in shown.output and "deepseek-flash" in shown.output
    cleared = runner.invoke(app, ["model", "clear"])
    assert cleared.exit_code == 0
    assert "ARCHAI_ROLE_MODELS" not in (tmp_path / ".env").read_text()
    bad = runner.invoke(app, ["model", "use", "mistral"])
    assert bad.exit_code == 3
    listed = runner.invoke(app, ["model", "list", "deepseek"])
    assert "deepseek-v4-pro" in listed.output and "(default)" in listed.output
    assert json.loads(runner.invoke(app, ["doctor"]).output)["anthropic_configuration"] == "missing"


def test_claude_caches_the_stable_instructions_and_counts_cache_reads():
    message = claude_message('{"service":"SQS","kinds":[]}')
    message.usage = SimpleNamespace(
        input_tokens=50,
        output_tokens=7,
        cache_read_input_tokens=4000,
        cache_creation_input_tokens=0,
    )
    client, calls = streaming_client(message)
    provider = AnthropicArchitectProvider("key", "claude-haiku-5-5")
    provider.client = client
    prompt = "instructions " * 400 + "\n# Context\n<untrusted>{}</untrusted>"
    result = provider.generate(prompt, Plan)
    content = calls[0]["messages"][0]["content"]
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert content[1]["text"].startswith("\n# Context\n")
    assert "cache_control" not in content[1]
    assert result.usage.input_tokens == 4050
    assert result.usage.cached_input_tokens == 4000
