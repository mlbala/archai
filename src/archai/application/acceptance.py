"""The acceptance checklist the verifier answers on every pass.

An open-ended review finds something different every time it runs. A checklist asks the
same questions every run: one criterion per hard requirement, per must-have PRD requirement,
per non-functional target, and per user journey. Each criterion keeps its id across passes,
so a failure is tracked until it passes, and the design is done when every criterion passes
and no blocking finding is open.
"""

from __future__ import annotations

from typing import Literal

from archai.application.designer import has_rag, uses_tools
from archai.schemas.models import AcceptanceCriterion, EnterpriseDesign

# Components a criterion usually involves; a failure names the exact fields to change.
_REQUIREMENT_COMPONENTS = {
    "residency": ["data", "infra", "routing"],
    "tenancy": ["data", "rag", "cache", "auth"],
    "side-effects": ["workflow", "guard", "auth", "api"],
    "classification": ["cache", "guard", "observe"],
    "budget": ["budget", "routing", "system"],
    "latency": ["resilience", "routing", "system"],
    "availability": ["observe", "resilience"],
    "recovery": ["resilience", "infra", "routing"],
    "channels": ["api", "auth", "system"],
    "identity": ["auth", "api"],
    "integration": ["system", "auth"],
    "source": ["rag", "workflow", "data"],
}


def _criterion(
    identifier: str,
    source: Literal["requirement", "prd", "journey"],
    text: str,
    key: str = "",
) -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=identifier,
        source=source,
        text=text,
        components=list(_REQUIREMENT_COMPONENTS.get(key, [])),
    )


def _requirement_criteria(design: EnterpriseDesign) -> list[AcceptanceCriterion]:
    req = design.requirements
    regions = ", ".join(dict.fromkeys(req.data_residency or [req.region]))
    items = [
        _criterion(
            "C-R-RESIDENCY",
            "requirement",
            f"Every data store, model endpoint, and processing step stays inside {regions}.",
            "residency",
        ),
        _criterion(
            "C-R-TENANCY",
            "requirement",
            "Each request reads only its own tenant's data: stores, index, cache keys, queues, "
            "and logs carry the tenant key."
            if req.tenant_isolation == "multi"
            else "Data, index entries, cache keys, and logs are bound to the organization and to "
            "the caller's permissions.",
            "tenancy",
        ),
        _criterion(
            "C-R-BUDGET",
            "requirement",
            f"Every billable model attempt is reserved against the {req.currency} "
            f"{req.monthly_budget} model-call hard limit before dispatch, and new model calls are "
            "rejected when it is reached.",
            "budget",
        ),
        _criterion(
            "C-R-IDENTITY",
            "requirement",
            f"Users sign in with {req.identity_provider or 'the identity provider'}; every role's "
            "permissions are scopes of existing operations, and every service call has a "
            "least-privilege grant.",
            "identity",
        ),
        _criterion(
            "C-R-AVAILABILITY",
            "requirement",
            f"The {req.availability_target}% availability target has an SLO in which "
            "dependency, model, and budget failures count as unavailable.",
            "availability",
        ),
    ]
    if uses_tools(req) or req.tool_side_effects != "forbidden":
        text = {
            "forbidden": "No component can change an external system; every tool and grant is "
            "read-only.",
            "approval": "Every change to an external system waits for a person to approve the "
            "exact action, and the approvals inbox and decision operations exist.",
            "allowed": "Autonomous changes to external systems are limited by the caller's "
            "authorization, bounded, and audited.",
        }[req.tool_side_effects]
        items.append(_criterion("C-R-SIDE-EFFECTS", "requirement", text, "side-effects"))
    else:
        items.append(
            _criterion(
                "C-R-SIDE-EFFECTS",
                "requirement",
                "The design has no path that changes an external system.",
                "side-effects",
            )
        )
    if req.data_classification:
        items.append(
            _criterion(
                "C-R-CLASSIFICATION",
                "requirement",
                f"Handling matches {req.data_classification} data: release checks, log "
                "redaction, and cache use fit the classification"
                + (" (semantic cache off)." if req.data_classification == "restricted" else "."),
                "classification",
            )
        )
    if req.latency_p95_ms:
        items.append(
            _criterion(
                "C-R-LATENCY",
                "requirement",
                f"The interactive path fits the {req.latency_p95_ms} ms p95 target: per-hop "
                "timeouts add up within it.",
                "latency",
            )
        )
    if req.rto_minutes is not None or req.rpo_minutes is not None:
        items.append(
            _criterion(
                "C-R-RECOVERY",
                "requirement",
                f"RTO {req.rto_minutes or '—'} and RPO {req.rpo_minutes or '—'} minutes are met "
                f"for failures restorable inside {regions}, with every component recovery needs, "
                "including model endpoints, in place.",
                "recovery",
            )
        )
    if req.client_channels:
        items.append(
            _criterion(
                "C-R-CHANNELS",
                "requirement",
                f"Each client channel ({', '.join(req.client_channels)}) reaches the application "
                "through the enterprise gateway with user sign-in.",
                "channels",
            )
        )
    for index, name in enumerate(req.integrations[:6], start=1):
        items.append(
            _criterion(
                f"C-R-INTEGRATION-{index}",
                "requirement",
                f"{name} is reached through a named service with least-privilege access that "
                "matches the tool side-effect policy.",
                "integration",
            )
        )
    if has_rag(req):
        for index, name in enumerate(req.data_sources[:6], start=1):
            items.append(
                _criterion(
                    f"C-R-SOURCE-{index}",
                    "requirement",
                    f"{name} is ingested with its access permissions and freshness, and answers "
                    "drawn from it cite the source and version a user is allowed to open.",
                    "source",
                )
            )
    return items


def _prd_criteria(design: EnterpriseDesign) -> list[AcceptanceCriterion]:
    prd = design.prd
    if prd is None:
        return []
    items = [
        AcceptanceCriterion(id=f"C-{item.id}", source="prd", text=f"{item.id}: {item.statement}")
        for item in prd.functional_requirements
        if item.priority == "must"
    ][:16]
    items += [
        AcceptanceCriterion(
            id=f"C-{item.id}",
            source="prd",
            text=f"{item.id} ({item.category}): {item.statement} Target: {item.target}",
        )
        for item in prd.non_functional_requirements
    ][:12]
    items += [
        AcceptanceCriterion(
            id=f"C-J{index}",
            source="journey",
            text=f"Journey '{journey.name}' can be completed end to end: every step has an "
            "operation or job, the permission it needs, and the data it reads or writes.",
            components=["system", "api", "auth", "workflow"],
        )
        for index, journey in enumerate(prd.journeys[:6], start=1)
    ]
    return items


def acceptance_checklist(
    design: EnterpriseDesign, reviewable: list[str]
) -> list[AcceptanceCriterion]:
    """The criteria that apply to the components this run designs."""
    scope = set(reviewable)
    full = "system" in scope
    criteria = [
        item for item in _requirement_criteria(design) if full or set(item.components) & scope
    ]
    if full:
        criteria += _prd_criteria(design)
    seen: set[str] = set()
    unique = []
    for item in criteria:
        if item.id not in seen:
            seen.add(item.id)
            unique.append(item)
    return unique
