from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from archai.errors import IncompleteRequirementsError
from archai.schemas.models import RequirementsSpec

CRITICAL_FIELDS = (
    "idea",
    "business_outcome",
    "users",
    "archetypes",
    "region",
    "data_residency",
    "tenant_isolation",
    "allowed_target_providers",
    "tool_side_effects",
    "avg_rps",
    "peak_rps",
    "input_tokens",
    "output_tokens",
    "model_calls_per_request",
    "monthly_budget",
    "currency",
    "availability_target",
)


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    elif path.suffix.lower() in {".yaml", ".yml"}:
        value = yaml.safe_load(text)
    else:
        return {"idea": text.strip()}
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def merge_inputs(
    files: list[Path],
    idea: str | None,
    stdin_text: str | None,
    answers: Path | None,
    profile: str | None,
    region: str | None,
    target_providers: str | None,
    topology: str | None,
    archetypes: list[str],
) -> tuple[dict[str, Any], list[tuple[Path, str]]]:
    merged: dict[str, Any] = {}
    raw_sources: list[tuple[Path, str]] = []
    for path in files:
        resolved = path.resolve()
        text = resolved.read_text(encoding="utf-8")
        raw_sources.append((resolved, text))
        data = load_structured(resolved)
        for key, value in data.items():
            if key in merged and merged[key] != value:
                conflicts = merged.setdefault("conflicts", [])
                conflicts.append(
                    {
                        "id": f"conflict-{key}",
                        "field": key,
                        "values": [merged[key], value],
                        "message": f"Conflicting source values for {key}",
                        "blocking": True,
                    }
                )
            else:
                merged[key] = value
    if idea:
        merged["idea"] = idea
    if stdin_text:
        merged["idea"] = "\n\n".join(filter(None, [merged.get("idea"), stdin_text]))
    if answers:
        for key, value in load_structured(answers.resolve()).items():
            merged[key] = value
    if profile:
        merged["profile"] = profile
    if region:
        merged["region"] = region
    if target_providers:
        merged["allowed_target_providers"] = [
            item.strip() for item in target_providers.split(",") if item.strip()
        ]
    if topology:
        merged["topology"] = topology
    if archetypes:
        merged["archetypes"] = archetypes
    merged.setdefault("profile", "azure-aca")
    merged.setdefault("topology", "single-cloud")
    merged.setdefault("assumptions", [])
    merged.setdefault("conflicts", [])
    merged.setdefault("evidence", [])
    return merged, raw_sources


def parse_requirements(data: dict[str, Any]) -> RequirementsSpec:
    missing = [name for name in CRITICAL_FIELDS if data.get(name) in (None, "", [])]
    if missing:
        question_ids = [f"REQ-{name.upper()}" for name in missing]
        raise IncompleteRequirementsError(
            "Missing critical requirements: "
            + ", ".join(missing)
            + ". Question IDs: "
            + ", ".join(question_ids)
        )
    if any(item.get("blocking", True) for item in data.get("conflicts", [])):
        raise IncompleteRequirementsError("Conflicting source requirements must be resolved")
    return RequirementsSpec.model_validate(data)


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug or slug in {".", ".."}:
        raise ValueError("project name must contain letters or digits")
    return slug[:80]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
