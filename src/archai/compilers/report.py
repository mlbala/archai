from __future__ import annotations

from archai.application.registry import COMPONENTS
from archai.schemas.models import ArchitectureGraph, EnterpriseDesign, ValidationDiagnostic


def component_document(
    component: str,
    design: EnterpriseDesign,
    graph: ArchitectureGraph,
    diagnostics: list[ValidationDiagnostic],
) -> str:
    title = COMPONENTS[component].title
    state = design.components.get(component)
    lines = [
        f"# {title} Design",
        "",
        f"**Project:** `{design.project}`  ",
        f"**Scope:** `{component}` only  ",
        f"**Component status:** `{state.status if state else 'missing'}`  ",
        f"**Project complete:** `{'yes' if project_complete(design) else 'no'}`",
        "",
        "> This is a reviewed design artifact. It does not deploy or prove availability of any cloud service.",
        "",
        "## Requirements and decisions",
        "",
        f"- Business outcome: {design.requirements.business_outcome}",
        f"- Region: {design.requirements.region}",
        f"- Data residency: {', '.join(design.requirements.data_residency)}",
        f"- Profile: {design.requirements.profile}",
        f"- Topology: {design.requirements.topology}",
        "",
        "## Design",
        "",
    ]
    lines.extend(_component_details(component, design))
    lines.extend(["", "## Interfaces and dependencies", ""])
    lines.append(
        "All cross-component references use IDs from `enterprise_design.json` and `architecture_graph.json`."
    )
    lines.extend(["", "## Assumptions and limitations", ""])
    lines.append(
        "- Managed model deployment identifiers, quotas, prices, and application image are account inputs."
    )
    lines.append("- Cost output is a scenario estimate, not a live quotation or latency guarantee.")
    lines.extend(["", "## Validation findings", ""])
    relevant = [item for item in diagnostics if item.component in {None, component}]
    if relevant:
        lines.extend(f"- **{item.severity}:** `{item.code}` — {item.message}" for item in relevant)
    else:
        lines.append("- No blocking diagnostics in this scope.")
    return "\n".join(lines) + "\n"


def requirements_document(design: EnterpriseDesign) -> str:
    req = design.requirements
    return f"""# AI Enterprise Product Requirements

**Project:** `{design.project}`

## Outcome

{req.business_outcome}

## Users and workload

- Users: {", ".join(req.users)}
- Archetypes: {", ".join(req.archetypes)}
- Average / peak RPS: {req.avg_rps} / {req.peak_rps}
- Model calls per request: {req.model_calls_per_request}
- Average input / output tokens: {req.input_tokens} / {req.output_tokens}

## Hard boundaries

- Data residency: {", ".join(req.data_residency)}
- Tenant isolation: {req.tenant_isolation}
- Tool side effects: {req.tool_side_effects}
- Monthly budget: {req.monthly_budget} {req.currency}
- Availability target: {req.availability_target}%
- Managed inference only; local inference and fine-tuning are outside v2.
"""


def complete_document(
    design: EnterpriseDesign, graph: ArchitectureGraph, diagnostics: list[ValidationDiagnostic]
) -> str:
    sections = [
        "# Complete AI System Design",
        "",
        f"**Project:** `{design.project}`  ",
        f"**Completeness:** `{'complete' if project_complete(design) else 'partial'}`  ",
        "**Deployment status:** `design assets only; not deployed`",
        "",
        requirements_document(design),
    ]
    for component in COMPONENTS:
        if component in {"requirements", "doc"}:
            continue
        if component in design.components:
            sections.extend(["", component_document(component, design, graph, diagnostics)])
    return "\n".join(sections)


def project_complete(design: EnterpriseDesign) -> bool:
    required = set(COMPONENTS) - {"diagram", "doc"}
    return required <= {
        name
        for name, state in design.components.items()
        if state.status.value in {"valid", "not_applicable"}
    }


def _component_details(component: str, design: EnterpriseDesign) -> list[str]:
    if component == "system":
        return [f"- `{item.id}` — {item.name} ({item.kind})" for item in design.services]
    if component == "api":
        return [
            f"- `{item.method} {item.path}` — {item.auth}; streaming={item.streaming}"
            for item in design.api_contracts
        ]
    if component == "routing":
        return [
            f"- `{item.id}` — {item.provider}, {item.region}, deployment `{item.deployment_id}`"
            for item in design.endpoints
        ]
    if component == "budget" and design.budget_policy:
        return [
            f"- Hard monthly limit: {design.budget_policy.monthly_limit} {design.budget_policy.currency}",
            "- Durable reservation states: requested, reserved, dispatched, settled/unresolved/reconciled",
            "- Budget authority outage behavior: reject",
        ]
    if component == "cache" and design.cache_policy:
        return [
            f"- Exact cache: {design.cache_policy.exact_enabled}",
            f"- Semantic cache: {design.cache_policy.semantic_enabled}",
            f"- Namespace: {', '.join(design.cache_policy.namespace_fields)}",
        ]
    if component == "workflow":
        return [
            f"- `{item.name}`: {' → '.join(item.steps)}; HITL={item.hitl_required}"
            for item in design.workflows
        ]
    if component in {"rag", "data"}:
        return [
            f"- `{item.id}` — {item.kind}: {item.purpose}; partition `{item.partition_key}`"
            for item in design.data_stores
        ]
    if component == "infra" and design.deployment:
        return [
            f"- Profile: {design.deployment.name} in {design.deployment.region}",
            f"- Resources: {', '.join(design.deployment.resources)}",
            "- A user-supplied application image is required before deployment.",
        ]
    if component == "resilience" and design.queue_policy:
        return [
            f"- Broker: {design.queue_policy.broker}",
            f"- Delivery: {design.queue_policy.delivery}; maximum attempts: {design.queue_policy.max_attempts}",
            "- Provider fallback does not constitute application disaster recovery.",
        ]
    if component == "auth" and design.identity_policy:
        return [
            f"- IdP: {design.identity_policy.idp}",
            f"- Claims: {', '.join(design.identity_policy.required_claims)}",
            "- Object-level authorization is required for retrieval, cache, jobs, audit, and tools.",
        ]
    if component == "guard":
        return [
            f"- `{item.id}` — {item.stage}: {item.control} ({item.enforcement})"
            for item in design.guardrails
        ]
    if component == "security":
        return [f"- `{item.id}` — {item.title}; {item.mitigation}" for item in design.risks]
    if component == "observe" and design.observability:
        return [
            f"- Tracing: {design.observability.tracing}",
            f"- Model analytics: {design.observability.model_analytics} (not the budget ledger)",
            f"- Correlation IDs: {', '.join(design.observability.correlation_ids)}",
        ]
    if component == "eval":
        return [
            "- Evaluate quality, safety, latency, cost, and policy adherence for every primary and fallback route."
        ]
    if component == "cost" and design.capacity:
        return [
            f"- Peak calls/minute: {design.capacity.calls_per_minute}",
            f"- Input/output tokens/minute: {design.capacity.input_tokens_per_minute}/{design.capacity.output_tokens_per_minute}",
            f"- Starting worker count: {design.capacity.worker_count} (load testing required)",
        ]
    if component == "diagram":
        return [
            f"- Canonical graph contains {len(design.services)} services and {len(design.endpoints)} managed endpoints."
        ]
    return ["- The selected scope is represented in canonical state."]
