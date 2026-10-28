from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_provider_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never load a developer's .env or make an accidental billed call."""
    from archai.config import Settings

    for name in (
        "OPENAI_API_KEY",
        "ARCHAI_OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ARCHAI_GEMINI_API_KEY",
        "ARCHAI_ARCHITECT_MODEL",
        "ARCHAI_ARCHITECT_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("archai.application.service.Settings", lambda: Settings(_env_file=None))


@pytest.fixture
def requirements_file() -> Path:
    return Path("examples/azure-enterprise-rag/requirements.yaml")
