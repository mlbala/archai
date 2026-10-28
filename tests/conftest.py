from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def requirements_file() -> Path:
    return Path("examples/azure-enterprise-rag/requirements.yaml")
