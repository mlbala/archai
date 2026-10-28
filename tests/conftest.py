from __future__ import annotations

from pathlib import Path
from typing import Any, get_args, get_origin

import pytest
from pydantic import BaseModel

from archai.architect_providers.base import StructuredResult, Usage


@pytest.fixture(autouse=True)
def isolate_provider_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never load a developer's .env or make an accidental billed call."""
    for name in (
        "OPENAI_API_KEY",
        "ARCHAI_OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ARCHAI_GEMINI_API_KEY",
        "ARCHAI_ARCHITECT_MODEL",
        "ARCHAI_ARCHITECT_PROVIDER",
        "ARCHAI_ROLE_MODELS",
        "ARCHAI_OUTPUT_DIR",
        "ANTHROPIC_API_KEY",
        "ARCHAI_ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "ARCHAI_DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("archai.config._env_files", lambda: ())


@pytest.fixture
def requirements_file() -> Path:
    return Path("examples/azure-enterprise-rag/requirements.yaml")


def fake_value(annotation: Any, name: str = "value") -> Any:
    """Build a schema-valid placeholder for any proposal field type."""
    origin = get_origin(annotation)
    if origin is list:
        return [fake_value(get_args(annotation)[0], name)]
    if origin is not None and str(origin).endswith("Literal"):
        return get_args(annotation)[0]
    if origin is not None and type(None) in get_args(annotation):
        inner = next(arg for arg in get_args(annotation) if arg is not type(None))
        return fake_value(inner, name)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {
            field: fake_value(info.annotation, field)
            for field, info in annotation.model_fields.items()
        }
    if annotation is bool:
        return True
    if annotation is int:
        return 8
    if annotation is float:
        return 0.5
    return f"{name}-text"


class FakeArchitect:
    """Deterministic structured-output provider for tests; records every prompt."""

    def __init__(self, overrides: dict[str, Any] | None = None) -> None:
        self.prompts: list[tuple[str, str]] = []
        self.overrides = overrides or {}

    def generate(self, prompt: str, output_type: type[BaseModel]) -> StructuredResult[Any]:
        self.prompts.append((output_type.__name__, prompt))
        data = fake_value(output_type)
        for key, value in self.overrides.get(output_type.__name__, {}).items():
            data[key] = value
        return StructuredResult(
            value=output_type.model_validate(data), usage=Usage(input_tokens=100, output_tokens=50)
        )


@pytest.fixture
def fake_architect() -> FakeArchitect:
    return FakeArchitect()
