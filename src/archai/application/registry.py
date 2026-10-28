from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    title: str
    role: str | None
    deterministic: bool
    outputs: tuple[str, ...]
    invalidates: tuple[str, ...] = ()


COMPONENTS: dict[str, ComponentSpec] = {
    "requirements": ComponentSpec(
        "requirements",
        "Requirements",
        "Enterprise Requirements Architect",
        False,
        ("AI_Enterprise_PRD.md",),
        (
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
        ("diagram", "doc"),
    ),
    "api": ComponentSpec(
        "api",
        "API",
        "API Management and AI Routing Architect",
        False,
        ("API_Design.md",),
        ("infra", "security", "diagram", "doc"),
    ),
    "routing": ComponentSpec(
        "routing",
        "Routing",
        "API Management and AI Routing Architect",
        False,
        ("Routing_Design.md",),
        ("budget", "cost", "diagram", "doc"),
    ),
    "budget": ComponentSpec(
        "budget",
        "Budget",
        "API Management and AI Routing Architect",
        False,
        ("Budget_Design.md",),
        ("cost", "doc"),
    ),
    "cache": ComponentSpec(
        "cache",
        "Cache",
        "API Management and AI Routing Architect",
        False,
        ("Cache_Design.md",),
        ("cost", "doc"),
    ),
    "workflow": ComponentSpec(
        "workflow",
        "Workflow",
        "Cloud, Data, and Resilience Architect",
        False,
        ("Workflow_Design.md",),
        ("security", "diagram", "doc"),
    ),
    "rag": ComponentSpec(
        "rag",
        "RAG",
        "Cloud, Data, and Resilience Architect",
        False,
        ("RAG_Design.md",),
        ("data", "security", "cost", "diagram", "doc"),
    ),
    "data": ComponentSpec(
        "data",
        "Data",
        "Cloud, Data, and Resilience Architect",
        False,
        ("Data_Design.md",),
        ("infra", "security", "diagram", "doc"),
    ),
    "infra": ComponentSpec(
        "infra",
        "Infrastructure",
        "Cloud, Data, and Resilience Architect",
        False,
        ("Infrastructure_Design.md",),
        ("resilience", "cost", "diagram", "doc"),
    ),
    "resilience": ComponentSpec(
        "resilience",
        "Resilience",
        "Cloud, Data, and Resilience Architect",
        False,
        ("Resilience_Design.md",),
        ("cost", "diagram", "doc"),
    ),
    "auth": ComponentSpec(
        "auth",
        "Identity and Authorization",
        "Identity, Security, and Observability Architect",
        False,
        ("Identity_Design.md",),
        ("guard", "security", "doc"),
    ),
    "guard": ComponentSpec(
        "guard",
        "Guardrails",
        "Identity, Security, and Observability Architect",
        False,
        ("Guardrails_Design.md",),
        ("security", "eval", "doc"),
    ),
    "security": ComponentSpec(
        "security",
        "Security",
        "Identity, Security, and Observability Architect",
        False,
        ("Security_Design.md",),
        ("doc",),
    ),
    "observe": ComponentSpec(
        "observe",
        "Observability",
        "Identity, Security, and Observability Architect",
        False,
        ("Observability_Design.md",),
        ("doc",),
    ),
    "eval": ComponentSpec(
        "eval",
        "Evaluation",
        "Identity, Security, and Observability Architect",
        False,
        ("Evaluation_Design.md",),
        ("doc",),
    ),
    "cost": ComponentSpec(
        "cost",
        "Capacity and Cost",
        None,
        True,
        ("Cost_Design.md", "capacity_and_cost.json"),
        ("doc",),
    ),
    "diagram": ComponentSpec("diagram", "Diagrams", None, True, ("Architecture_Diagrams.md",)),
    "doc": ComponentSpec("doc", "Documentation", None, True, ("Complete_AI_System_Design.md",)),
}

DESIGN_COMPONENTS = tuple(name for name in COMPONENTS if name not in {"diagram", "doc"})
AUTO_COMPONENTS = tuple(COMPONENTS)


def execution_plan(scope: list[str]) -> list[ComponentSpec]:
    unknown = set(scope) - set(COMPONENTS)
    if unknown:
        raise ValueError(f"unknown components: {', '.join(sorted(unknown))}")
    return [COMPONENTS[name] for name in COMPONENTS if name in scope]
