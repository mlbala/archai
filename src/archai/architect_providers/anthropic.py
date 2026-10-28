"""Anthropic Claude adapter: Messages API with JSON-schema structured output and local validation."""

from __future__ import annotations

from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from archai.architect_providers.base import (
    SYSTEM_INSTRUCTION,
    StructuredResult,
    Usage,
    inline_json_schema,
)
from archai.errors import ProviderError

# Models that accept the server-side refusal fallback ("default" routes by refusal category).
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicArchitectProvider:
    """Claude structured-output adapter with bounded local repair validation.

    Requests stream (long structured designs would otherwise risk HTTP timeouts) and the final
    message is validated locally against the Pydantic schema, like every other ArchAI provider.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        repair_attempts: int = 2,
        timeout_seconds: int = 300,
        effort: str | None = "high",
        fallbacks: bool = True,
        max_tokens: int = 64_000,
    ) -> None:
        self.client = anthropic.Anthropic(api_key=api_key, timeout=float(timeout_seconds))
        self.model = model
        self.repair_attempts = repair_attempts
        self.effort = effort or None
        self.fallbacks = fallbacks
        self.max_tokens = max_tokens

    def _request(self, prompt: str, schema: dict[str, Any]) -> Any:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        if self.effort:
            output_config["effort"] = self.effort
        messages: list[Any] = [{"role": "user", "content": prompt}]
        if self.fallbacks and self.model in FALLBACK_MODELS:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_INSTRUCTION,
                messages=messages,
                output_config=output_config,  # type: ignore[arg-type]
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                return stream.get_final_message()
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_INSTRUCTION,
            messages=messages,
            output_config=output_config,  # type: ignore[arg-type]
        ) as stream:
            return stream.get_final_message()

    def generate[T: BaseModel](self, prompt: str, output_type: type[T]) -> StructuredResult[T]:
        schema = inline_json_schema(output_type)
        current_prompt = prompt
        last_error: Exception | None = None
        for attempt in range(self.repair_attempts + 1):
            try:
                message = self._request(current_prompt, schema)
            except anthropic.BadRequestError as exc:
                if self.effort and "effort" in str(exc.message).lower():
                    self.effort = None  # this model does not take an effort setting
                    message = self._call_mapped(current_prompt, schema)
                else:
                    raise ProviderError(
                        f"Claude rejected the request: {exc.message}", kind="configuration"
                    ) from exc
            except anthropic.APIError as exc:
                raise _mapped(exc, self.model) from exc
            if message.stop_reason == "refusal":
                raise ProviderError("Claude declined the request", kind="refusal")
            if message.stop_reason == "max_tokens":
                raise ProviderError("Claude output was truncated", kind="truncated_output")
            text = _final_text(message)
            if not text:
                raise ProviderError("Claude returned no structured output", kind="malformed_output")
            try:
                value = output_type.model_validate_json(text)
            except ValidationError as exc:
                last_error = exc
                if attempt >= self.repair_attempts:
                    break
                current_prompt = (
                    f"{prompt}\n\nYour prior JSON failed local schema validation. Return corrected "
                    f"JSON only. Errors: {exc.errors(include_url=False)[:8]}"
                )
                continue
            usage: Any = message.usage
            return StructuredResult(
                value=value,
                usage=Usage(
                    input_tokens=getattr(usage, "input_tokens", None),
                    output_tokens=getattr(usage, "output_tokens", None),
                ),
            )
        raise ProviderError(f"Claude schema repair exhausted: {last_error}", kind="schema_error")

    def _call_mapped(self, prompt: str, schema: dict[str, Any]) -> Any:
        try:
            return self._request(prompt, schema)
        except anthropic.APIError as exc:
            raise _mapped(exc, self.model) from exc


def _final_text(message: Any) -> str:
    """Text produced by the model that finished the turn (after any fallback switch point)."""
    blocks = list(getattr(message, "content", None) or [])
    last_fallback = max(
        (index for index, block in enumerate(blocks) if getattr(block, "type", "") == "fallback"),
        default=-1,
    )
    return "".join(
        getattr(block, "text", "")
        for block in blocks[last_fallback + 1 :]
        if getattr(block, "type", "") == "text"
    ).strip()


def _mapped(exc: anthropic.APIError, model: str) -> ProviderError:
    if isinstance(exc, anthropic.AuthenticationError):
        return ProviderError(
            "Claude rejected the API key (401); check ARCHAI_ANTHROPIC_API_KEY.",
            kind="authentication",
        )
    if isinstance(exc, anthropic.PermissionDeniedError):
        return ProviderError("Claude denied access (403) for this key.", kind="permission")
    if isinstance(exc, anthropic.NotFoundError):
        return ProviderError(
            f"Claude model {model!r} was not found for this key (404).", kind="configuration"
        )
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderError("Claude rate limit or quota reached (429).", kind="rate_limit")
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderError("Claude request timed out.", kind="timeout")
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError("Could not reach the Claude API (network).", kind="server_error")
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return ProviderError(f"Claude server error ({exc.status_code}).", kind="server_error")
    return ProviderError(f"Claude request failed ({type(exc).__name__}).", kind="provider_error")
