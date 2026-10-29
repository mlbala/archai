"""Master design: features, delivery plan, and sprints compiled from canonical state."""

from __future__ import annotations

from dataclasses import dataclass

from archai.application.registry import COMPONENTS
from archai.compilers.report import DISCLAIMER, bullets, project_complete, source_label, table
from archai.domain.scale import scale_targets
from archai.schemas.models import (
    ComponentStatus,
    EnterpriseDesign,
    Service,
    ValidationDiagnostic,
)

_SPRINTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "Sprint 1 — Foundation",
        "Sign-in, tenant-scoped data, and the hosting baseline.",
        ("auth", "data", "infra"),
    ),
    (
        "Sprint 2 — Core path",
        "A user request completes through the gateway, the model route, and the primary workflow.",
        ("system", "api", "routing", "rag", "workflow"),
    ),
    (
        "Sprint 3 — Controls",
        "Budget, cache, guardrails, and the threat model are in place before broader rollout.",
        ("budget", "cache", "guard", "security"),
    ),
    (
        "Sprint 4 — Operate",
        "Telemetry, evaluation, recovery, and the scale-up contract are in place.",
        ("observe", "eval", "resilience", "cost"),
    ),
)
_FEATURE_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("budget", "token", "spend", "cost"), ("budget", "cost", "routing"), "Sprint 3 — Controls"),
    (("retriev", "document", "citation", "ground", "rag"), ("rag", "data"), "Sprint 2 — Core path"),
    (("identity", "oauth", "sign-in", "role", "tenant"), ("auth",), "Sprint 1 — Foundation"),
    (("guard", "inject", "safety"), ("guard", "security"), "Sprint 3 — Controls"),
    (("observ", "metric", "trace", "alert"), ("observe",), "Sprint 4 — Operate"),
    (("eval", "quality"), ("eval",), "Sprint 4 — Operate"),
    (("recover", "failover", "resilien"), ("resilience", "infra"), "Sprint 4 — Operate"),
    (("cache",), ("cache",), "Sprint 3 — Controls"),
    (("workflow", "approval", "tool"), ("workflow",), "Sprint 2 — Core path"),
    (("api", "chat", "endpoint"), ("api", "system"), "Sprint 2 — Core path"),
    (("infra", "deploy", "region", "kubernetes"), ("infra",), "Sprint 1 — Foundation"),
)


@dataclass(frozen=True)
class _Feature:
    id: str
    statement: str
    priority: str
    components: tuple[str, ...]
    sprint: str


