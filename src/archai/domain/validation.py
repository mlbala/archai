from __future__ import annotations

from archai.application.registry import DESIGN_COMPONENTS
from archai.schemas.models import (
    ArchitectureGraph,
    ComponentStatus,
    EnterpriseDesign,
    ValidationDiagnostic,
)


def validate_design(
    design: EnterpriseDesign, graph: ArchitectureGraph, scope: list[str], strict: bool = False
) -> list[ValidationDiagnostic]:
    diagnostics: list[ValidationDiagnostic] = []
    if design.requirements.conflicts:
        diagnostics.append(
            ValidationDiagnostic(
                code="REQ_CONFLICT", severity="error", message="Requirements contain conflicts"
            )
        )
    if not graph.nodes:
        diagnostics.append(
            ValidationDiagnostic(code="GRAPH_EMPTY", severity="error", message="Graph has no nodes")
        )
    if (
        design.budget_policy
        and design.budget_policy.hard_limit
        and design.budget_policy.unavailable_behavior != "reject"
    ):
        diagnostics.append(
            ValidationDiagnostic(
                code="BUDGET_FAIL_OPEN",
                severity="error",
                component="budget",
                message="Hard budgets must reject when the budget authority is unavailable",
            )
        )
    for name in scope:
        state = design.components.get(name)
        if state is None or state.status not in {
            ComponentStatus.valid,
            ComponentStatus.not_applicable,
        }:
            diagnostics.append(
                ValidationDiagnostic(
                    code="SCOPE_INCOMPLETE",
                    severity="error",
                    component=name,
                    message=f"Component {name} is not valid",
                )
            )
    if strict:
        for name in DESIGN_COMPONENTS:
            state = design.components.get(name)
            if state is None or state.status not in {
                ComponentStatus.valid,
                ComponentStatus.not_applicable,
            }:
                diagnostics.append(
                    ValidationDiagnostic(
                        code="PROJECT_INCOMPLETE",
                        severity="error",
                        component=name,
                        message=f"Strict validation requires current component {name}",
                    )
                )
    return diagnostics
