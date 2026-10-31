from test_closure import requirements

from archai.application.designer import FIXED_SOURCE, apply_scope
from archai.application.findings import finding_target
from archai.application.merge import enforce_invariants
from archai.application.service import auto_scope
from archai.schemas.models import ArchitectureDecision


def design_with_decisions():
    design = apply_scope(None, "sample", requirements(), auto_scope(), [])
    enforce_invariants(design)
    design.decisions.append(
        ArchitectureDecision(
            id="adr-api-filter-before-ranking-and-give-the-ai-gatewa",
            component="api",
            title="Filter before ranking",
            decision="The AI gateway may try three attempts.",
            rationale="Provider timeouts.",
        )
    )
    return design


def test_fields_map_to_their_owning_components():
    design = design_with_decisions()
    target = finding_target(
        design,
        "rag",
        ["services[svc-retrieval].depends_on", "identity_policy.service_identities.svc-x"],
        "svc-retrieval depends on svc-erp",
    )
    assert target.components == ["system", "auth"]
    assert target.fixed_only is False


def test_cited_decision_ids_route_to_their_component_even_when_shortened_or_longer():
    design = design_with_decisions()
    target = finding_target(
        design,
        "routing",
        ["routing_policy.max_attempts"],
        "routing_policy caps attempts at 2 but adr-api-filter-before-ranking-and-give-the-ai-gateway "
        "commits three.",
    )
    # max_attempts is fixed, so only the decision record's owner is asked to change.
    assert target.components == ["api"]
    assert target.fixed_only is False


def test_only_fixed_values_means_no_repair():
    design = design_with_decisions()
    fixed = next(item for item in design.decisions if item.source == FIXED_SOURCE)
    target = finding_target(
        design,
        "budget",
        ["budget_policy.monthly_limit", f"decisions.{fixed.id}", "requirements.monthly_budget"],
        "The limit is too high.",
    )
    assert target.components == []
    assert target.fixed_only is True


def test_unknown_fields_fall_back_to_the_finding_component():
    design = design_with_decisions()
    target = finding_target(design, "cache", ["something.else"], "Semantic cache is on.")
    assert target.components == ["cache"]
    assert target.fixed_only is False
    assert finding_target(design, "prd", ["prd.goals"], "").components == ["requirements"]


def test_cost_engine_numbers_are_fixed():
    design = design_with_decisions()
    target = finding_target(
        design, "routing", ["capacity.input_tokens_per_minute", "endpoints.x.tpm"], ""
    )
    assert target.fixed_only is True