def master_design_document(
    design: EnterpriseDesign, diagnostics: list[ValidationDiagnostic]
) -> str:
    """One delivery document: features, build order, and sprint slices. No calendar dates."""
    features = _features(design)
    lines = [
        "# Master Design",
        "",
        *table(
            ["Field", "Value"],
            [
                ["Project", f"`{design.project}`"],
                ["Completeness", "complete" if project_complete(design) else "partial"],
                [
                    "Hosting",
                    f"{design.requirements.profile} in {design.requirements.region} "
                    f"({design.requirements.topology})",
                ],
                ["Deployment status", "design assets only; not deployed"],
                ["Designed by", _sources(design)],
            ],
        ),
        "",
        DISCLAIMER,
        "",
        "This document is the delivery view of this revision: features, build order, and "
        "sprint slices. The high-level design is the architecture picture. The low-level "
        "design walks each hop. `Complete_AI_System_Design` is the component archive. A "
        "sprint is a build slice, not a calendar commitment. Dates and team size stay with "
        "the people running the project.",
        "",
        "## 1. Feature catalog",
        "",
        _feature_intro(design),
        "",
    ]
    lines += table(
        ["ID", "Feature", "Priority", "Components", "Sprint"],
        [
            [
                item.id,
                item.statement,
                item.priority,
                ", ".join(COMPONENTS[name].title for name in item.components),
                item.sprint,
            ]
            for item in features
        ],
    )
    lines += ["", "## 2. Development plan", ""]
    lines.append(
        "Build in dependency order. Later slices consume the services and stores from "
        "earlier waves. Provider quotas, deployment IDs, and prices remain account inputs."
    )
    lines += ["", "### Service build order", ""]
    lines += table(
        ["Wave", "Services", "Unblocks"],
        [
            [str(index), ", ".join(names), _wave_unblocks(design, names)]
            for index, names in enumerate(_waves(design.services), start=1)
        ],
    )
    lines += ["", "### Plan by component", ""]
    lines += table(
        ["Order", "Work", "Components", "Done when"],
        [
            [str(index), goal, _component_titles(design, names), _done_when(design, names)]
            for index, (_title, goal, names) in enumerate(_active_sprints(design), start=1)
        ],
    )
    lines += ["", "## 3. Sprints", ""]
    for sprint_name, goal, names in _active_sprints(design):
        included = _present_names(design, names)
        owned = [item for item in features if item.sprint == sprint_name]
        lines += [f"### {sprint_name}", "", goal, ""]
        if owned:
            lines.append("Features:")
            lines += bullets(f"`{item.id}` {item.statement}" for item in owned)
            lines.append("")
        lines.append(f"Components: {_component_titles(design, included)}.")
        lines += ["", "Done when:", ""]
        lines += bullets(_done_items(design, included))
        lines.append("")
    lines += ["## 4. Decisions carried into the plan", ""]
    if design.decisions:
        lines += table(
            ["ID", "Component", "Decision", "Rationale"],
            [
                [
                    item.id,
                    COMPONENTS[item.component].title
                    if item.component in COMPONENTS
                    else item.component,
                    item.title,
                    item.decision,
                ]
                for item in design.decisions
            ],
        )
    else:
        lines.append("_No architecture decisions recorded on this revision._")
    if design.requirements.assumptions:
        lines += ["", "Assumptions accepted with the requirements:", ""]
        lines += bullets(
            f"{item.statement} — {item.rationale}" for item in design.requirements.assumptions
        )
    lines += ["", "## 5. Readiness", ""]
    lines += bullets(_readiness(design, diagnostics))
    lines += [
        "",
        "Sprint 4 records the scale-up contract already written into the design. "
        "Replica ranges are load-test starting points, and ArchAI does not apply them.",
        "",
    ]
    targets = scale_targets(design)
    if targets:
        lines += table(
            ["Service", "Mode", "Replicas", "Trigger"],
            [[item.name, item.mode, item.replicas, item.trigger] for item in targets],
        )
    return "\n".join(lines).rstrip() + "\n"


def _sources(design: EnterpriseDesign) -> str:
    sources = sorted(
        {source_label(state.source) for state in design.components.values() if state.source}
    )
    return ", ".join(sources) or "deterministic baseline"


def _feature_intro(design: EnterpriseDesign) -> str:
    if design.prd and design.prd.functional_requirements:
        return (
            "Features are the functional requirements on this revision. Each one is placed in "
            "the sprint of the components that implement it."
        )
    return (
        "This revision has no separate functional-requirement list, so each feature is a "
        "delivery slice of the business outcome, the workflows, and the controls in the design."
    )


def _features(design: EnterpriseDesign) -> list[_Feature]:
    if design.prd and design.prd.functional_requirements:
        features: list[_Feature] = []
        for index, item in enumerate(design.prd.functional_requirements, start=1):
            components, sprint = _map_statement(design, item.statement)
            features.append(
                _Feature(
                    item.id or f"F-{index:02d}",
                    item.statement,
                    item.priority,
                    components,
                    sprint,
                )
            )
        return features
    return _synthesized_features(design)


