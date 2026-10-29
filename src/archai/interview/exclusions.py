"""Optional parts of a design that a workload can leave out."""

from __future__ import annotations

import re
from typing import Any

# Interview labels and free-text names map to component ids.
OPTIONAL_COMPONENT_ALIASES: dict[str, str] = {
    "cache": "cache",
    "rbac": "auth",
    "auth": "auth",
    "authorization": "auth",
    "cloud deployment": "infra",
    "deployment": "infra",
    "infrastructure": "infra",
    "hosting": "infra",
    "infra": "infra",
    "retrieval": "rag",
    "rag": "rag",
    "observability": "observe",
    "observe": "observe",
    "evaluation": "eval",
    "eval": "eval",
    "workflows": "workflow",
    "workflow": "workflow",
    "guardrails": "guard",
    "guard": "guard",
    "resilience": "resilience",
}

# Question field -> component that answer can turn off.
QUESTION_COMPONENT: dict[str, str] = {
    "profile": "infra",
    "existing_services": "infra",
    "user_roles": "auth",
    "identity_provider": "auth",
    "data_sources": "rag",
    "documents_per_day": "rag",
}

_NEGATIVE = re.compile(
    r"don'?t need|do not need|does not need|doesn't need|"
    r"not required|not needed|\bexcluded\b|\bexclude\b|no need|leave out",
    re.IGNORECASE,
)
_DIRECT: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bno cache\b", re.IGNORECASE), "cache"),
    (re.compile(r"\bno rbac\b", re.IGNORECASE), "auth"),
    (re.compile(r"\bno (?:cloud|deployment)\b", re.IGNORECASE), "infra"),
)
_FEATURE_NEEDLES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("cloud deployment", "cloud deploy"), "infra"),
    (("rbac", "role-based access", "role based access"), "auth"),
    (("observability",), "observe"),
    (("evaluation",), "eval"),
    (("guardrail",), "guard"),
    (("retrieval",), "rag"),
    (("workflow",), "workflow"),
    (("resilience",), "resilience"),
    (("cache",), "cache"),
    (("deployment", "infrastructure", "hosting"), "infra"),
    (("authorization",), "auth"),
)
_NO_USER = re.compile(
    r"\bno user|\bwithout users\b|\bno interaction\b|\bnot interactive\b|\bheadless\b|"
    r"don'?t interact|does not interact",
    re.IGNORECASE,
)
_BATCH = ("pandas", "dataframe", "batch calculation", "spreadsheet")
_SYSTEM_USERS = {"scheduler", "system", "batch", "pipeline"}


def normalize_excluded(value: Any) -> list[str] | None:
    """Map interview labels to component ids. None means the question was not answered."""
    if value is None:
        return None
    items = value if isinstance(value, list) else [value]
    found: list[str] = []
    for item in items:
        key = str(item).strip().lower()
        if not key or key == "none":
            continue
        component = OPTIONAL_COMPONENT_ALIASES.get(key)
        if component is None:
            raise ValueError(
                f"unknown optional part '{item}'. Choose from: cache, RBAC, cloud deployment, "
                "retrieval, observability, evaluation, workflows, guardrails, resilience."
            )
        if component not in found:
            found.append(component)
    return found


def exclusion_targets(text: str) -> list[str]:
    """Components named in a sentence such as 'cache excluded' or 'I don't need RBAC'."""
    if not text or not str(text).strip():
        return []
    lowered = str(text)
    found: list[str] = []
    for pattern, component in _DIRECT:
        if pattern.search(lowered) and component not in found:
            found.append(component)
    if _NEGATIVE.search(lowered) is None:
        return found
    haystack = lowered.lower()
    if re.search(r"\brag\b", haystack) and "rag" not in found:
        found.append("rag")
    for needles, component in _FEATURE_NEEDLES:
        if component in found:
            continue
        if any(needle in haystack for needle in needles):
            found.append(component)
    return found


def workload_exclusions(data: dict[str, Any]) -> list[str]:
    """Optional parts a batch or non-interactive workload does not need."""
    text = " ".join(
        str(part)
        for part in (
            data.get("idea"),
            data.get("business_outcome"),
            data.get("notes"),
            " ".join(str(item) for item in data.get("archetypes") or []),
        )
        if part
    )
    excluded: list[str] = []
    if any(word in text.lower() for word in _BATCH):
        excluded.append("cache")
    if not _interactive(data, text) and "auth" not in excluded:
        excluded.append("cache")
        excluded.append("auth")
    return list(dict.fromkeys(excluded))


def suggested_exclusions(data: dict[str, Any]) -> list[str]:
    """Best exclusions to offer when the optional-parts question is left empty."""
    found = exclusion_targets(f"{data.get('idea') or ''} {data.get('business_outcome') or ''}")
    for name in workload_exclusions(data):
        if name not in found:
            found.append(name)
    return found


def effective_exclusions(data: dict[str, Any]) -> list[str]:
    """Exclusions that apply to a saved requirements dict."""
    text = f"{data.get('idea') or ''} {data.get('business_outcome') or ''}"
    found = exclusion_targets(text)
    explicit = data.get("excluded_components")
    if explicit is None:
        for name in workload_exclusions(data):
            if name not in found:
                found.append(name)
    else:
        for name in explicit:
            if name not in found:
                found.append(name)
    return found


def _interactive(data: dict[str, Any], text: str) -> bool:
    if _NO_USER.search(text):
        return False
    users = [str(item).strip().lower() for item in data.get("users") or [] if str(item).strip()]
    if users and not all(user in _SYSTEM_USERS for user in users):
        return True
    if data.get("client_channels"):
        return True
    return any(word in text.lower() for word in ("chat", "copilot", "customer", "slack", "teams"))
