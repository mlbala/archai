from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeArchitect

from archai.application import service
from archai.errors import ProviderError
from archai.persistence.store import ProjectStore

REQUIREMENTS = Path("examples/azure-enterprise-rag/requirements.yaml")


def run(tmp_path: Path, scope: list[str], project: str = "team", **kwargs):
    return service.run_generation(
        project=project,
        scope=scope,
        output_dir=tmp_path,
        files=kwargs.pop("files", [REQUIREMENTS]),
        idea=kwargs.pop("idea", None),
        stdin_enabled=False,
        answers=None,
        profile=None,
        region=None,
        target_providers=None,
        topology=None,
        archetypes=[],
        allow_assumptions=False,
        architect_provider="gemini",
        **kwargs,
    )


def install(monkeypatch: pytest.MonkeyPatch, provider) -> None:
    monkeypatch.setattr(
        "archai.application.service.create_provider", lambda settings, name, model: provider
    )


SERVICES = [
    {
        "id": "svc-support-api",
        "name": "Support API",
        "kind": "application",
        "responsibilities": ["Chat orchestration for support agents"],
        "technology": "FastAPI",
        "scaling": "HTTP",
        "exposes": ["chat"],
        "depends_on": ["svc-budget", "store-ledger-db", "svc-unknown"],
        "data_owned": [],
    },
    {
        "id": "svc-budget",
        "name": "Budget admission",
        "kind": "policy",
        "responsibilities": ["Reserve budget"],
        "technology": "Python",
        "scaling": "HTTP",
        "exposes": [],
        "depends_on": [],
        "data_owned": ["store-ledger-db"],
    },
]
STORES = [
    {
        "id": "store-ledger-db",
        "name": "Budget ledger",
        "kind": "PostgreSQL",
        "purpose": "budget ledger",
        "owner_service": "svc-budget",
        "partition_key": "org",
        "consistency": "serializable",
        "retention_days": 99999,
        "encryption": "TDE",
        "backup": "PITR",
    }
]


def test_full_design_runs_every_role_and_merges_proposals(tmp_path, monkeypatch):
    fake = FakeArchitect(
        {
            "CloudSystemDataWorkflowRagInfraResilienceProposal": {
                "services": SERVICES,
                "data_stores": STORES,
            },
            "VerificationReport": {"findings": []},
        }
    )
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope(), idea="Support copilot for agents")
    calls = [name for name, _ in fake.prompts]
    assert calls[0] == "RequirementsAnalysis"
    assert "PRDProposal" in calls
    assert {
        "ApiApiRoutingBudgetCacheProposal",
        "SecurityAuthGuardSecurityObserveEvalProposal",
    } <= set(calls)
    assert calls.count("VerificationReport") == 1
    design = store.load_design(revision)
    ids = {service.id for service in design.services}
    assert {"svc-support-api", "svc-budget"} <= ids
    api = next(s for s in design.services if s.id == "svc-support-api")
    assert "svc-unknown" not in api.depends_on  # dangling references are dropped
    assert design.data_stores[0].retention_days == 3650  # clamped
    assert any(s.kind == "gateway" for s in design.services)  # required owner added
    assert design.prd is not None
    assert design.components["system"].source == "architect:gemini:gemini-3.1-pro-preview"
    assert design.components["cost"].source == "deterministic-baseline"
    run_state = next((store.root / "runs").glob("*/run.json")).read_text()
    assert '"design_mode": "multi-agent"' in run_state
    prompt = dict(fake.prompts)["CloudSystemDataWorkflowRagInfraResilienceProposal"]
    assert "<untrusted>" in prompt and "locked_components" in prompt
    for name in ("CloudSystemDataWorkflowRagInfraResilienceProposal", "VerificationReport"):
        assert '"planning_capacity":{"peak_model_calls_per_minute"' in dict(fake.prompts)[name]
    verifier = dict(fake.prompts)["VerificationReport"]
    assert "an engineer who builds exactly what this design says" in verifier
    assert "naming, labels, and duplicate or" in verifier  # tidiness is a warning


def test_component_command_only_dispatches_its_role(tmp_path, monkeypatch):
    fake = FakeArchitect({"VerificationReport": {"findings": []}})
    install(monkeypatch, fake)
    store, revision = run(tmp_path, ["infra"])
    calls = [name for name, _ in fake.prompts]
    assert calls == ["CloudInfraProposal", "VerificationReport"]
    schema_prompt = dict(fake.prompts)["CloudInfraProposal"]
    assert '"scope":["infra"]' in schema_prompt
    design = store.load_design(revision)
    assert set(design.components) == {"infra"}
    assert design.services == [] and design.guardrails == []