def _synthesized_features(design: EnterpriseDesign) -> list[_Feature]:
    req = design.requirements
    drafts: list[tuple[str, str, tuple[str, ...], str]] = []
    if req.business_outcome:
        drafts.append((req.business_outcome, "must", ("system", "api"), "Sprint 2 — Core path"))
    if design.identity_policy:
        drafts.append(
            (
                f"Sign users in with {design.identity_policy.idp} and enforce application roles.",
                "must",
                ("auth",),
                "Sprint 1 — Foundation",
            )
        )
    if design.data_stores:
        drafts.append(
            (
                f"Store tenant-scoped state in {len(design.data_stores)} named data stores.",
                "must",
                ("data",),
                "Sprint 1 — Foundation",
            )
        )
    if design.deployment:
        drafts.append(
            (
                f"Host the application on {design.deployment.name} in {design.deployment.region}.",
                "must",
                ("infra",),
                "Sprint 1 — Foundation",
            )
        )
    for workflow in design.workflows:
        drafts.append(
            (
                workflow.description or workflow.name,
                "must",
                ("workflow", "system"),
                "Sprint 2 — Core path",
            )
        )
    if design.rag_pipeline:
        drafts.append(
            (
                "Answer from permitted sources and return citations for the index version.",
                "must",
                ("rag", "data"),
                "Sprint 2 — Core path",
            )
        )
    if design.budget_policy:
        drafts.append(
            (
                f"Reject new chargeable work past {design.budget_policy.monthly_limit} "
                f"{design.budget_policy.currency} in a month.",
                "must",
                ("budget", "routing"),
                "Sprint 3 — Controls",
            )
        )
    if design.guardrails:
        drafts.append(
            (
                "Apply the guardrail controls on the request path before a tool or model call.",
                "must",
                ("guard", "security"),
                "Sprint 3 — Controls",
            )
        )
    if design.observability:
        drafts.append(
            (
                "Trace each request across the gateway, admission, and model call.",
                "should",
                ("observe",),
                "Sprint 4 — Operate",
            )
        )
    if design.eval_plan:
        drafts.append(
            (
                "Evaluate every primary route before fallback traffic is enabled.",
                "should",
                ("eval",),
                "Sprint 4 — Operate",
            )
        )
    features: list[_Feature] = []
    for index, (statement, priority, components, sprint) in enumerate(drafts, start=1):
        present = _present_names(design, components)
        if not present:
            continue
        features.append(_Feature(f"F-{index:02d}", statement, priority, present, sprint))
    return features


def _map_statement(design: EnterpriseDesign, statement: str) -> tuple[tuple[str, ...], str]:
    text = statement.lower()
    for needles, components, sprint in _FEATURE_RULES:
        if any(needle in text for needle in needles):
            present = _present_names(design, components)
            if present:
                return present, sprint
    present = _present_names(design, ("system",))
    return present or ("system",), "Sprint 2 — Core path"


def _present_names(design: EnterpriseDesign, names: tuple[str, ...]) -> tuple[str, ...]:
    present: list[str] = []
    for name in names:
        state = design.components.get(name)
        if state is not None and state.status != ComponentStatus.not_applicable:
            present.append(name)
    return tuple(present)


def _active_sprints(design: EnterpriseDesign) -> list[tuple[str, str, tuple[str, ...]]]:
    active: list[tuple[str, str, tuple[str, ...]]] = []
    for title, goal, names in _SPRINTS:
        present = _present_names(design, names)
        if present:
            active.append((title, goal, present))
    return active


def _component_titles(design: EnterpriseDesign, names: tuple[str, ...]) -> str:
    del design
    return ", ".join(COMPONENTS[name].title for name in names if name in COMPONENTS)


def _done_when(design: EnterpriseDesign, names: tuple[str, ...]) -> str:
    items = _done_items(design, names)
    return " ".join(items)


