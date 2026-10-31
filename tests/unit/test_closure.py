from decimal import Decimal

from archai.application.designer import FIXED_SOURCE, apply_scope
from archai.application.merge import enforce_invariants
from archai.application.service import auto_scope
from archai.compilers.report import project_complete
from archai.schemas.models import (
    APIContract,
    ArchitectureDecision,
    BudgetAllocation,
    RequirementsSpec,
    VerificationFinding,
)


def requirements() -> RequirementsSpec:
    return RequirementsSpec.model_validate(
        {
            "idea": "Answer employee questions from approved sources.",
            "business_outcome": "Shorten the time to a permitted answer.",
            "users": ["Employees", "Approvers"],
            "user_roles": ["employee", "approver"],
            "archetypes": ["enterprise-rag", "tool-using-agent"],
            "integrations": ["HR"],
            "region": "westeurope",
            "data_residency": ["westeurope"],
            "tenant_isolation": "single",
            "identity_provider": "Entra ID",
            "allowed_target_providers": ["Azure OpenAI"],
            "tool_side_effects": "approval",
            "avg_rps": 2,
            "peak_rps": 8,
            "input_tokens": 3000,
            "output_tokens": 600,
            "model_calls_per_request": 3,
            "monthly_budget": 25000,
            "currency": "EUR",
            "availability_target": 99.9,
            "profile": "azure-aca",
            "topology": "single-cloud",
            "rto_minutes": 240,
            "rpo_minutes": 60,
        }
    )


def test_invariants_close_budget_recovery_quota_and_approval_gaps():
    design = apply_scope(None, "sample", requirements(), auto_scope(), [])
    assert design.budget_policy is not None
    design.budget_policy.allocations = [
        BudgetAllocation(scope="department:Employees", share_percent=Decimal("40"), amount=0),
        BudgetAllocation(scope="platform-reserve", share_percent=Decimal("30"), amount=0),
        BudgetAllocation(scope="database", share_percent=Decimal("30"), amount=0),
    ]
    design.budget_policy.rationale = "The ceiling covers the complete workload."
    assert design.resilience is not None
    design.resilience.dr_strategy = "Fail over to northeurope and restore from backups there."
    for endpoint in design.endpoints:
        endpoint.quota_status = "confirmed"
    design.api_contracts = [
        contract
        for contract in design.api_contracts
        if not contract.path.startswith("/v1/approvals")
    ]
    app = next(service for service in design.services if service.kind == "application")
    app.exposes = [item for item in app.exposes if item != "approvals"]

    codes = {item.code for item in enforce_invariants(design)}

    assert design.budget_policy.enforcement_scope == "model-calls"
    # Shares are the API role's design choice: kept as proposed, amounts follow the limit.
    assert [item.scope for item in design.budget_policy.allocations] == [
        "department:Employees",
        "platform-reserve",
        "database",
    ]
    assert [item.amount for item in design.budget_policy.allocations] == [
        Decimal("10000.00"),
        Decimal("7500.00"),
        Decimal("7500.00"),
    ]
    assert design.budget_policy.monthly_limit == Decimal("25000")
    # A plan naming a region outside residency is replaced by ArchAI's in-region plan.
    assert "northeurope" not in design.resilience.dr_strategy
    assert "westeurope" in design.resilience.dr_strategy
    assert "accepted risk" in design.resilience.dr_strategy
    assert {endpoint.quota_status for endpoint in design.endpoints} == {"planning"}
    paths = {(contract.method, contract.path) for contract in design.api_contracts}
    assert ("GET", "/v1/approvals") in paths
    assert ("POST", "/v1/approvals/{approval_id}/decision") in paths
    # The approval paths are exposed; a bare "approvals" entry is not put back.
    assert "GET /v1/approvals" in app.exposes
    assert "POST /v1/approvals/{approval_id}/decision" in app.exposes
    assert "approvals" not in app.exposes
    approver = next(role for role in design.identity_policy.roles if "approv" in role.name.lower())
    assert "approvals.read" in approver.permissions
    assert {"DR_REGION_REJECTED", "QUOTA_PLANNING", "APPROVAL_INBOX"} <= codes
    # A plan that stays inside residency is the role's to keep.
    design.resilience.dr_strategy = "Warm standby of the app tier; restore stores from backups."
    enforce_invariants(design)
    assert (
        design.resilience.dr_strategy
        == "Warm standby of the app tier; restore stores from backups."
    )
    assert project_complete(design)
    design.verification = [
        VerificationFinding(
            severity="blocking",
            component="budget",
            issue="The limit still covers non-model spend.",
            recommendation="Narrow it.",
        )
    ]
    assert project_complete(design) is False


