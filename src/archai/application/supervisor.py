"""Bounded supervisor coordinating the five specialist architect roles.

Roles 1-4 return structured proposals that are merged and validated deterministically; role 5
cross-checks the result. Calls are bounded by a shared call/token budget and at most two semantic
revision passes. Generation runs in worker threads; merging happens on the calling thread.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel

from archai.application import designer
from archai.application.merge import ProposalMerger, enforce_invariants
from archai.architect_providers.base import ArchitectProvider
from archai.architect_providers.factory import RoleBinding
from archai.errors import ProviderError
from archai.interview.questions import QUESTIONS
from archai.schemas.models import (
    PRD,
    ComponentStatus,
    DecisionLock,
    EnterpriseDesign,
    Journey,
    NFRItem,
    Persona,
    RequirementItem,
    RoleCallRecord,
    ValidationDiagnostic,
    VerificationFinding,
)
from archai.schemas.proposals import (
    PRDProposal,
    RequirementsAnalysis,
    VerificationReport,
    scoped_proposal_model,
)

T = TypeVar("T", bound=BaseModel)
StepStatus = Literal["pending", "running", "done", "failed", "skipped"]

ROLE_NAMES = {
    "requirements": "Enterprise Requirements Architect",
    "cloud": "Cloud, Data, and Resilience Architect",
    "api": "API Management and AI Routing Architect",
    "security": "Identity, Security, and Observability Architect",
    "verifier": "Design Verifier and Compiler",
}
ROLE_COMPONENTS: dict[str, tuple[str, ...]] = {
    "cloud": ("system", "data", "workflow", "rag", "infra", "resilience"),
    "api": ("api", "routing", "budget", "cache"),
    "security": ("auth", "guard", "security", "observe", "eval"),
}
ROLE_SKILLS = {
    "requirements": ("enterprise_prd",),
    "cloud": ("cloud_data_and_identity", "resilience_and_queues"),
    "api": ("api_routing_and_budgets",),
    "security": ("guardrails_observability", "cloud_data_and_identity"),
    "verifier": (
        "api_routing_and_budgets",
        "resilience_and_queues",
        "guardrails_observability",
    ),
}
ROLE_PROMPTS = {"cloud": "cloud_data.md", "api": "api_routing.md", "security": "security.md"}
STEP_TITLES = {
    "intake": "Requirements analysis",
    "prd": "Product requirements (PRD)",
    "cloud": "Microservices, data, workflows, RAG, infra & resilience",
    "api": "APIs, model routing, budgets & caching",
    "security": "Identity/OAuth, guardrails, threat model, observability & evals",
    "cost": "Capacity and cost engine (deterministic)",
    "verify": "Cross-component verification",
}

COMPONENT_GUIDANCE = {
    "system": "services: 6-12 services forming the microservice architecture. Include exactly one "
    "enterprise API gateway (kind gateway), an application/orchestration service, a model "
    "admission and budget service (kind policy), and one AI gateway (kind ai-gateway, e.g. "
    "LiteLLM). Add retrieval, ingestion, worker, tool-executor, or integration services only when "
    "the requirements need them. depends_on lists the service or data-store IDs it calls; exposes "
    "lists API resources or events it provides.",
    "data": "data_stores: concrete managed services for the hosting profile with owner_service "
    "(a service ID), partition key, consistency, retention, encryption, and backup. Include a "
    "transactional budget ledger, object storage for documents, and one vector store only if "
    "retrieval is needed.",
    "workflow": "workflows: the key end-to-end flows (interactive request, async jobs, tool "
    "actions, ingestion) as 4-10 short verb steps; hitl_required=true where a human approves.",
    "rag": "rag: set applicable=false if no retrieval is needed. Otherwise specify ingestion "
    "steps, chunking, embedding alias, dimensions, similarity, retrieval mode, top_k, reranking, "
    "grounding/citation policy, freshness, and ACL enforcement.",
    "infra": "infra: compute choice, environments, networking controls, and 6-14 concrete cloud "
    "resources (service, SKU/tier, purpose) for the hosting profile, plus IaC notes.",
    "resilience": "resilience: bounded retries with exactly one retry owner, circuit breaker "
    "parameters, per-hop timeouts, queue max attempts and max age, DLQ owner, scaling rules bounded "
    "by provider quota, degraded modes, and a DR strategy consistent with the topology.",
    "api": "api_contracts: 5-12 external REST operations (method, /v1 path, summary, owning "
    "service_id from existing services, OAuth scopes, streaming flag, per-principal rate limit in "
    "requests/minute, main request and response fields).",
    "routing": "model_aliases: logical task aliases (e.g. enterprise-chat, enterprise-embedding); "
    "required_capabilities only from: text, streaming, json-schema, tools, vision, audio, "
    "long-context, embeddings; existing_design.endpoints lists each provider's processing region; "
    "primary_provider and fallback_providers only from allowed_target_providers; embedding "
    "aliases have no fallback. routing: eligibility rules, ranking, retry owner, total "
    "max_attempts (1-3), circuit breaker, and stream policy.",
    "budget": "budget: allocations of the monthly hard budget across departments or user groups "
    "as share_percent (sum at most 100, include a reserve), soft-limit alert percent, "
    "per-request token ceiling, per-workflow step ceiling, rationale.",
    "cache": "cache: exact/semantic/provider-prompt/retrieval caching choices with TTLs, a "
    "semantic similarity threshold, bypass conditions, invalidation events, and rationale.",
    "auth": "identity: use the exact scope strings from existing_design.api_contracts for role "
    "permissions and OAuth scopes; no wildcard permissions. IdP, OAuth 2.0/OIDC flows "
    "(authorization_code_pkce for users, "
    "client_credentials via workload identity for services, on_behalf_of for delegated tool "
    "calls when needed), application roles as sets of API scopes, least-privilege service "
    "identities per service ID, extra required claims, tenant mapping, session management.",
    "guard": "guardrails: controls for input, retrieval, tool, execution, output, and audit "
    "stages as applicable, each with owner and enforcement type.",
    "security": "threats: 8-14 STRIDE threats with OWASP LLM 2025 IDs (LLM01:2025..LLM10:2025) "
    "or an empty string, affected service/store IDs, mitigation, owner, residual risk.",
    "observe": "observability: tracing, model analytics, extra correlation IDs, 6-12 SLO-linked "
    "metrics with alerts, dashboards, log retention days, sampling, redaction.",
    "eval": "evaluation: datasets, metrics with targets and methods, cadence, release gates, "
    "and route coverage including fallback routes.",
}


class ProgressReporter(Protocol):
    def step(self, key: str, title: str, status: StepStatus, detail: str = "") -> None: ...

    def message(self, text: str) -> None: ...


class NullReporter:
    def step(self, key: str, title: str, status: StepStatus, detail: str = "") -> None:
        del key, title, status, detail

    def message(self, text: str) -> None:
        del text


@cache
def load_prompt(name: str) -> str:
    return files("archai.resources").joinpath("prompts", name).read_text(encoding="utf-8")


@cache
def load_skill(name: str) -> str:
    text = files("archai.resources").joinpath("skills", name, "SKILL.md").read_text("utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        return parts[2].strip() if len(parts) == 3 else text
    return text


class CallBudget:
    """Thread-safe cap on generation calls and tokens for one run."""

    def __init__(self, max_calls: int, max_tokens: int) -> None:
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self.calls = 0
        self.tokens = 0
        self._lock = threading.Lock()

    def reserve(self) -> None:
        with self._lock:
            if self.calls >= self.max_calls:
                raise ProviderError(
                    f"generation call budget exhausted ({self.max_calls} calls)",
                    kind="budget_exhausted",
                )
            if self.tokens >= self.max_tokens:
                raise ProviderError(
                    f"generation token budget exhausted ({self.max_tokens} tokens)",
                    kind="budget_exhausted",
                )
            self.calls += 1

    def add(self, tokens: int) -> None:
        with self._lock:
            self.tokens += tokens


FAILOVER_KINDS = {
    "rate_limit",
    "server_error",
    "timeout",
    "authentication",
    "permission",
    "configuration",
    "provider_error",
    "truncated_output",
    "malformed_output",
}


@dataclass
class DesignTeam:
    """Role bindings plus designer-side provider failover.

    When a provider fails with a quota, rate-limit, availability, or credential error and another
    configured provider exists, the call is retried once on that provider and the failing
    provider is skipped for the rest of the run.
    """

    bindings: dict[str, RoleBinding]
    factory: Callable[[str, str], ArchitectProvider]
    budget: CallBudget
    reporter: ProgressReporter = field(default_factory=NullReporter)
    calls: list[RoleCallRecord] = field(default_factory=list)
    alternates: dict[str, RoleBinding] = field(default_factory=dict)
    _providers: dict[tuple[str, str], ArchitectProvider] = field(default_factory=dict)
    _unhealthy: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _binding_for(self, role: str) -> RoleBinding:
        binding = self.bindings[role]
        with self._lock:
            alternate = self.alternates.get(binding.provider)
            if (
                binding.provider in self._unhealthy
                and alternate is not None
                and alternate.provider not in self._unhealthy
            ):
                return alternate
        return binding

    def describe(self, role: str) -> str:
        binding = self._binding_for(role)
        return f"{binding.provider} · {binding.model}"

    def models_used(self) -> list[str]:
        with self._lock:
            return sorted({f"{c.provider}:{c.model}" for c in self.calls if c.status == "ok"})

    def source_for(self, step: str, role: str) -> str:
        with self._lock:
            records = [c for c in self.calls if c.step == step and c.status == "ok"]
        if records:
            return f"architect:{records[-1].provider}:{records[-1].model}"
        binding = self._binding_for(role)
        return f"architect:{binding.provider}:{binding.model}"

    def _provider(self, binding: RoleBinding) -> ArchitectProvider:
        key = (binding.provider, binding.model)
        with self._lock:
            if key not in self._providers:
                self._providers[key] = self.factory(binding.provider, binding.model)
            return self._providers[key]

    def call(self, role: str, step: str, prompt: str, output_type: type[T]) -> T:
        binding = self._binding_for(role)
        try:
            return self._attempt(role, step, binding, prompt, output_type)
        except ProviderError as exc:
            alternate = self.alternates.get(binding.provider)
            with self._lock:
                usable = (
                    exc.kind in FAILOVER_KINDS
                    and alternate is not None
                    and alternate.provider not in self._unhealthy
                )
                first = usable and binding.provider not in self._unhealthy
                if usable:
                    self._unhealthy[binding.provider] = exc.kind
            if not usable or alternate is None:
                raise
            if first:
                self.reporter.message(
                    f"{binding.provider} is unavailable ({exc.kind}); switching to "
                    f"{alternate.provider} · {alternate.model} for the rest of this run."
                )
            return self._attempt(role, step, alternate, prompt, output_type)

    def _attempt(
        self, role: str, step: str, binding: RoleBinding, prompt: str, output_type: type[T]
    ) -> T:
        started = time.monotonic()
        try:
            self.budget.reserve()
            result = self._provider(binding).generate(prompt, output_type)
        except ProviderError as exc:
            self._record(
                RoleCallRecord(
                    role=ROLE_NAMES[role],
                    step=step,
                    provider=binding.provider,
                    model=binding.model,
                    status="failed",
                    seconds=round(time.monotonic() - started, 1),
                    error=str(exc)[:300],
                )
            )
            raise
        usage = result.usage
        self.budget.add((usage.input_tokens or 0) + (usage.output_tokens or 0))
        self._record(
            RoleCallRecord(
                role=ROLE_NAMES[role],
                step=step,
                provider=binding.provider,
                model=binding.model,
                status="ok",
                seconds=round(time.monotonic() - started, 1),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        )
        return result.value

    def _record(self, record: RoleCallRecord) -> None:
        with self._lock:
            self.calls.append(record)

    def last_detail(self, step: str) -> str:
        with self._lock:
            records = [item for item in self.calls if item.step == step and item.status == "ok"]
        if not records:
            return ""
        record = records[-1]
        tokens = (record.input_tokens or 0) + (record.output_tokens or 0)
        return f"{record.provider} · {record.model} · {tokens / 1000:.1f}k tok · {record.seconds}s"


# ---------------------------------------------------------------- prompt construction


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _requirements_context(design: EnterpriseDesign) -> dict[str, Any]:
    return design.requirements.model_dump(mode="json", exclude={"evidence"})


def _design_summary(design: EnterpriseDesign) -> dict[str, Any]:
    return {
        "services": [
            {"id": s.id, "name": s.name, "kind": s.kind, "depends_on": s.depends_on}
            for s in design.services
        ],
        "data_stores": [
            {"id": s.id, "kind": s.kind, "purpose": s.purpose} for s in design.data_stores
        ],
        "workflows": [{"id": w.id, "name": w.name} for w in design.workflows],
        "api_contracts": [
            {"method": c.method, "path": c.path, "service_id": c.service_id, "scopes": c.scopes}
            for c in design.api_contracts
        ],
        "endpoints": [
            {"id": e.id, "provider": e.provider, "region": e.region, "modalities": e.modalities}
            for e in design.endpoints
        ],
        "model_aliases": [a.id for a in design.model_aliases],
        "deployment_profile": design.deployment.name if design.deployment else None,
        "capacity": design.capacity.model_dump(mode="json") if design.capacity else None,
    }


def build_prompt(
    role: str,
    task: str,
    context: dict[str, Any],
    output_notes: Iterable[str] = (),
) -> str:
    skills = "\n\n".join(load_skill(name) for name in ROLE_SKILLS.get(role, ()))
    notes = "\n".join(f"- {note}" for note in output_notes)
    return (
        f"# Role\nYou are the {ROLE_NAMES[role]} in ArchAI's five-role architecture team.\n\n"
        f"{task.strip()}\n\n{load_prompt('common.md').strip()}\n\n"
        f"# Domain guidance\n{skills}\n\n"
        f"# Context (untrusted data)\n<untrusted>\n{_compact(context)}\n</untrusted>\n\n"
        + (f"# Output guidance\n{notes}\n\n" if notes else "")
        + "Return only JSON matching the response schema."
    )


def intake_prompt(source: str, data: dict[str, Any]) -> str:
    fields = [
        {
            "field": q.field,
            "question": q.prompt,
            "type": q.kind,
            **({"choices": list(q.choices)} if q.choices else {}),
        }
        for q in QUESTIONS
    ]
    known = {key: value for key, value in data.items() if key not in {"evidence", "conflicts"}}
    return build_prompt(
        "requirements",
        load_prompt("requirements_intake.md"),
        {
            "application_description": source,
            "already_provided": known,
            "interview_fields": fields,
        },
    )


def analyze_requirements(
    team: DesignTeam, source: str, data: dict[str, Any]
) -> RequirementsAnalysis:
    return team.call("requirements", "intake", intake_prompt(source, data), RequirementsAnalysis)


# ---------------------------------------------------------------- supervisor


@dataclass
class SupervisorResult:
    diagnostics: list[ValidationDiagnostic] = field(default_factory=list)
    roles_run: list[str] = field(default_factory=list)
    revision_passes: int = 0


class Supervisor:
    def __init__(
        self,
        design: EnterpriseDesign,
        scope: list[str],
        locks: list[DecisionLock],
        team: DesignTeam | None,
        reporter: ProgressReporter | None = None,
        validator: Callable[[EnterpriseDesign], list[ValidationDiagnostic]] | None = None,
    ) -> None:
        self.design = design
        self.scope = scope
        self.team = team
        self.reporter = reporter or NullReporter()
        self.validator = validator
        self.locked = {lock.component for lock in locks if lock.field_path is None}
        self.result = SupervisorResult()

    # ------------------------------------------------------------------ helpers

    def _active(self, components: Iterable[str]) -> list[str]:
        active = []
        for name in components:
            state = self.design.components.get(name)
            if (
                name in self.scope
                and name not in self.locked
                and state is not None
                and state.status == ComponentStatus.valid
            ):
                active.append(name)
        return active

    def _context(
        self, components: list[str], findings: list[VerificationFinding]
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "project": self.design.project,
            "scope": components,
            "requirements": _requirements_context(self.design),
            "existing_design": _design_summary(self.design),
            "locked_components": sorted(self.locked),
        }
        if self.design.prd:
            context["prd"] = {
                "summary": self.design.prd.summary,
                "goals": self.design.prd.goals,
                "functional_requirements": [
                    f"{item.id}: {item.statement}"
                    for item in self.design.prd.functional_requirements
                ],
            }
        if findings:
            context["verifier_findings_to_fix"] = [
                item.model_dump(mode="json", exclude={"resolved"}) for item in findings
            ]
        return context

    def _fallback(self, step: str, components: list[str], exc: ProviderError) -> None:
        for name in components:
            state = self.design.components.get(name)
            if state is not None:
                state.source = f"{designer.BASELINE_SOURCE} (architect failed: {exc.kind})"
        self.result.diagnostics.append(
            ValidationDiagnostic(
                code="ARCHITECT_ROLE_FALLBACK",
                severity="warning",
                message=f"{STEP_TITLES.get(step, step)}: {exc}. Used the deterministic baseline "
                f"for {', '.join(components)}.",
                component=components[0] if components else None,
            )
        )
        self.reporter.step(
            step, STEP_TITLES.get(step, step), "failed", f"baseline used: {exc.kind}"
        )

    def _generate(
        self, role: str, step: str, components: list[str], context: dict[str, Any]
    ) -> BaseModel | None:
        assert self.team is not None
        model = scoped_proposal_model(role, components)
        notes = [COMPONENT_GUIDANCE[name] for name in components if name in COMPONENT_GUIDANCE]
        notes.append("decisions: 1-3 architecture decision records per designed component.")
        prompt = build_prompt(role, load_prompt(ROLE_PROMPTS[role]), context, notes)
        return self.team.call(role, step, prompt, model)

    def _merge(self, role: str, step: str, proposal: BaseModel, components: list[str]) -> None:
        assert self.team is not None
        source = self.team.source_for(step, role)
        merger = ProposalMerger(self.design, source)
        self.result.diagnostics.extend(merger.merge(proposal, components))
        self.result.roles_run.append(ROLE_NAMES[role])

    # ------------------------------------------------------------------ main flow

    def run(self) -> SupervisorResult:
        if self.team is None:
            return self.result
        self._prd()
        role_scopes = {
            role: self._active(ROLE_COMPONENTS[role]) for role in ("cloud", "api", "security")
        }
        for role in ("cloud", "api", "security"):
            if role_scopes[role]:
                self.reporter.step(role, STEP_TITLES[role], "pending", ROLE_NAMES[role])
        # Sequential hand-offs: services feed API contracts, whose scopes feed identity design.
        for role in ("cloud", "api", "security"):
            if role_scopes[role]:
                self._run_roles({role: role_scopes[role]}, [])
        self.result.diagnostics.extend(enforce_invariants(self.design))
        self._verify(role_scopes)
        return self.result

    def _prd(self) -> None:
        assert self.team is not None
        if not self._active(["requirements"]):
            return
        self.reporter.step("prd", STEP_TITLES["prd"], "running", self.team.describe("requirements"))
        prompt = build_prompt(
            "requirements",
            load_prompt("requirements_prd.md"),
            {"project": self.design.project, "requirements": _requirements_context(self.design)},
        )
        try:
            proposal = self.team.call("requirements", "prd", prompt, PRDProposal)
        except ProviderError as exc:
            if exc.fatal:
                raise
            self._fallback("prd", ["requirements"], exc)
            return
        self.design.prd = PRD(
            summary=proposal.summary,
            problem_statement=proposal.problem_statement,
            goals=proposal.goals[:10],
            non_goals=proposal.non_goals[:8],
            personas=[Persona(name=p.name, needs=p.needs) for p in proposal.personas[:8]],
            journeys=[Journey(name=j.name, steps=j.steps[:10]) for j in proposal.journeys[:6]],
            functional_requirements=[
                RequirementItem(id=item.id, statement=item.statement, priority=item.priority)
                for item in proposal.functional_requirements[:24]
            ],
            non_functional_requirements=[
                NFRItem(id=i.id, category=i.category, statement=i.statement, target=i.target)
                for i in proposal.non_functional_requirements[:20]
            ],
            acceptance_metrics=proposal.acceptance_metrics[:10],
            open_questions=proposal.open_questions[:10],
        )
        state = self.design.components.get("requirements")
        if state is not None:
            state.source = self.team.source_for("prd", "requirements")
        self.result.roles_run.append(ROLE_NAMES["requirements"])
        self.reporter.step("prd", STEP_TITLES["prd"], "done", self.team.last_detail("prd"))

    def _run_roles(
        self,
        role_scopes: dict[str, list[str]],
        findings: list[VerificationFinding],
        step_suffix: str = "",
    ) -> None:
        assert self.team is not None
        contexts = {
            role: self._context(components, findings) for role, components in role_scopes.items()
        }
        for role in role_scopes:
            step = role + step_suffix
            self.reporter.step(step, STEP_TITLES[role] + step_suffix, "running", ROLE_NAMES[role])
        with ThreadPoolExecutor(max_workers=max(1, len(role_scopes))) as pool:
            futures = {
                role: pool.submit(
                    self._generate, role, role + step_suffix, components, contexts[role]
                )
                for role, components in role_scopes.items()
            }
            outcomes: dict[str, BaseModel | ProviderError] = {}
            for role, future in futures.items():
                try:
                    proposal = future.result()
                    if proposal is not None:
                        outcomes[role] = proposal
                except ProviderError as exc:
                    outcomes[role] = exc
        fatal = next(
            (item for item in outcomes.values() if isinstance(item, ProviderError) and item.fatal),
            None,
        )
        if fatal is not None:
            raise fatal
        for role, components in role_scopes.items():
            step = role + step_suffix
            outcome = outcomes.get(role)
            if isinstance(outcome, ProviderError):
                self._fallback(step, components, outcome)
            elif outcome is not None:
                self._merge(role, step, outcome, components)
                self.reporter.step(
                    step, STEP_TITLES[role] + step_suffix, "done", self.team.last_detail(step)
                )

    def _verify(self, role_scopes: dict[str, list[str]]) -> None:
        assert self.team is not None
        designed = [name for components in role_scopes.values() for name in components]
        if not designed:
            return
        previous: list[VerificationFinding] = []
        for attempt in range(3):
            step = "verify" if attempt == 0 else f"verify-{attempt}"
            title = STEP_TITLES["verify"] + ("" if attempt == 0 else f" (pass {attempt + 1})")
            self.reporter.step(step, title, "running", self.team.describe("verifier"))
            deterministic = self.validator(self.design) if self.validator else []
            context = {
                "scope": designed,
                "requirements": _requirements_context(self.design),
                "design": self.design.model_dump(
                    mode="json",
                    exclude={"requirements", "components", "verification", "costs"},
                ),
                "deterministic_diagnostics": [
                    item.model_dump(mode="json") for item in deterministic
                ],
            }
            prompt = build_prompt("verifier", load_prompt("verifier.md"), context)
            try:
                report = self.team.call("verifier", step, prompt, VerificationReport)
            except ProviderError as exc:
                if exc.fatal:
                    raise
                self.reporter.step(step, title, "failed", f"skipped: {exc.kind}")
                self.result.diagnostics.append(
                    ValidationDiagnostic(
                        code="VERIFIER_UNAVAILABLE",
                        severity="warning",
                        message=f"Model verification skipped: {exc}",
                    )
                )
                return
            findings = [
                VerificationFinding(
                    severity=item.severity,
                    component=item.component if item.component in designed else designed[0],
                    issue=item.issue,
                    recommendation=item.recommendation,
                )
                for item in report.findings[:30]
            ]
            blocking = [item for item in findings if item.severity == "blocking"]
            self.design.verification_summary = report.summary
            self.design.verification = [*previous, *findings]
            detail = self.team.last_detail(step)
            self.reporter.step(
                step, title, "done", f"{len(blocking)} blocking, {len(findings)} total · {detail}"
            )
            if not blocking or attempt == 2:
                if blocking:
                    for item in blocking:
                        self.result.diagnostics.append(
                            ValidationDiagnostic(
                                code="VERIFIER_UNRESOLVED",
                                severity="warning",
                                component=item.component,
                                message=f"{item.issue} → {item.recommendation}",
                            )
                        )
                return
            revise: dict[str, list[str]] = {}
            for role, components in role_scopes.items():
                targeted = [
                    name for name in components if any(f.component == name for f in blocking)
                ]
                if targeted:
                    revise[role] = targeted
            if not revise:
                return
            self.result.revision_passes += 1
            suffix = f" · revision {self.result.revision_passes}"
            self._run_roles(revise, blocking, suffix)
            self.result.diagnostics.extend(enforce_invariants(self.design))
            revised = {name for names in revise.values() for name in names}
            previous = [
                *previous,
                *[
                    item.model_copy(
                        update={
                            "resolved": item.component in revised,
                            "severity": "info" if item.component in revised else item.severity,
                        }
                    )
                    for item in blocking
                ],
            ]