def _done_items(design: EnterpriseDesign, names: tuple[str, ...]) -> list[str]:
    req = design.requirements
    items: list[str] = []
    selected = set(names)
    if "auth" in selected and design.identity_policy:
        grants = ", ".join(flow.grant_type for flow in design.identity_policy.oauth_flows)
        items.append(f"Sign-in with {design.identity_policy.idp} ({grants}) is specified.")
    if "data" in selected and design.data_stores:
        items.append(f"{len(design.data_stores)} data stores name a region, owner, and retention.")
    if "infra" in selected and design.deployment:
        items.append(
            f"The {design.deployment.name} profile in {design.deployment.region} is the "
            "hosting baseline. Generated Terraform is still not applied."
        )
    if "system" in selected and design.services:
        items.append(f"{len(design.services)} services have owners and dependencies.")
    if "api" in selected and design.api_contracts:
        items.append(f"{len(design.api_contracts)} API operations define auth and scopes.")
    if "routing" in selected and design.model_aliases:
        items.append(f"{len(design.model_aliases)} model aliases route only to eligible endpoints.")
    if "rag" in selected and design.rag_pipeline:
        items.append(
            f"Retrieval is {design.rag_pipeline.retrieval_mode}, top-{design.rag_pipeline.top_k}, "
            "with ACL filtering."
        )
    if "workflow" in selected and design.workflows:
        items.append(f"{len(design.workflows)} workflows name their steps and trigger.")
    if "budget" in selected and design.budget_policy:
        items.append(
            f"The hard monthly limit is {design.budget_policy.monthly_limit} "
            f"{design.budget_policy.currency}, enforced by reservation and settlement."
        )
    if "cache" in selected and design.cache_policy:
        items.append("Cache namespaces are bound to tenant and permission scope.")
    if "guard" in selected and design.guardrails:
        items.append(f"{len(design.guardrails)} guardrail controls name an owner and a stage.")
    if "security" in selected and design.threats:
        items.append(f"{len(design.threats)} threats are mapped for review.")
    if "observe" in selected and design.observability:
        items.append("The telemetry path correlates gateway, admission, and model calls.")
    if "eval" in selected and design.eval_plan:
        items.append("Primary routes have an evaluation step before fallback is enabled.")
    if "resilience" in selected and design.resilience:
        items.append(
            f"Recovery targets are RTO {req.rto_minutes or '—'} minutes and "
            f"RPO {req.rpo_minutes or '—'} minutes."
        )
    if "cost" in selected and design.capacity:
        items.append(
            "Capacity is calculated from the supplied traffic, and missing prices stay unknown."
        )
    return items or ["The components in this slice are present on the revision."]


def _waves(services: list[Service]) -> list[list[str]]:
    ids = {service.id for service in services}
    names = {service.id: service.name for service in services}
    remaining = {service.id: set(service.depends_on) & ids for service in services}
    waves: list[list[str]] = []
    while remaining:
        ready = sorted(service_id for service_id, deps in remaining.items() if not deps)
        if not ready:
            ready = sorted(remaining)
        waves.append([names[service_id] for service_id in ready])
        for service_id in ready:
            remaining.pop(service_id, None)
        for deps in remaining.values():
            deps.difference_update(ready)
    return waves


def _wave_unblocks(design: EnterpriseDesign, names: list[str]) -> str:
    by_name = {service.name: service for service in design.services}
    dependency_ids = {item.id for name in names if (item := by_name.get(name)) is not None}
    blocked = [
        service.name
        for service in design.services
        if service.name not in names and set(service.depends_on) & dependency_ids
    ]
    return ", ".join(blocked) if blocked else "—"


def _readiness(design: EnterpriseDesign, diagnostics: list[ValidationDiagnostic]) -> list[str]:
    items = [
        "The revision is complete."
        if project_complete(design)
        else "The revision is partial; finish the missing components before Sprint 1 is called done."
    ]
    blocking = [
        item for item in design.verification if item.severity == "blocking" and not item.resolved
    ]
    if blocking:
        items.append(f"{len(blocking)} blocking verifier findings are still open.")
    else:
        items.append("No unresolved blocking verifier findings are on this revision.")
    errors = [item for item in diagnostics if item.severity == "error"]
    if errors:
        items.append(f"{len(errors)} validation errors are open.")
    placeholders = [
        endpoint.id for endpoint in design.endpoints if "USER_SUPPLIED" in endpoint.deployment_id
    ]
    if placeholders:
        items.append(
            f"{len(placeholders)} model deployment IDs are still USER_SUPPLIED account inputs."
        )
    missing = [item.contract for item in design.external_dependencies if item.status == "missing"]
    if missing:
        items.append("Missing external inputs: " + ", ".join(missing) + ".")
    if design.requirements.assumptions:
        items.append(
            f"{len(design.requirements.assumptions)} interview answers were chosen from the "
            "project requirements and are listed above."
        )
    items.append("Nothing in this plan is deployed.")
    return items
