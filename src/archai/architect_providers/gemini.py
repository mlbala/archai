from __future__ import annotations

from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from archai.architect_providers.base import StructuredResult, Usage
from archai.errors import ProviderError


class GeminiArchitectProvider:
    """Gemini structured-output adapter with bounded local repair validation."""

    def __init__(self, api_key: str, model: str, repair_attempts: int = 2) -> None:
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.repair_attempts = repair_attempts

    def generate[T: BaseModel](self, prompt: str, output_type: type[T]) -> StructuredResult[T]:
        current_prompt = prompt
        last_error: Exception | None = None
        for attempt in range(self.repair_attempts + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=current_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=output_type,
                        temperature=0.1,
                    ),
                )
                if not response.text:
                    raise ProviderError("architect provider returned no content")
                value = output_type.model_validate_json(response.text)
                metadata: Any = getattr(response, "usage_metadata", None)
                return StructuredResult(
                    value=value,
                    usage=Usage(
                        input_tokens=getattr(metadata, "prompt_token_count", None),
                        output_tokens=getattr(metadata, "candidates_token_count", None),
                    ),
                )
            except ValidationError as exc:
                last_error = exc
                if attempt >= self.repair_attempts:
                    break
                current_prompt = (
                    f"{prompt}\n\nYour prior JSON failed local schema validation. "
                    f"Return corrected JSON only. Errors: {exc.errors(include_url=False)}"
                )
            except errors.APIError as exc:
                code = getattr(exc, "code", None)
                if code in {401, 403}:
                    kind = "authentication"
                elif code == 429:
                    kind = "rate_limit"
                elif code and code >= 500:
                    kind = "server_error"
                else:
                    kind = "provider_error"
                raise ProviderError(f"Gemini {kind}: {exc}") from exc
            except TimeoutError as exc:
                raise ProviderError("Gemini timeout") from exc
        raise ProviderError(f"Gemini schema repair exhausted: {last_error}")
