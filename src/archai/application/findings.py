"""Decide which components a verifier finding asks to change.

A finding names one component for display, but its fix often spans several: a service
dependency, an identity grant, and a decision record can all be part of one defect. The
verifier lists the design fields the fix must change. Each field maps to the component that
owns it, so the repair goes to every role that can make part of the change.

Some fields hold values ArchAI sets from the requirements (see ``designer.fixed_facts``). No
role can change them, so a finding that only disputes those values is not sent for repair.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from archai.application.designer import FIXED_SOURCE
from archai.schemas.models import ArchitectureDecision, EnterpriseDesign

# First path segment -> owning component. Component names are accepted as well, so a
# verifier that writes "auth" instead of "identity_policy" still routes correctly.
FIELD_COMPONENTS: dict[str, str] = {
    "prd": "requirements",
    "requirements": "requirements",
    "services": "system",
    "system": "system",
    "data_stores": "data",
    "data": "data",
    "workflows": "workflow",
    "workflow": "workflow",
    "rag_pipeline": "rag",
    "rag": "rag",
    "deployment": "infra",
    "infra": "infra",
    "resilience": "resilience",
    "queue_policy": "resilience",
    "api_contracts": "api",
    "api": "api",
    "routing_policy": "routing",
    "model_aliases": "routing",
    "routing": "routing",
    "budget_policy": "budget",
    "budget": "budget",
    "cache_policy": "cache",
    "cache": "cache",
    "identity_policy": "auth",
    "identity": "auth",
    "auth": "auth",
    "guardrails": "guard",
    "guard": "guard",
    "threats": "security",
    "security": "security",
    "observability": "observe",
    "observe": "observe",
    "eval_plan": "eval",
    "evaluation": "eval",
    "eval": "eval",
}

# Field paths (ids removed) whose values Python sets from the requirements after every merge.
FIXED_FIELDS = (
    "budget_policy.monthly_limit",
    "budget_policy.currency",
    "budget_policy.hard_limit",
    "budget_policy.unavailable_behavior",
    "budget_policy.enforcement_scope",
    "routing_policy.max_attempts",
    "endpoints",
    "capacity",
    "costs",
    "resilience.rto_minutes",
    "resilience.rpo_minutes",
    "resilience.dr_strategy",
    "identity_policy.tenant_mode",
    "identity_policy.required_claims",
    "identity_policy.object_level_authorization",
    "observability.correlation_ids",
    "observability.redaction_required",
    "cache_policy.namespace_fields",
)

_SPLIT = re.compile(r"[.\[\]'\"]+")
_ATTRIBUTE = re.compile(r"[a-z_][a-z0-9_]*")
_DECISION_ID = re.compile(r"\badr-[a-z0-9][a-z0-9-]*", re.IGNORECASE)


@dataclass(frozen=True)
class FindingTarget:
    """Components a finding asks to change, and whether it only disputes fixed values."""

    components: list[str]
    fixed_only: bool


def _segments(path: str) -> list[str]:
    return [part for part in _SPLIT.split(path.strip()) if part]


def _decision(
    identifier: str, decisions: dict[str, ArchitectureDecision]
) -> ArchitectureDecision | None:
    """Find a decision by id; models sometimes shorten or lengthen a long slug."""
    key = identifier.lower().rstrip("-.,;")
    if key in decisions:
        return decisions[key]
    matches = [
        item for name, item in decisions.items() if name.startswith(key) or key.startswith(name)
    ]
    return matches[0] if len(matches) == 1 else None


def _is_fixed(segments: list[str], decisions: dict[str, ArchitectureDecision]) -> bool:
    head = segments[0].lower()
    if head == "requirements" and len(segments) > 1:
        return True  # the confirmed inputs themselves
    if head == "decisions":
        item = _decision(segments[1], decisions) if len(segments) > 1 else None
        return item is not None and item.source == FIXED_SOURCE
    path = ".".join(part.lower() for part in segments if _ATTRIBUTE.fullmatch(part.lower()))
    return any(path == item or path.startswith(item + ".") for item in FIXED_FIELDS)


def _owner(segments: list[str], decisions: dict[str, ArchitectureDecision]) -> str | None:
    head = segments[0].lower()
    if head == "decisions":
        item = _decision(segments[1], decisions) if len(segments) > 1 else None
        return item.component if item is not None else None
    return FIELD_COMPONENTS.get(head)


def finding_target(
    design: EnterpriseDesign, component: str, fields: list[str], text: str
) -> FindingTarget:
    """Resolve the components to change from the named fields and the decision ids cited.

    The finding's own component is used only when no named field maps to a component.
    """
    decisions = {item.id.lower(): item for item in design.decisions}
    found: list[str] = []
    named = 0
    fixed = 0

    def add(name: str | None) -> None:
        if name and name not in found:
            found.append(name)

    for path in fields:
        segments = _segments(path)
        if not segments:
            continue
        owner = _owner(segments, decisions)
        if owner is None and segments[0].lower() not in {"endpoints", "decisions"}:
            continue
        named += 1
        if _is_fixed(segments, decisions):
            fixed += 1
            continue
        add(owner)
    for identifier in _DECISION_ID.findall(text):
        item = _decision(identifier, decisions)
        if item is not None and item.source != FIXED_SOURCE:
            add(item.component)
    if not found and not (named and fixed == named):
        add(component)
    return FindingTarget(components=found, fixed_only=bool(named) and fixed == named and not found)
