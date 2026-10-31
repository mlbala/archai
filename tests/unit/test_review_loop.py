from __future__ import annotations

from conftest import FakeArchitect
from test_closure import requirements
from test_supervisor import finding, install, run

from archai.application import service
from archai.application.acceptance import acceptance_checklist
from archai.application.checks import design_checks
from archai.application.derive import derive_service_grants, derive_signin_scopes, queue_sentence
from archai.application.designer import apply_scope
from archai.application.merge import enforce_invariants
from archai.application.service import auto_scope
from archai.schemas.models import PRD, Journey, RequirementItem, Workflow


def baseline():
    design = apply_scope(None, "sample", requirements(), auto_scope(), [])
    enforce_invariants(design)
    return design


# ------------------------------------------------------------------ derived facts


def test_every_call_and_store_gets_a_grant_and_sign_in_covers_role_scopes():
    design = baseline()
    worker = next(service for service in design.services if service.kind == "worker")
    worker.depends_on.append("svc-retrieval")
    identity = next(
        item for item in design.identity_policy.service_identities if item.service_id == worker.id
    )
    identity.grants = ["queue receive"]
    flow = next(
        item
        for item in design.identity_policy.oauth_flows
        if item.grant_type == "authorization_code_pkce"
    )
    flow.scopes = []

    assert derive_service_grants(design)
    assert derive_signin_scopes(design)

    assert "queue receive" in identity.grants  # nothing the role wrote is removed
    assert "svc-retrieval: call its private API" in identity.grants
    role_scopes = {p for role in design.identity_policy.roles for p in role.permissions}
    operation_scopes = {s for contract in design.api_contracts for s in contract.scopes}
    assert role_scopes & operation_scopes <= set(flow.scopes)
    assert not derive_service_grants(design)  # idempotent


def test_the_retry_policy_states_the_queue_limit_and_a_different_count_is_reported():
    design = baseline()
    assert design.queue_policy is not None and design.resilience is not None
    assert design.resilience.retry_policy.startswith(queue_sentence(design) or "")
    assert not [item for item in design_checks(design) if item.id == "P-RETRY_COUNT"]
    design.resilience.retry_policy += " Jobs get three delayed SQS deliveries before parking."
    found = [item for item in design_checks(design) if item.id == "P-RETRY_COUNT"]
    assert found and found[0].components == ["resilience"]
    assert "states 3 queue deliveries" in found[0].issue


def test_a_workflow_step_naming_a_missing_operation_is_reported():
    design = baseline()
    design.workflows.append(
        Workflow(
            id="workflow-publish",
            name="Publish",
            steps=[
                "Admin calls GET /v1/jobs/by-source-version on svc-app",
                "svc-app writes store-state",
            ],
            hitl_required=False,
        )
    )
    found = [item for item in design_checks(design) if item.id.startswith("P-WORKFLOW")]
    assert len(found) == 1
    assert "/v1/jobs/by-source-version" in found[0].issue
    assert "svc-app" not in found[0].issue.split("names", 1)[1]  # existing ids are fine
    assert found[0].components == ["workflow", "api"]


def test_a_guardrail_owned_by_a_team_name_is_only_a_warning():
    design = baseline()
    design.guardrails[0].owner = "platform team"
    found = [item for item in design_checks(design) if item.id == "P-GUARD_OWNER"]
    assert found and found[0].severity == "warning"


# ------------------------------------------------------------------ acceptance checklist


def test_the_checklist_is_the_same_questions_every_time():
    design = baseline()
    design.prd = PRD(
        problem_statement="Agents wait for answers.",
        functional_requirements=[
            RequirementItem(id="FR-1", statement="Agents get cited answers.", priority="must"),
            RequirementItem(id="FR-2", statement="Nice extras.", priority="could"),
        ],
        journeys=[Journey(name="Ask a question", steps=["ask", "read the cited answer"])],
    )
    first = acceptance_checklist(design, auto_scope())
    second = acceptance_checklist(design, auto_scope())
    assert [item.id for item in first] == [item.id for item in second]
    ids = {item.id for item in first}
    assert {"C-R-RESIDENCY", "C-R-BUDGET", "C-R-SIDE-EFFECTS", "C-FR-1", "C-J1"} <= ids
    assert "C-FR-2" not in ids  # only must-have requirements are acceptance criteria
    # A component command checks only the criteria its components touch.
    api_only = {item.id for item in acceptance_checklist(design, ["api"])}
    assert "C-FR-1" not in api_only and "C-R-IDENTITY" in api_only


