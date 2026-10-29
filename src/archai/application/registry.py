from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    title: str
    role: str | None
    deterministic: bool
    outputs: tuple[str, ...]
    invalidates: tuple[str, ...] = ()


def derived(*names: str) -> tuple[str, ...]:
    return names


COMPONENTS: dict[str, ComponentSpec] = {
    "requirements": ComponentSpec(
        "requirements",
        "Requirements",
        "Enterprise Requirements Architect",
        False,
        ("AI_Enterprise_PRD.md",),
        derived(
            "system",
            "api",
            "routing",
            "budget",
            "cache",
            "workflow",
            "rag",
            "data",
            "infra",
            "resilience",
            "auth",
            "guard",
            "security",
            "observe",
            "eval",
            "cost",
            "diagram",
            "doc",
        ),
    ),
    "system": ComponentSpec(
        "system",
        "System",
        "Cloud, Data, and Resilience Architect",
        False,
        ("System_Design.md",),
        derived("diagram", "doc"),
    ),
    "api": ComponentSpec(
        "api",
        "API",
        "API Management and AI Routing Architect",
        False,
        ("API_Design.md",),
        derived("infra", "security", "diagram", "doc"),
    ),
    "routing": ComponentSpec(
        "routing",
        "Routing",
        "API Management and AI Routing Architect",
        False,
        ("Routing_Design.md",),
        derived("budget", "cost", "diagram", "doc"),
    ),
    "budget": ComponentSpec(
        "budget",
        "Budget",
        "API Management and AI Routing Architect",
        False,
        ("Budget_Design.md",),
        derived("cost", "doc"),
    ),
    "cache": ComponentSpec(
        "cache",
        "Cache",
        "API Management and AI Routing Architect",
        False,
        ("Cache_Design.md",),
        derived("cost", "doc"),
    ),
    "workflow": ComponentSpec(
        "workflow",
        "Workflow",
        "Cloud, Data, and Resilience Architect",
        False,
        ("Workflow_Design.md",),
        derived("security", "diagram", "doc"),
    ),
    "rag": ComponentSpec(
        "rag",
        "RAG",
        "Cloud, Data, and Resilience Architect",
        False,
        ("RAG_Design.md",),
        derived("data", "security", "cost", "diagram", "doc"),
    ),
    "data": ComponentSpec(
        "data",
        "Data",
        "Cloud, Data, and Resilience Architect",
        False,
        ("Data_Design.md",),
        derived("infra", "security", "diagram", "doc"),
    ),
    "infra": ComponentSpec(
        "infra",
        "Infrastructure",
        "Cloud, Data, and Resilience Architect",
        False,
        ("Infrastructure_Design.md",),
        derived("resilience", "cost", "diagram", "doc"),
    ),
    "resilience": ComponentSpec(
        "resilience",
        "Resilience",
        "Cloud, Data, and Resilience Architect",
        False,
        ("Resilience_Design.md",),
        derived("cost", "diagram", "doc"),
    ),
    "auth": ComponentSpec(
        "auth",
        "Identity and Authorization",
        "Identity, Security, and Observability Architect",
        False,
        ("Identity_Design.md",),
        derived("guard", "security", "doc"),
    ),
    "guard": ComponentSpec(
        "guard",
        "Guardrails",
        "Identity, Security, and Observability Architect",
        False,
        ("Guardrails_Design.md",),
        derived("security", "eval", "doc"),
    ),
    "security": ComponentSpec(
        "security",
        "Security",
        "Identity, Security, and Observability Architect",
        False,
        ("Security_Design.md",),
        derived("doc"),
    ),
    "observe": ComponentSpec(
        "observe",
        "Observability",
        "Identity, Security, and Observability Architect",
        False,
        ("Observability_Design.md",),
        derived("doc"),
    ),
    "eval": ComponentSpec(
        "eval",
        "Evaluation",
        "Identity, Security, and Observability Architect",
        False,
        ("Evaluation_Design.md",),
        derived("doc"),
    ),
    "cost": ComponentSpec(
        "cost",
        "Capacity and Cost",
        None,
        True,
        ("Cost_Design.md", "capacity_and_cost.json"),
        derived("doc"),
    ),
    "diagram": ComponentSpec("diagram", "Diagrams", None, True, ("Architecture_Diagrams.md",)),
    "doc": ComponentSpec("doc", "Documentation", None, True, ("Master_Design.md",)),
}

DOCUMENT_PACKAGES: dict[str, ComponentSpec] = {
    "hld": ComponentSpec("hld", "High-Level Design", None, True, ("High_Level_Design.md",)),
    "lld": ComponentSpec("lld", "Low-Level Design", None, True, ("Low_Level_Design.md",)),
}

COMPILED_COMPONENTS = frozenset({"diagram", "doc"})
DESIGN_COMPONENTS = tuple(name for name in COMPONENTS if name not in COMPILED_COMPONENTS)
AUTO_COMPONENTS = tuple(COMPONENTS)


def review_scope(components: Iterable[str]) -> list[str]:
    return list(dict.fromkeys([*components, "doc", *DOCUMENT_PACKAGES]))


def execution_plan(scope: list[str]) -> list[ComponentSpec]:
    unknown = set(scope) - set(COMPONENTS) - set(DOCUMENT_PACKAGES)
    if unknown:
        raise ValueError(f"unknown components: {', '.join(sorted(unknown))}")
    return [COMPONENTS[name] for name in COMPONENTS if name in scope]
