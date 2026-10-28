from __future__ import annotations

from archai.application.registry import DESIGN_COMPONENTS
from archai.domain.geography import within_residency
from archai.schemas.models import (
    ArchitectureGraph,
    ComponentStatus,
    EnterpriseDesign,
    ValidationDiagnostic,
)

REQUIRED_CLAIMS = {"iss", "aud", "exp"}
CACHE_BINDING = {"tenant", "principal_scope"}


def _diag(
    code: str, severity: str, message: str, component: str | None = None
) -> ValidationDiagnostic:
    return ValidationDiagnostic(
        code=code,
        severity=severity,
        message=message,
        component=component,
    )


def validate_design(
    design: EnterpriseDesign, graph: ArchitectureGraph, scope: list[str], strict: bool = False
) -> list[ValidationDiagnostic]:
    diagnostics: list[ValidationDiagnostic] = []
    req = design.requirements
    if req.conflicts:
        diagnostics.append(_diag("REQ_CONFLICT", "error", "Requirements contain conflicts"))
    if not graph.nodes:
        diagnostics.append(_diag("GRAPH_EMPTY", "error", "Graph has no nodes"))
    if (
        design.budget_policy
        and design.budget_policy.hard_limit
        and design.budget_policy.unavailable_behavior != "reject"
    ):
        diagnostics.append(
            _diag(
                "BUDGET_FAIL_OPEN",
                "error",
                "Hard budgets must reject when the budget authority is unavailable",
                "budget",
            )
        )
    selected = set(scope)
    service_ids = {service.id for service in design.services}
    store_ids = {store.id for store in design.data_stores}
    if "system" in selected:
        if len(service_ids) != len(design.services):
            diagnostics.append(
                _diag("DUPLICATE_ID", "error", "Service IDs must be unique", "system")
            )
        for service in design.services:
            unknown = set(service.depends_on) - service_ids - store_ids
            if unknown:
                diagnostics.append(
                    _diag(
                        "DANGLING_REFERENCE",
                        "error",
                        f"{service.id} depends on unknown IDs {sorted(unknown)}",
                        "system",
                    )
                )
        for kind in ("gateway", "ai-gateway", "policy"):
            if design.services and not any(service.kind == kind for service in design.services):
                diagnostics.append(
                    _diag(
                        "MISSING_CONTROL_OWNER",
                        "warning",
                        f"No {kind} service owns its controls",
                        "system",
                    )
                )
    if "api" in selected and design.services:
        for contract in design.api_contracts:
            if contract.service_id and contract.service_id not in service_ids:
                diagnostics.append(
                    _diag(
                        "DANGLING_REFERENCE",
                        "warning",
                        f"API {contract.id} references unknown service {contract.service_id}",
                        "api",
                    )
                )
    if "data" in selected:
        allowed = {req.region, *req.data_residency}
        for store in design.data_stores:
            if store.region not in allowed:
                diagnostics.append(
                    _diag(
                        "RESIDENCY_VIOLATION",
                        "error",
                        f"{store.id} is in {store.region}, outside {sorted(allowed)}",
                        "data",
                    )
                )
    if "routing" in selected:
        for endpoint in design.endpoints:
            if not within_residency(endpoint.region, [req.region, *req.data_residency]):
                diagnostics.append(
                    _diag(
                        "RESIDENCY_VIOLATION",
                        "error",
                        f"{endpoint.id} processes data in {endpoint.region}, outside residency",
                        "routing",
                    )
                )
        for alias in design.model_aliases:
            if "embeddings" in alias.required_capabilities and alias.fallback_endpoint_ids:
                diagnostics.append(
                    _diag(
                        "EMBEDDING_FALLBACK",
                        "error",
                        f"{alias.id} would mix vector spaces through fallback",
                        "routing",
                    )
                )
    if "cache" in selected and design.cache_policy and design.cache_policy.semantic_enabled:
        missing = CACHE_BINDING - set(design.cache_policy.namespace_fields)
        if missing:
            diagnostics.append(
                _diag(
                    "CACHE_UNBOUND",
                    "error",
                    f"Semantic cache namespace lacks {sorted(missing)}",
                    "cache",
                )
            )
    if "auth" in selected and design.identity_policy:
        missing_claims = REQUIRED_CLAIMS - set(design.identity_policy.required_claims)
        if missing_claims:
            diagnostics.append(
                _diag(
                    "TOKEN_VALIDATION",
                    "error",
                    f"Token validation must check {sorted(missing_claims)}",
                    "auth",
                )
            )
    if (
        "workflow" in selected
        and req.tool_side_effects == "approval"
        and design.workflows
        and any("tool" in workflow.name.lower() for workflow in design.workflows)
        and not any(workflow.hitl_required for workflow in design.workflows)
    ):
        diagnostics.append(
            _diag(
                "HITL_MISSING",
                "error",
                "Tool side effects require approval but no workflow has a human gate",
                "workflow",
            )
        )
    for name in scope:
        state = design.components.get(name)
        if state is None or state.status not in {
            ComponentStatus.valid,
            ComponentStatus.not_applicable,
        }:
            diagnostics.append(
                _diag("SCOPE_INCOMPLETE", "error", f"Component {name} is not valid", name)
            )
    if strict:
        for name in DESIGN_COMPONENTS:
            state = design.components.get(name)
            if state is None or state.status not in {
                ComponentStatus.valid,
                ComponentStatus.not_applicable,
            }:
                diagnostics.append(
                    _diag(
                        "PROJECT_INCOMPLETE",
                        "error",
                        f"Strict validation requires current component {name}",
                        name,
                    )
                )
    return diagnostics
