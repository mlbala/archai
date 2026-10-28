from __future__ import annotations

from typing import Any

import openai
from pydantic import BaseModel, ValidationError

from archai.architect_providers.base import SYSTEM_INSTRUCTION, StructuredResult, Usage
from archai.errors import ProviderError


class OpenAIArchitectProvider:
    """OpenAI Responses structured-output adapter with bounded local validation."""

    def __init__(
        self,
        api_key: str,
        model: str,
        repair_attempts: int = 2,
        timeout_seconds: int = 300,
    ) -> None:
        self.client = openai.OpenAI(api_key=api_key, max_retries=0, timeout=float(timeout_seconds))
        self.model = model
        self.repair_attempts = repair_attempts

    def generate[T: BaseModel](self, prompt: str, output_type: type[T]) -> StructuredResult[T]:
        current_prompt = prompt
        for attempt in range(self.repair_attempts + 1):
            try:
                response = self.client.responses.parse(
                    model=self.model,
                    input=[
                        {"role": "system", "content": SYSTEM_INSTRUCTION},
                        {"role": "user", "content": current_prompt},
                    ],
                    text_format=output_type,
                )
                if response.status == "incomplete":
                    raise ProviderError(
                        "OpenAI response was incomplete (truncated)", kind="truncated_output"
                    )
                if response.output_parsed is None:
                    for item in response.output:
                        for part in getattr(item, "content", None) or []:
                            if getattr(part, "type", "") == "refusal":
                                raise ProviderError("OpenAI refused the request", kind="refusal")
                    raise ProviderError(
                        "OpenAI returned no structured output", kind="malformed_output"
                    )
                value = output_type.model_validate(response.output_parsed.model_dump())
                usage: Any = response.usage
                return StructuredResult(
                    value=value,
                    usage=Usage(
                        input_tokens=getattr(usage, "input_tokens", None),
                        output_tokens=getattr(usage, "output_tokens", None),
                    ),
                )
            except ValidationError as exc:
                if attempt == self.repair_attempts:
                    raise ProviderError(
                        "OpenAI schema validation failed after bounded repair", kind="schema_error"
                    ) from exc
                current_prompt = f"{prompt}\nReturn corrected JSON matching the schema."
            except openai.AuthenticationError as exc:
                raise ProviderError(
                    "OpenAI authentication failed; check your API key", kind="authentication"
                ) from exc
            except openai.PermissionDeniedError as exc:
                raise ProviderError(
                    "OpenAI access denied; check model and project permissions", kind="permission"
                ) from exc
            except openai.NotFoundError as exc:
                raise ProviderError(
                    f"OpenAI model {self.model!r} was not found for this account",
                    kind="configuration",
                ) from exc
            except openai.RateLimitError as exc:
                raise ProviderError(
                    "OpenAI rate limit or quota exceeded", kind="rate_limit"
                ) from exc
            except openai.APITimeoutError as exc:
                raise ProviderError("OpenAI request timed out", kind="timeout") from exc
            except openai.BadRequestError as exc:
                raise ProviderError(
                    f"OpenAI rejected the request: {exc.message}", kind="configuration"
                ) from exc
            except openai.APIError as exc:
                raise ProviderError(
                    f"OpenAI request failed ({type(exc).__name__})", kind="server_error"
                ) from exc
        raise ProviderError("OpenAI structured-output repair exhausted", kind="schema_error")
