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


def test_blocking_findings_trigger_bounded_revision_passes(tmp_path, monkeypatch):
    finding = {
        "severity": "blocking",
        "component": "api",
        "issue": "Approval endpoint missing",
        "recommendation": "Add one",
    }
    fake = FakeArchitect({"VerificationReport": {"findings": [finding]}})
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    calls = [name for name, _ in fake.prompts]
    assert calls.count("VerificationReport") == 3
    assert calls.count("ApiApiProposal") == 2  # only the API component is revised
    revision_prompt = dict(fake.prompts)["ApiApiProposal"]
    assert "verifier_findings_to_fix" in revision_prompt
    design = store.load_design(revision)
    assert any(item.resolved for item in design.verification)
    codes = {item.code for item in store.load_manifest(revision).diagnostics}
    assert "VERIFIER_UNRESOLVED" in codes


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