def test_fixed_facts_are_restated_by_python_not_by_regex_rewrites():
    design = apply_scope(None, "sample", requirements(), auto_scope(), [])
    assert design.budget_policy is not None
    assert design.routing_policy is not None
    design.routing_policy.max_attempts = 3
    model_text = "The AI gateway may dispatch three attempts when the first two fail."
    design.decisions.append(
        ArchitectureDecision(
            id="adr-routing-third",
            component="routing",
            title="Third attempt",
            decision=model_text,
            rationale="A third billable attempt covers provider timeouts.",
        )
    )

    codes = {item.code for item in enforce_invariants(design)}

    assert design.routing_policy.max_attempts == 2
    assert "ATTEMPT_LIMIT" in codes
    # A model's prose is left for the verifier to flag and its owner to fix.
    third = next(item for item in design.decisions if item.id == "adr-routing-third")
    assert third.decision == model_text
    fixed = {item.title: item for item in design.decisions if item.source == FIXED_SOURCE}
    assert {"Model-call hard limit", "Model attempt limit", "Recovery scope"} <= set(fixed)
    assert "EUR 25000" in fixed["Model-call hard limit"].decision
    assert "at most 2 attempts" in fixed["Model attempt limit"].decision
    assert "westeurope" in fixed["Recovery scope"].decision

    before = list(design.decisions)
    again = {item.code for item in enforce_invariants(design)}
    assert "ATTEMPT_LIMIT" not in again
    assert sorted(item.id for item in design.decisions) == sorted(item.id for item in before)


def test_no_project_specific_service_is_added_to_retrieval_designs():
    design = apply_scope(None, "sample", requirements(), auto_scope(), [])
    enforce_invariants(design)
    kinds = {service.kind for service in design.services}
    assert "document-access" not in kinds
    retrieval = next(service for service in design.services if service.kind == "retrieval")
    assert retrieval.depends_on == ["store-vector", "svc-admission"]


def test_public_surface_follows_the_contract_list():
    design = apply_scope(None, "sample", requirements(), auto_scope(), [])
    app = next(service for service in design.services if service.kind == "application")
    gateway = next(service for service in design.services if service.kind == "gateway")
    gateway.exposes = ["/v1/*", "POST /v1/jobs", "api-chat POST /v1/chat"]
    app.exposes = ["jobs", "POST /v1/feedback", "api-chat POST /v1/chat"]
    design.api_contracts = [
        contract
        for contract in design.api_contracts
        if contract.path not in {"/v1/jobs", "/v1/feedback"}
    ]
    design.api_contracts.append(
        APIContract(
            id="api-erp-state",
            path="/v1/records/{record_id}",
            method="GET",
            auth="bearer",
            service_id=app.id,
            scopes=["records.read"],
        )
    )

    codes = {item.code for item in enforce_invariants(design)}

    assert "PUBLIC_SURFACE" in codes
    exposed = set(gateway.exposes) | set(app.exposes)
    assert "POST /v1/jobs" not in exposed
    assert "POST /v1/feedback" not in exposed
    assert "/v1/*" not in gateway.exposes
    assert "jobs" in app.exposes  # resource names are the cloud role's to change
    assert "GET /v1/records/{record_id}" in app.exposes
    assert "GET /v1/records/{record_id}" in gateway.exposes
    operations = {f"{contract.method} {contract.path}" for contract in design.api_contracts}
    assert set(gateway.exposes) == operations  # one METHOD /path entry per contract
    assert len(gateway.exposes) == len(operations)  # "api-chat POST /v1/chat" is not doubled
    assert app.exposes.count("POST /v1/chat") == 1
    assert not [item for item in app.exposes if item.startswith("/v1/")]  # no bare paths
    assert "PUBLIC_SURFACE" not in {item.code for item in enforce_invariants(design)}