def test_locked_component_is_not_redesigned(tmp_path, monkeypatch):
    install(monkeypatch, FakeArchitect({"VerificationReport": {"findings": []}}))
    store, _ = service.run_generation(
        project="locked",
        scope=["guard"],
        output_dir=tmp_path,
        files=[REQUIREMENTS],
        idea=None,
        stdin_enabled=False,
        answers=None,
        profile=None,
        region=None,
        target_providers=None,
        topology=None,
        archetypes=[],
        allow_assumptions=False,
        offline=True,
    )
    before = store.load_design().guardrails
    with store.locked():
        service.add_lock(store, "guard", None)
    fake = FakeArchitect({"VerificationReport": {"findings": []}})
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope(), project="locked", files=[])
    assert store.load_design(revision).guardrails == before
    security_prompt = next(prompt for name, prompt in fake.prompts if name.startswith("Security"))
    assert '"locked_components":["guard"]' in security_prompt
    assert "Guard" not in next(name for name, _ in fake.prompts if name.startswith("Security"))


class FailingArchitect(FakeArchitect):
    def __init__(self, fail_on: str, kind: str) -> None:
        super().__init__({"VerificationReport": {"findings": []}})
        self.fail_on = fail_on
        self.kind = kind

    def generate(self, prompt, output_type):
        if output_type.__name__.startswith(self.fail_on):
            self.prompts.append((output_type.__name__, prompt))
            raise ProviderError(f"{self.kind} failure", kind=self.kind)
        return super().generate(prompt, output_type)


def test_transient_role_failure_falls_back_to_baseline(tmp_path, monkeypatch):
    install(monkeypatch, FailingArchitect("Api", "timeout"))
    store, revision = run(tmp_path, service.auto_scope())
    design = store.load_design(revision)
    assert design.components["api"].source.startswith("deterministic-baseline (architect failed")
    assert design.api_contracts  # baseline contracts remain
    codes = {item.code for item in store.load_manifest(revision).diagnostics}
    assert "ARCHITECT_ROLE_FALLBACK" in codes


def test_authentication_failure_stops_the_run(tmp_path, monkeypatch):
    install(monkeypatch, FailingArchitect("Cloud", "authentication"))
    with pytest.raises(ProviderError):
        run(tmp_path, service.auto_scope())
    assert ProjectStore(tmp_path, "team").metadata().latest_revision == 0


def finding(component: str, issue: str, recommendation: str, **extra):
    return {
        "severity": "blocking",
        "component": component,
        "fields": [],
        "same_as": "",
        "issue": issue,
        "recommendation": recommendation,
        **extra,
    }