def checklist_verifier(results_by_pass):
    """A fake verifier that answers the checklist differently on each pass."""

    class Verifier(FakeArchitect):
        def __init__(self) -> None:
            super().__init__({"VerificationReport": {"findings": [], "decisions_needed": []}})
            self.passes = 0

        def generate(self, prompt, output_type):
            if output_type.__name__ == "VerificationReport":
                results = results_by_pass[min(self.passes, len(results_by_pass) - 1)]
                self.overrides["VerificationReport"]["criteria"] = results
                self.passes += 1
            return super().generate(prompt, output_type)

    return Verifier()


def result(identifier, status, fields=()):
    return {
        "id": identifier,
        "status": status,
        "evidence": "api-chat has no citation download" if status == "fail" else "ok",
        "fields": list(fields),
        "recommendation": "Add a download operation" if status == "fail" else "",
    }


def test_a_failed_criterion_is_repaired_and_the_design_completes_when_it_passes(
    tmp_path, monkeypatch
):
    fake = checklist_verifier(
        [
            [result("C-R-BUDGET", "fail", ["budget_policy.allocations"])],
            [result("C-R-BUDGET", "pass")],
        ]
    )
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    prompts = [prompt for name, prompt in fake.prompts if name == "VerificationReport"]
    assert '"acceptance_criteria":[{"id":"C-R-RESIDENCY"' in prompts[0]
    # The second pass asks only the failed criterion and those near the changed components.
    assert '"id":"C-R-BUDGET"' in prompts[1]
    assert prompts[1].count('"id":"C-R-') < prompts[0].count('"id":"C-R-')
    repair = dict(fake.prompts)["ApiBudgetProposal"]
    assert "Acceptance C-R-BUDGET not met" in repair
    design = store.load_design(revision)
    budget = next(item for item in design.acceptance if item.id == "C-R-BUDGET")
    assert budget.status == "pass"
    assert store.load_manifest(revision).project_complete is True


