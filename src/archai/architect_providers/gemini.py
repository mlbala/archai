from __future__ import annotations

from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from archai.architect_providers.base import (
    SYSTEM_INSTRUCTION,
    StructuredResult,
    Usage,
    inline_json_schema,
)
from archai.errors import ProviderError


class GeminiArchitectProvider:
    """Gemini structured-output adapter with bounded local repair validation."""

    def __init__(
        self,
        api_key: str,
        model: str,
        repair_attempts: int = 2,
        timeout_seconds: int = 300,
    ) -> None:
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout_seconds * 1000),
        )
        self.model = model
        self.repair_attempts = repair_attempts

    def generate[T: BaseModel](self, prompt: str, output_type: type[T]) -> StructuredResult[T]:
        current_prompt = prompt
        last_error: Exception | None = None
        schema = inline_json_schema(output_type)
        for attempt in range(self.repair_attempts + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=current_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_json_schema=schema,
                    ),
                )
                candidates: Any = getattr(response, "candidates", None) or []
                finish = str(getattr(candidates[0], "finish_reason", "")) if candidates else ""
                if not response.text:
                    if "SAFETY" in finish or "PROHIBITED" in finish:
                        raise ProviderError("Gemini refused the request", kind="refusal")
                    raise ProviderError("Gemini returned no content", kind="malformed_output")
                if "MAX_TOKENS" in finish:
                    raise ProviderError("Gemini output was truncated", kind="truncated_output")
                value = output_type.model_validate_json(response.text)
                metadata: Any = getattr(response, "usage_metadata", None)
                thoughts = getattr(metadata, "thoughts_token_count", None) or 0
                output_tokens = getattr(metadata, "candidates_token_count", None)
                return StructuredResult(
                    value=value,
                    usage=Usage(
                        input_tokens=getattr(metadata, "prompt_token_count", None),
                        output_tokens=(output_tokens or 0) + thoughts
                        if output_tokens is not None or thoughts
                        else None,
                    ),
                )
            except ValidationError as exc:
                last_error = exc
                if attempt >= self.repair_attempts:
                    break
                current_prompt = (
                    f"{prompt}\n\nYour prior JSON failed local schema validation. "
                    f"Return corrected JSON only. Errors: {exc.errors(include_url=False)[:8]}"
                )
            except errors.APIError as exc:
                code = getattr(exc, "code", None)
                if code == 401:
                    kind = "authentication"
                elif code == 403:
                    kind = "permission"
                elif code == 404:
                    kind = "configuration"
                elif code == 429:
                    kind = "rate_limit"
                elif code and code >= 500:
                    kind = "server_error"
                else:
                    kind = "provider_error"
                raise ProviderError(_describe(exc, kind), kind=kind) from exc
            except TimeoutError as exc:
                raise ProviderError("Gemini timeout", kind="timeout") from exc
        raise ProviderError(f"Gemini schema repair exhausted: {last_error}", kind="schema_error")


def _describe(exc: Exception, kind: str) -> str:
    """Short, actionable message without the raw error payload."""
    status = getattr(exc, "status", None) or ""
    message = str(getattr(exc, "message", None) or exc).split("\n")[0][:160]
    text = str(exc)
    if kind == "rate_limit" and ("FreeTier" in text or "free_tier" in text or "quota" in text):
        return (
            "Gemini quota exhausted for this model (the key appears to be on the free tier). "
            "Use a paid Gemini key, another model (--architect-model), or another provider."
        )
    if kind == "rate_limit":
        return "Gemini rate limit reached (429); retry later or reduce parallel roles."
    if kind == "authentication":
        return "Gemini rejected the API key (401); check ARCHAI_GEMINI_API_KEY."
    if kind == "permission":
        return "Gemini denied access (403); check the key's project and model access."
    if kind == "configuration":
        return f"Gemini model not found or unavailable for this key (404): {message}"
    return f"Gemini {kind} {status}: {message}".strip()