def test_open_finding_is_repaired_then_saved_as_a_draft(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHAI_MAX_REPAIR_PASSES", "2")
    open_finding = finding("api", "Approval endpoint missing", "Add one")
    fake = FakeArchitect({"VerificationReport": {"findings": [open_finding]}})
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    calls = [name for name, _ in fake.prompts]
    assert calls.count("VerificationReport") == 3
    repairs = [prompt for name, prompt in fake.prompts if name == "ApiApiProposal"]
    assert len(repairs) == 2
    assert all("verifier_findings_to_fix" in prompt for prompt in repairs)
    assert all("current_components" in prompt for prompt in repairs)
    # Repairs read a compact index of the rest of the design, not the full summary.
    assert all('"design_index":' in prompt for prompt in repairs)
    assert all('"existing_design":' not in prompt for prompt in repairs)
    assert all('"journeys":' not in prompt for prompt in repairs)
    reviews = [prompt for name, prompt in fake.prompts if name == "VerificationReport"]
    assert '"review_mode":"full"' in reviews[0]
    assert all('"review_mode":"changes"' in prompt for prompt in reviews[1:])
    assert '"changed_components":["api"]' in reviews[1]
    # The fake returns the same content again, so the next pass sees no change.
    assert '"changed_components":[]' in reviews[2]
    assert len(reviews[1]) < len(reviews[0])
    assert all("Approval endpoint missing" in prompt for prompt in repairs)
    assert all("Add one" in prompt for prompt in repairs)
    cloud_calls = [name for name in calls if name.startswith("Cloud")]
    assert cloud_calls == ["CloudSystemDataWorkflowRagInfraResilienceProposal"]
    # The design is kept as a draft revision instead of being thrown away.
    assert revision == 1
    manifest = store.load_manifest(revision)
    assert manifest.project_complete is False
    unresolved = [item for item in manifest.diagnostics if item.code == "VERIFIER_UNRESOLVED"]
    assert unresolved and {item.severity for item in unresolved} == {"warning"}
    design = store.load_design(revision)
    assert any(item.severity == "blocking" and not item.resolved for item in design.verification)


def test_a_finding_that_keeps_coming_back_stops_being_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHAI_MAX_REPAIR_PASSES", "4")
    stuck = finding("api", "Approval endpoint missing", "Add one", same_as="F1")
    fake = FakeArchitect({"VerificationReport": {"findings": [stuck]}})
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    calls = [name for name, _ in fake.prompts]
    assert calls.count("ApiApiProposal") == 2  # MAX_REPAIRS_PER_FINDING
    assert calls.count("VerificationReport") == 3  # stopped early instead of using all 4 passes
    design = store.load_design(revision)
    open_items = [
        item for item in design.verification if not item.resolved and item.severity == "blocking"
    ]
    assert [item.id for item in open_items] == ["F1"]
    assert open_items[0].repairs == 2
    verifier_prompts = [prompt for name, prompt in fake.prompts if name == "VerificationReport"]
    assert '"previous_findings":' not in verifier_prompts[0]
    assert '"previous_findings":[{"id":"F1"' in verifier_prompts[1]


def test_each_finding_is_sent_only_to_the_agent_that_owns_it(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHAI_MAX_REPAIR_PASSES", "1")
    findings = [
        finding(
            "budget",
            "Clerk share is 100 percent with no reserve",
            "Set the clerk share to 80 and the reserve to 20",
        ),
        finding(
            "workflow",
            "Payment write ignores the approved ERP state",
            "Require a conditional ERP write against that state",
        ),
    ]
    fake = FakeArchitect({"VerificationReport": {"findings": findings}})
    install(monkeypatch, fake)
    run(tmp_path, service.auto_scope())
    prompts = dict(fake.prompts)
    budget = prompts["ApiBudgetProposal"]
    workflow = prompts["CloudWorkflowProposal"]
    assert "Clerk share is 100 percent with no reserve" in budget
    assert "Payment write ignores the approved ERP state" not in budget
    assert "Payment write ignores the approved ERP state" in workflow
    assert "Clerk share is 100 percent with no reserve" not in workflow
    initial = prompts["CloudSystemDataWorkflowRagInfraResilienceProposal"]
    assert "Payment write ignores the approved ERP state" not in initial
    assert "Clerk share is 100 percent with no reserve" not in initial
    calls = [name for name, _ in fake.prompts]
    assert calls.index("CloudWorkflowProposal") < calls.index("ApiBudgetProposal")


def test_a_cross_component_finding_goes_to_every_owner_in_order(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHAI_MAX_REPAIR_PASSES", "1")
    cross = finding(
        "rag",
        "svc-retrieval depends on svc-erp and its grant names svc-erp for document reads",
        "Remove the dependency and the grant",
        fields=[
            "services.svc-retrieval.depends_on",
            "identity_policy.service_identities.svc-retrieval.grants",
        ],
    )
    fake = FakeArchitect({"VerificationReport": {"findings": [cross]}})
    install(monkeypatch, fake)
    run(tmp_path, service.auto_scope())
    calls = [name for name, _ in fake.prompts]
    # Routed by the named fields, not by the finding's component (rag is not changed).
    assert "CloudSystemProposal" in calls
    assert "SecurityAuthProposal" in calls
    assert "CloudRagProposal" not in calls
    assert calls.index("CloudSystemProposal") < calls.index("SecurityAuthProposal")
    prompts = dict(fake.prompts)
    assert '"you_change":["system"]' in prompts["CloudSystemProposal"]
    assert '"other_owners_change":["auth"]' in prompts["CloudSystemProposal"]
    assert '"you_change":["auth"]' in prompts["SecurityAuthProposal"]


def test_a_prd_finding_is_sent_to_the_requirements_role(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHAI_MAX_REPAIR_PASSES", "1")
    prd_finding = finding(
        "requirements",
        "The PRD says the model limit caps total operating spend",
        "State that the limit covers model calls only",
        fields=["prd.goals"],
    )
    fake = FakeArchitect({"VerificationReport": {"findings": [prd_finding]}})
    install(monkeypatch, fake)
    run(tmp_path, service.auto_scope())
    prd_prompts = [prompt for name, prompt in fake.prompts if name == "PRDProposal"]
    assert len(prd_prompts) == 2
    assert "current_prd" not in prd_prompts[0]
    assert "current_prd" in prd_prompts[1]
    assert "model limit caps total operating spend" in prd_prompts[1]
    assert '"fixed_facts"' in prd_prompts[1]
    verifier = next(prompt for name, prompt in fake.prompts if name == "VerificationReport")
    assert '"requirements"]' in verifier  # the PRD is reviewable


def test_a_finding_that_only_disputes_a_fixed_value_is_not_sent(tmp_path, monkeypatch):
    disputed = finding(
        "budget",
        "The EUR limit is higher than finance approved",
        "Lower it",
        fields=["budget_policy.monthly_limit"],
    )
    fake = FakeArchitect({"VerificationReport": {"findings": [disputed]}})
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    calls = [name for name, _ in fake.prompts]
    assert calls.count("VerificationReport") == 1
    assert "ApiBudgetProposal" not in calls
    design = store.load_design(revision)
    disputed_items = [item for item in design.verification if item.id == "F1"]
    assert [item.severity for item in disputed_items] == ["warning"]
    assert "from the requirements" in disputed_items[0].recommendation
    manifest = store.load_manifest(revision)
    assert "VERIFIER_FIXED_FACT" in {item.code for item in manifest.diagnostics}
    assert manifest.project_complete is True


def test_cleared_finding_marks_the_revision_complete(tmp_path, monkeypatch):
    open_finding = finding("api", "Approval endpoint missing", "Add one")

    class ClearOnSecondVerify(FakeArchitect):
        def __init__(self) -> None:
            super().__init__(
                {"VerificationReport": {"findings": [open_finding], "summary": "Open."}}
            )
            self.verifications = 0

        def generate(self, prompt, output_type):
            if output_type.__name__ == "VerificationReport":
                self.verifications += 1
                if self.verifications > 1:
                    self.overrides["VerificationReport"] = {"findings": [], "summary": "Closed."}
            return super().generate(prompt, output_type)

    fake = ClearOnSecondVerify()
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    design = store.load_design(revision)
    assert any(item.resolved for item in design.verification)
    assert not any(
        item.severity == "blocking" and not item.resolved for item in design.verification
    )
    codes = {item.code for item in store.load_manifest(revision).diagnostics}
    assert "VERIFIER_UNRESOLVED" not in codes
    assert store.load_manifest(revision).project_complete is True


def test_call_budget_exhaustion_degrades_gracefully(tmp_path, monkeypatch):
    install(monkeypatch, FakeArchitect({"VerificationReport": {"findings": []}}))
    monkeypatch.setenv("ARCHAI_MAX_GENERATION_CALLS", "2")
    store, revision = run(tmp_path, service.auto_scope())
    codes = [item.code for item in store.load_manifest(revision).diagnostics]
    assert "ARCHITECT_ROLE_FALLBACK" in codes
    assert any(
        "budget" in (item.message or "") for item in store.load_manifest(revision).diagnostics
    )


def test_role_models_route_the_verifier_to_a_second_provider(tmp_path, monkeypatch):
    used: list[tuple[str, str]] = []
    fake = FakeArchitect({"VerificationReport": {"findings": []}})

    def factory(settings, name, model):
        used.append((name, model))
        return fake

    monkeypatch.setattr("archai.application.service.create_provider", factory)
    monkeypatch.setenv("ARCHAI_OPENAI_API_KEY", "test-key")
    run(tmp_path, ["guard"], role_models=["verifier=openai:review-model"])
    assert ("openai", "review-model") in used
    assert ("gemini", "gemini-3.1-pro-preview") in used


def test_quota_failure_fails_over_to_the_other_configured_provider(tmp_path, monkeypatch):
    class Exhausted:
        calls = 0

        def generate(self, prompt, output_type):
            Exhausted.calls += 1
            raise ProviderError("quota exhausted", kind="rate_limit")

    healthy = FakeArchitect({"VerificationReport": {"findings": []}})

    def factory(settings, name, model):
        return Exhausted() if name == "gemini" else healthy

    monkeypatch.setattr("archai.application.service.create_provider", factory)
    monkeypatch.setenv("ARCHAI_GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("ARCHAI_OPENAI_API_KEY", "openai-key")
    store, revision = run(tmp_path, service.auto_scope(), idea="Support copilot")
    assert Exhausted.calls == 1  # the failing provider is skipped after the first failure
    design = store.load_design(revision)
    assert design.components["system"].source == "architect:openai:gpt-6-sol"
    codes = {item.code for item in store.load_manifest(revision).diagnostics}
    assert "ARCHITECT_ROLE_FALLBACK" not in codes


def test_live_run_regressions_owasp_region_fallback_and_roles(tmp_path, monkeypatch):
    threat = {
        "id": "threat-injection",
        "title": "Injected instructions",
        "stride": "tampering",
        "owasp_ref": "LLM01:2025 Prompt Injection",
        "severity": "high",
        "affected": ["svc-app"],
        "mitigation": "Treat content as data",
        "owner": "security",
        "residual_risk": "medium",
    }
    alias = {
        "id": "enterprise-chat",
        "task": "chat",
        "required_capabilities": ["managed text generation", "streaming support"],
        "max_output_tokens": 1000,
        "primary_provider": "Azure OpenAI",
        "fallback_providers": [],
        "quality_gate": "eval",
    }
    fake = FakeArchitect(
        {
            "SecurityAuthGuardSecurityObserveEvalProposal": {"threats": [threat]},
            "ApiApiRoutingBudgetCacheProposal": {"model_aliases": [alias]},
            "VerificationReport": {"findings": []},
        }
    )
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    design = store.load_design(revision)
    assert design.threats[0].owasp_ref == "LLM01:2025"
    bedrock = next(e for e in design.endpoints if e.provider == "AWS Bedrock")
    assert bedrock.region == "eu-central-1"  # AWS-native region in the EU geography
    chat = next(a for a in design.model_aliases if a.id == "enterprise-chat")
    assert chat.required_capabilities == ["text", "streaming"]
    assert chat.fallback_endpoint_ids == [bedrock.id]  # provider-failover topology enforced
    assert not any(
        "*" in permission
        for item in design.identity_policy.roles
        for permission in item.permissions
    )
    calls = [name for name, _ in fake.prompts]
    assert calls.index("ApiApiRoutingBudgetCacheProposal") < calls.index(
        "SecurityAuthGuardSecurityObserveEvalProposal"
    )
    security_prompt = dict(fake.prompts)["SecurityAuthGuardSecurityObserveEvalProposal"]
    assert '"scopes":' in security_prompt


def test_the_chief_architect_plans_before_the_specialists(tmp_path, monkeypatch):
    plan = {
        "style": "streaming Q&A with an async intake pipeline",
        "services": [
            {
                "id": "svc-answers",
                "name": "Answers",
                "kind": "application",
                "purpose": "Grounded answers for support agents",
                "depends_on": ["svc-admission"],
            }
        ],
    }
    fake = FakeArchitect({"ArchitecturePlanProposal": plan, "VerificationReport": {"findings": []}})
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    calls = [name for name, _ in fake.prompts]
    assert calls.index("PRDProposal") < calls.index("ArchitecturePlanProposal")
    assert calls.index("ArchitecturePlanProposal") < calls.index(
        "CloudSystemDataWorkflowRagInfraResilienceProposal"
    )
    prompts = dict(fake.prompts)
    assert '"archai_defaults":' in prompts["ArchitecturePlanProposal"]
    assert "Choose the shape of the system" in prompts["ArchitecturePlanProposal"]  # skill
    cloud = prompts["CloudSystemDataWorkflowRagInfraResilienceProposal"]
    assert '"architecture_plan":{"style":"streaming Q&A' in cloud
    assert '"architecture_plan"' not in prompts["VerificationReport"]
    design = store.load_design(revision)
    assert design.architecture_plan is not None
    assert design.architecture_plan.services[0].id == "svc-answers"


def test_a_component_command_does_not_replan(tmp_path, monkeypatch):
    fake = FakeArchitect({"VerificationReport": {"findings": []}})
    install(monkeypatch, fake)
    run(tmp_path, ["api"])
    assert "ArchitecturePlanProposal" not in [name for name, _ in fake.prompts]


def test_a_rejected_endpoint_is_reported_back_with_its_reason(tmp_path, monkeypatch):
    endpoints = [
        {
            "provider": "Azure OpenAI",
            "region": "eastus",
            "purpose": "chat",
            "deployment_role": "primary",
            "reason": "lower latency",
        }
    ]
    fake = FakeArchitect(
        {
            "ApiApiRoutingBudgetCacheProposal": {"endpoints": endpoints},
            "VerificationReport": {"findings": []},
        }
    )
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    codes = {item.code for item in store.load_manifest(revision).diagnostics}
    assert "ENDPOINT_REJECTED" in codes
    review = dict(fake.prompts)["VerificationReport"]
    assert '"archai_rejected_changes":[' in review
    assert '{"component":"routing","message":"Did not add a chat deployment' in review
    assert "outside data residency" in review
    design = store.load_design(revision)
    assert all(item.region != "eastus" for item in design.endpoints)


def test_a_service_cycle_is_reported_and_sent_to_the_cloud_role(tmp_path, monkeypatch):
    cyclic = [
        {**SERVICES[0], "depends_on": ["svc-budget"]},
        {**SERVICES[1], "depends_on": ["svc-gw-ai"]},
        {
            "id": "svc-gw-ai",
            "name": "AI gateway",
            "kind": "ai-gateway",
            "responsibilities": ["Route model calls"],
            "technology": "LiteLLM",
            "scaling": "HTTP",
            "exposes": [],
            "depends_on": ["svc-budget"],
            "data_owned": [],
        },
    ]
    fake = FakeArchitect(
        {
            "CloudSystemDataWorkflowRagInfraResilienceProposal": {"services": cyclic},
            "VerificationReport": {"findings": []},
        }
    )
    install(monkeypatch, fake)
    store, _ = run(tmp_path, service.auto_scope())
    calls = [name for name, _ in fake.prompts]
    # The self-check sends the cycle straight back to the cloud role, before the API role
    # designs on top of it and before the first review.
    assert calls.index("CloudSystemProposal") < calls.index("ApiApiRoutingBudgetCacheProposal")
    assert calls.index("CloudSystemProposal") < calls.index("VerificationReport")
    repair = dict(fake.prompts)["CloudSystemProposal"]
    assert "[ArchAI check] Services depend on each other in a cycle" in repair
    run_state = next((store.root / "runs").glob("*/run.json")).read_text()
    assert '"step": "cloud · self-check"' in run_state
    # Python no longer forces its own call order on top of the role's design: the role is
    # shown its own wiring, with admission calling the AI gateway and not the reverse added.
    assert '"id":"svc-budget"' in repair
    assert '"depends_on":["svc-gw-ai"]' in repair


def test_the_plan_replaces_the_template_for_the_components_being_designed(tmp_path, monkeypatch):
    plan = {"style": "event-driven intake with a small answer API"}
    fake = FakeArchitect({"ArchitecturePlanProposal": plan, "VerificationReport": {"findings": []}})
    install(monkeypatch, fake)
    run(tmp_path, service.auto_scope())
    prompts = dict(fake.prompts)
    cloud = prompts["CloudSystemDataWorkflowRagInfraResilienceProposal"]
    assert '"architecture_plan":{"style":"event-driven intake' in cloud
    # The cloud role does not see ArchAI's template services, stores, or workflows...
    assert '"services":[{"id":"svc-ingress"' not in cloud
    assert (
        '"data_stores":' not in cloud.split('"existing_design":')[1].split('"architecture_plan"')[0]
    )
    # ...but the API role still sees the services the cloud role designed.
    api = prompts["ApiApiRoutingBudgetCacheProposal"]
    assert '"existing_design":{"services":[' in api


def test_a_clamped_value_is_reported_back_with_its_meaning(tmp_path, monkeypatch):
    fake = FakeArchitect(
        {
            "ApiApiRoutingBudgetCacheProposal": {
                "budget": {
                    "allocations": [{"scope": "department:Support", "share_percent": 90}],
                    "soft_limit_percent": 80,
                    "per_request_token_ceiling": 20000,
                    "per_workflow_step_ceiling": 8000,
                    "rationale": "8000 tokens per indexing step",
                }
            },
            "VerificationReport": {"findings": []},
        }
    )
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    design = store.load_design(revision)
    assert design.budget_policy.per_workflow_step_ceiling == 200
    review = dict(fake.prompts)["VerificationReport"]
    assert "per_workflow_step_ceiling 8000 is outside 1–200" in review
    assert "not tokens" in review
