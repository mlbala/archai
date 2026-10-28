"""DeepSeek adapter: OpenAI-compatible Chat Completions in JSON mode, validated locally.

DeepSeek's JSON Output mode guarantees a JSON object but not a schema, so the schema and an
example are placed in the prompt (DeepSeek requires the word "json" and a format example), and the
result is validated against the Pydantic model with bounded repair attempts.
"""

from __future__ import annotations

import json
from typing import Any

import openai
from pydantic import BaseModel, ValidationError

from archai.architect_providers.base import (
    SYSTEM_INSTRUCTION,
    StructuredResult,
    Usage,
    inline_json_schema,
)
from archai.errors import ProviderError

DEFAULT_BASE_URL = "https://api.deepseek.com"


def example_for(schema: dict[str, Any]) -> Any:
    """A small placeholder instance that shows the JSON shape the schema expects."""
    kind = schema.get("type")
    if "enum" in schema:
        return schema["enum"][0]
    if kind == "object":
        return {key: example_for(value) for key, value in schema.get("properties", {}).items()}
    if kind == "array":
        return [example_for(schema.get("items", {}))]
    if kind == "integer":
        return 1
    if kind == "number":
        return 0.5
    if kind == "boolean":
        return True
    if "anyOf" in schema:
        return example_for(next(iter(schema["anyOf"])))
    return "..."


class DeepSeekArchitectProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        repair_attempts: int = 2,
        timeout_seconds: int = 300,
        base_url: str = DEFAULT_BASE_URL,
        max_tokens: int = 32_000,
    ) -> None:
        self.client = openai.OpenAI(
            api_key=api_key, base_url=base_url, max_retries=0, timeout=float(timeout_seconds)
        )
        self.model = model
        self.repair_attempts = repair_attempts
        self.max_tokens = max_tokens

    def generate[T: BaseModel](self, prompt: str, output_type: type[T]) -> StructuredResult[T]:
        schema = inline_json_schema(output_type)
        instructions = (
            "\n\nReturn one json object that matches this JSON Schema exactly: every property is "
            "required and no other properties are allowed.\nJSON Schema:\n"
            + json.dumps(schema, separators=(",", ":"))
            + "\nExample json shape (replace the placeholder values):\n"
            + json.dumps(example_for(schema), separators=(",", ":"))
        )
        current_prompt = prompt + instructions
        last_error: Exception | None = None
        for attempt in range(self.repair_attempts + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_INSTRUCTION + " Output json only."},
                        {"role": "user", "content": current_prompt},
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=self.max_tokens,
                )
            except openai.APIError as exc:
                raise _mapped(exc, self.model) from exc
            choice = response.choices[0] if response.choices else None
            if choice is not None and choice.finish_reason == "length":
                raise ProviderError("DeepSeek output was truncated", kind="truncated_output")
            if choice is not None and choice.finish_reason == "content_filter":
                raise ProviderError("DeepSeek declined the request", kind="refusal")
            text = (choice.message.content or "").strip() if choice is not None else ""
            try:
                if not text:
                    raise ValueError("DeepSeek returned empty content")
                value = output_type.model_validate_json(text)
            except (ValidationError, ValueError) as exc:
                last_error = exc
                if attempt >= self.repair_attempts:
                    break
                detail = (
                    exc.errors(include_url=False)[:8] if isinstance(exc, ValidationError) else exc
                )
                current_prompt = (
                    f"{prompt}{instructions}\n\nYour previous reply was not valid for the schema. "
                    f"Return the corrected json object only. Problems: {detail}"
                )
                continue
            usage: Any = response.usage
            return StructuredResult(
                value=value,
                usage=Usage(
                    input_tokens=getattr(usage, "prompt_tokens", None),
                    output_tokens=getattr(usage, "completion_tokens", None),
                ),
            )
        raise ProviderError(f"DeepSeek schema repair exhausted: {last_error}", kind="schema_error")


def _mapped(exc: openai.APIError, model: str) -> ProviderError:
    if isinstance(exc, openai.AuthenticationError):
        return ProviderError(
            "DeepSeek rejected the API key (401); check ARCHAI_DEEPSEEK_API_KEY.",
            kind="authentication",
        )
    if isinstance(exc, openai.PermissionDeniedError):
        return ProviderError("DeepSeek denied access (403).", kind="permission")
    if isinstance(exc, openai.NotFoundError):
        return ProviderError(f"DeepSeek model {model!r} was not found (404).", kind="configuration")
    if isinstance(exc, openai.RateLimitError):
        return ProviderError(
            "DeepSeek rate limit or balance limit reached (429).", kind="rate_limit"
        )
    if isinstance(exc, openai.APITimeoutError):
        return ProviderError("DeepSeek request timed out.", kind="timeout")
    if isinstance(exc, openai.BadRequestError):
        return ProviderError(f"DeepSeek rejected the request: {exc.message}", kind="configuration")
    if isinstance(exc, openai.APIStatusError) and exc.status_code == 402:
        return ProviderError("DeepSeek account balance is insufficient (402).", kind="rate_limit")
    if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
        return ProviderError(f"DeepSeek server error ({exc.status_code}).", kind="server_error")
    if isinstance(exc, openai.APIConnectionError):
        return ProviderError("Could not reach the DeepSeek API (network).", kind="server_error")
    return ProviderError(f"DeepSeek request failed ({type(exc).__name__}).", kind="provider_error")