def test_planning_capacity_is_one_set_of_numbers_for_every_role():
    from archai.application.designer import fixed_facts

    req = requirements()
    design = apply_scope(None, "sample", req, auto_scope(), [])
    enforce_invariants(design)
    capacity = fixed_facts(req)["planning_capacity"]
    # peak 8 rps x 60 x 3 calls = 1,440 calls; x 2 attempts = 2,880 dispatches per minute
    assert capacity["peak_model_calls_per_minute"] == 1440
    assert capacity["peak_dispatches_per_minute_with_retries"] == 2880
    assert capacity["peak_input_tokens_per_minute"] == 2880 * 3000
    assert capacity["peak_output_tokens_per_minute"] == 2880 * 600
    chat = [item for item in design.endpoints if "embeddings" not in item.modalities]
    embedding = [item for item in design.endpoints if "embeddings" in item.modalities]
    assert {item.rpm for item in chat} == {capacity["chat_endpoint_rpm"]}
    assert {item.tpm for item in chat} == {capacity["chat_endpoint_tpm"]}
    assert capacity["chat_endpoint_tpm"] == capacity["peak_total_tokens_per_minute"]
    assert embedding[0].rpm == capacity["embedding_endpoint_rpm"]
    assert embedding[0].tpm == capacity["embedding_endpoint_tpm"]
    # The cost engine uses the same arithmetic.
    from archai.application.designer import baseline_component

    baseline_component(design, "cost")
    assert design.capacity is not None
    assert (
        int(design.capacity.calls_per_minute) == capacity["peak_dispatches_per_minute_with_retries"]
    )
    attempt = next(item for item in design.decisions if item.title == "Model attempt limit")
    assert "2,880 dispatches" in attempt.decision
    assert "10,368,000 tokens per minute" in attempt.decision
    traffic = fixed_facts(req)["traffic"]
    assert traffic["input_tokens_per_model_call"] == 3000
    assert "not per-request" in traffic["meaning"]


def test_application_dr_gets_standby_endpoints_inside_residency():
    from types import SimpleNamespace

    from archai.application.designer import proposed_endpoint, target_endpoints

    req = requirements().model_copy(
        update={"topology": "application-dr", "data_residency": ["westeurope", "northeurope"]}
    )
    design = apply_scope(None, "sample", req, auto_scope(), [])
    enforce_invariants(design)
    recovery = [item for item in design.endpoints if item.deployment_role == "recovery"]
    assert {item.region for item in recovery} == {"northeurope"}
    assert {tuple(item.modalities) for item in recovery} == {("text",), ("embeddings",)}
    for alias in design.model_aliases:
        assert alias.recovery_endpoint_ids, alias.id
        assert not set(alias.recovery_endpoint_ids) & set(alias.fallback_endpoint_ids)
    assert all(item.deployment_role == "primary" for item in target_endpoints(requirements()))

    def ask(**overrides):
        item = {
            "provider": "Azure OpenAI",
            "region": "northeurope",
            "purpose": "chat",
            "deployment_role": "recovery",
            "reason": "standby",
        }
        return proposed_endpoint(req, design.endpoints, SimpleNamespace(**{**item, **overrides}))

    assert ask() == (None, None)  # already present
    added, reason = ask(deployment_role="primary")
    assert added is not None and added.region == "northeurope" and reason is None
    assert "outside data residency" in (ask(region="eastus")[1] or "")
    assert "not an allowed target provider" in (ask(provider="AWS Bedrock")[1] or "")


def test_a_repair_patch_keeps_items_it_does_not_return():
    from archai.application.merge import ProposalMerger
    from archai.schemas.proposals import scoped_proposal_model

    design = apply_scope(None, "sample", requirements(), auto_scope(), [])
    enforce_invariants(design)
    before = {service.id for service in design.services}
    worker = next(service for service in design.services if service.kind == "worker")
    app = next(service for service in design.services if service.kind == "application")
    kept_decision = next(item for item in design.decisions if item.component == "system")
    model = scoped_proposal_model("cloud", ["system"], patch=True)
    assert "remove_ids" in model.model_fields
    proposal = model.model_validate(
        {
            "services": [
                {
                    "id": app.id,
                    "name": "Answers",
                    "kind": "application",
                    "responsibilities": ["Grounded answers"],
                    "technology": "FastAPI",
                    "scaling": "HTTP",
                    "exposes": ["chat"],
                    "depends_on": ["svc-admission"],
                    "data_owned": [],
                }
            ],
            "decisions": [
                {
                    "component": "system",
                    "title": "Answers own the chat journey",
                    "decision": "d",
                    "rationale": "r",
                    "alternatives": [],
                    "consequences": "c",
                }
            ],
            "remove_ids": [worker.id],
        }
    )

    ProposalMerger(design, "architect:test:model", patch=True).merge(proposal, ["system"])

    ids = {service.id for service in design.services}
    assert ids == before - {worker.id}
    assert next(service for service in design.services if service.id == app.id).name == "Answers"
    titles = {item.title for item in design.decisions if item.component == "system"}
    assert {kept_decision.title, "Answers own the chat journey"} <= titles