def test_a_new_observation_about_an_unchanged_part_does_not_block_after_the_first_review(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ARCHAI_MAX_REPAIR_PASSES", "2")
    first = finding("api", "Approval endpoint missing", "Add one")
    late = finding("cache", "Cache TTL could be shorter", "Shorten it", fields=["cache_policy"])

    class Verifier(FakeArchitect):
        def __init__(self) -> None:
            super().__init__({"VerificationReport": {"findings": [first]}})
            self.passes = 0

        def generate(self, prompt, output_type):
            if output_type.__name__ == "VerificationReport":
                self.passes += 1
                if self.passes > 1:
                    self.overrides["VerificationReport"] = {"findings": [late]}
            return super().generate(prompt, output_type)

    fake = Verifier()
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    design = store.load_design(revision)
    cache = [item for item in design.verification if "Cache TTL" in item.issue]
    assert cache and cache[0].severity == "warning"
    assert "ApiCacheProposal" not in [name for name, _ in fake.prompts]
    codes = {item.code for item in store.load_manifest(revision).diagnostics}
    assert "VERIFIER_LATE_FINDING" in codes


# ------------------------------------------------------------------ decisions for the user

DECISION = {
    "question": "May managers see country-restricted policies of other countries?",
    "why": "It changes the retrieval filter and the cache key.",
    "options": ["No, own country only", "Yes, all countries"],
    "components": ["rag", "cache"],
}


def test_a_business_decision_is_recorded_not_looped_on(tmp_path, monkeypatch):
    fake = FakeArchitect({"VerificationReport": {"findings": [], "decisions_needed": [DECISION]}})
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    calls = [name for name, _ in fake.prompts]
    assert calls.count("VerificationReport") == 1  # no repair round for a question
    design = store.load_design(revision)
    assert [item.question for item in design.open_decisions] == [DECISION["question"]]
    assert design.open_decisions[0].answer is None


def test_an_answered_decision_becomes_a_clarification_and_is_applied(tmp_path, monkeypatch):
    fake = FakeArchitect({"VerificationReport": {"findings": [], "decisions_needed": [DECISION]}})
    install(monkeypatch, fake)
    asked = []

    class Person:
        def interview(self, data, **kwargs):
            return data

        def fix(self, data, fields, reason, persist):
            return data

        def decide(self, decisions):
            asked.extend(decisions)
            return {decisions[0].id: "No, own country only"}

    store, revision = run(tmp_path, service.auto_scope(), interviewer=Person())
    assert [item.question for item in asked] == [DECISION["question"]]
    calls = [name for name, _ in fake.prompts]
    assert "CloudRagProposal" in calls  # the owners of the answer's components apply it
    repair = dict(fake.prompts)["CloudRagProposal"]
    assert "Stakeholder decision D1" in repair and "No, own country only" in repair
    design = store.load_design(revision)
    assert design.open_decisions[0].answer == "No, own country only"
    assert any(item.answer == "No, own country only" for item in design.requirements.clarifications)


def test_a_criterion_still_failing_after_one_repair_goes_to_every_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHAI_MAX_REPAIR_PASSES", "2")
    failing = result("C-R-IDENTITY", "fail", ["api_contracts"])
    fake = checklist_verifier([[failing], [failing], [failing]])
    install(monkeypatch, fake)
    run(tmp_path, service.auto_scope())
    calls = [name for name, _ in fake.prompts]
    first_review, second_review = [
        index for index, name in enumerate(calls) if name == "VerificationReport"
    ][:2]
    first_round = calls[first_review:second_review]
    second_round = calls[second_review:]
    assert "ApiApiProposal" in first_round and "SecurityAuthProposal" not in first_round
    # The second attempt involves the identity owner too (C-R-IDENTITY covers auth and api).
    assert "SecurityAuthProposal" in second_round


def test_a_passed_criterion_does_not_flip_for_a_part_that_did_not_change(tmp_path, monkeypatch):
    fake = checklist_verifier(
        [
            [
                result("C-R-IDENTITY", "pass"),
                # Repairing this touches the API, so C-R-IDENTITY (auth, api) is asked again.
                result("C-R-BUDGET", "fail", ["api_contracts"]),
            ],
            [
                result("C-R-IDENTITY", "fail", ["cache_policy.bypass_conditions"]),
                result("C-R-BUDGET", "pass"),
            ],
        ]
    )
    install(monkeypatch, fake)
    store, revision = run(tmp_path, service.auto_scope())
    design = store.load_design(revision)
    identity = next(item for item in design.acceptance if item.id == "C-R-IDENTITY")
    assert identity.status == "pass"
    codes = {item.code for item in store.load_manifest(revision).diagnostics}
    assert "CRITERION_KEPT" in codes
    second = [prompt for name, prompt in fake.prompts if name == "VerificationReport"][1]
    assert '"id":"C-R-IDENTITY"' in second  # it was asked again, and the flip was refused


def test_answers_add_to_saved_clarifications():
    from archai.application.service import merge_clarifications

    saved = [{"question": "Who may see restricted policies?", "answer": "Managers only"}]
    added = [
        {"question": "Who may see  restricted policies?", "answer": "Managers and HR"},
        {"question": "Which baseline?", "answer": ""},
        {"question": "Which region?", "answer": "westeurope"},
    ]
    merged = merge_clarifications(saved, added)
    assert merged == [
        {"question": "Who may see restricted policies?", "answer": "Managers and HR"},
        {"question": "Which region?", "answer": "westeurope"},
    ]


def test_the_terminal_asks_each_decision_and_maps_option_numbers(monkeypatch):
    from rich.console import Console

    from archai.schemas.models import OpenDecision
    from archai.ui import RichInterviewer

    replies = iter(["2", "", "Only HR owners may publish"])
    monkeypatch.setattr("archai.ui.Prompt.ask", lambda *args, **kwargs: next(replies))

    class Progress:
        def __init__(self) -> None:
            self.events: list[str] = []

        def pause(self) -> None:
            self.events.append("pause")

        def resume(self) -> None:
            self.events.append("resume")

    progress = Progress()
    console = Console(record=True, width=120)
    decisions = [
        OpenDecision(
            id="D1", question="Which baseline?", why="Sets the metric.", options=["A", "B"]
        ),
        OpenDecision(id="D2", question="Which region for backups?", why="Residency."),
        OpenDecision(id="D3", question="Who may publish?", why="Ingestion trigger."),
    ]
    answers = RichInterviewer(console, progress).decide(decisions)  # type: ignore[arg-type]
    assert answers == {"D1": "B", "D3": "Only HR owners may publish"}  # Enter leaves D2 open
    assert progress.events == ["pause", "resume"]  # the live progress view steps aside
    shown = console.export_text()
    assert "Decisions for you" in shown and "Which baseline?" in shown and "1) A" in shown


def test_only_an_answers_change_revises_the_last_revision():
    from archai.application.service import answers_to_apply
    from archai.schemas.models import Clarification, OpenDecision

    design = baseline()
    design.open_decisions = [
        OpenDecision(id="D1", question="Which baseline?", why="Metric.", components=["eval"])
    ]
    scope = auto_scope()
    answered = design.requirements.model_copy(deep=True)
    answered.clarifications = [
        *answered.clarifications,
        Clarification(question="Which baseline?", answer="Last quarter"),
    ]
    applied = answers_to_apply(design, answered, scope)
    assert applied is not None
    assert [(item.id, item.answer, item.components) for item in applied] == [
        ("D1", "Last quarter", ["eval"])
    ]
    moved = answered.model_copy(update={"region": "northeurope"})
    assert answers_to_apply(design, moved, scope) is None  # a real change designs again
    assert answers_to_apply(design, design.requirements, scope) is None  # nothing new
    assert answers_to_apply(design, answered, ["api"]) is None  # component commands as before


def test_the_gateway_calls_every_service_whose_operation_it_publishes():
    from archai.application.derive import derive_gateway_calls

    design = baseline()
    gateway = next(service for service in design.services if service.kind == "gateway")
    observe = next(service for service in design.services if service.kind == "operations")
    design.api_contracts[0].service_id = observe.id
    gateway.depends_on = [item for item in gateway.depends_on if item != observe.id]
    assert derive_gateway_calls(design)
    assert observe.id in gateway.depends_on
    assert not derive_gateway_calls(design)


def test_an_update_does_not_ask_again_what_the_last_revision_confirmed():
    from archai.interview.session import InterviewSession

    data = baseline().requirements.model_dump(mode="json")
    data["existing_services"] = []
    asked = InterviewSession(object(), dict(data), review=False)  # type: ignore[arg-type]
    assert "existing_services" in asked.targets
    confirmed = InterviewSession(
        object(),  # type: ignore[arg-type]
        dict(data),
        review=False,
        confirmed=frozenset(data),
    )
    assert "existing_services" not in confirmed.targets


def test_a_role_sets_how_an_operation_is_authenticated():
    from archai.application.merge import ProposalMerger
    from archai.schemas.proposals import scoped_proposal_model

    design = baseline()
    app = next(service for service in design.services if service.kind == "application")
    contract = {
        "method": "POST",
        "summary": "Teams messages",
        "service_id": app.id,
        "scopes": [],
        "streaming": False,
        "rate_limit_rpm": 600,
        "request_fields": [],
        "response_fields": [],
    }
    proposal = scoped_proposal_model("api", ["api"]).model_validate(
        {
            "api_contracts": [
                {
                    **contract,
                    "id": "api-teams",
                    "path": "/api/teams/messages",
                    "auth": "Bot Framework token validation",
                },
                {**contract, "id": "api-chat", "path": "/v1/chat", "auth": ""},
            ],
            "decisions": [],
        }
    )
    ProposalMerger(design, "architect:test:model").merge(proposal, ["api"])
    by_id = {item.id: item for item in design.api_contracts}
    assert by_id["api-teams"].auth == "Bot Framework token validation"
    assert by_id["api-chat"].auth.startswith("OIDC bearer token")


def test_guardrail_owner_words_become_service_ids():
    from archai.application.derive import derive_guard_owners

    design = baseline()
    design.guardrails[0].owner = "platform"
    design.guardrails[1].owner = "workflow"
    assert derive_guard_owners(design)
    kinds = {service.id: service.kind for service in design.services}
    assert kinds[design.guardrails[0].owner] == "operations"
    assert kinds[design.guardrails[1].owner] in {"application", "orchestration"}
