from __future__ import annotations

from collections.abc import Sequence

import pytest

from archai.errors import InterviewPaused
from archai.interview.questions import QUESTION_BY_FIELD, missing_questions, parse_answer
from archai.interview.session import InterviewSession, Suggestion


class ScriptedIO:
    """Feeds answers in order and records what the interview showed."""

    def __init__(self, answers: Sequence[str], review: Sequence[str] = ("",)) -> None:
        self.answers = list(answers)
        self.reviews = list(review)
        self.asked: list[str] = []
        self.errors: list[str] = []
        self.defaults: dict[str, str | None] = {}
        self.hints: dict[str, str | None] = {}

    def section(self, title: str) -> None:
        del title

    def ask(self, *, label, prompt, help_text, choices, default, hint, critical) -> str:
        del label, help_text, choices, critical
        self.asked.append(prompt)
        self.defaults[prompt] = default
        self.hints[prompt] = hint
        if not self.answers:
            return "save"
        return self.answers.pop(0)

    def info(self, text: str) -> None:
        del text

    def error(self, text: str) -> None:
        self.errors.append(text)

    def review(self, rows) -> str:
        assert rows
        return self.reviews.pop(0) if self.reviews else ""


COMPLETE = {
    "idea": "Support copilot",
    "business_outcome": "Faster answers",
    "users": ["agents"],
    "archetypes": ["enterprise-rag"],
    "region": "westeurope",
    "data_residency": ["westeurope"],
    "tenant_isolation": "multi",
    "allowed_target_providers": ["Azure OpenAI"],
    "tool_side_effects": "approval",
    "avg_rps": "1",
    "peak_rps": "4",
    "input_tokens": 2000,
    "output_tokens": 400,
    "model_calls_per_request": "1",
    "monthly_budget": "1000",
    "currency": "EUR",
    "availability_target": "99.9",
}
OPTIONAL = {
    "user_roles": ["agent"],
    "client_channels": ["web app"],
    "data_sources": ["SharePoint"],
    "documents_per_day": 100,
    "topology": "single-cloud",
    "profile": "azure-aca",
    "existing_services": ["none"],
    "identity_provider": "Entra ID",
    "data_classification": "confidential",
    "compliance": ["GDPR"],
    "latency_p95_ms": 8000,
    "rto_minutes": 240,
    "rpo_minutes": 60,
}
FULL = {**COMPLETE, **OPTIONAL}


def test_parse_answers_by_type():
    archetypes = QUESTION_BY_FIELD["archetypes"]
    assert parse_answer(archetypes, "1, tool-using-agent") == ["enterprise-rag", "tool-using-agent"]
    assert parse_answer(QUESTION_BY_FIELD["monthly_budget"], "€25,000") == "25000"
    assert parse_answer(QUESTION_BY_FIELD["input_tokens"], "2,500") == 2500
    assert parse_answer(QUESTION_BY_FIELD["currency"], "eur") == "EUR"
    assert parse_answer(QUESTION_BY_FIELD["compliance"], "none") == []
    with pytest.raises(ValueError):
        parse_answer(QUESTION_BY_FIELD["tool_side_effects"], "sometimes")
    with pytest.raises(ValueError, match="at least the average"):
        parse_answer(QUESTION_BY_FIELD["peak_rps"], "1", {"avg_rps": "2"})


def test_only_missing_and_applicable_questions_are_asked():
    data = dict(COMPLETE)
    del data["monthly_budget"]
    data["archetypes"] = ["summarization"]
    fields = {question.field for question in missing_questions(data)}
    assert "monthly_budget" in fields
    assert "business_outcome" not in fields
    assert "data_sources" not in fields  # only asked for retrieval workloads
    data["archetypes"] = ["enterprise-rag"]
    assert "data_sources" in {question.field for question in missing_questions(data)}


def test_session_back_skip_validation_suggestions_and_persistence():
    data = {"idea": "Support copilot"}
    saved: list[dict] = []
    answers = [
        "Faster answers",  # business outcome
        "back",  # go back to business outcome
        "Faster grounded answers",
        "agents, approvers",  # users
        "skip",  # roles (optional)
        "",  # channels: accept default
        "",  # archetypes: accept AI suggestion
        "maybe",  # tool side effects: invalid
        "approval",
    ]
    io = ScriptedIO(answers)
    session = InterviewSession(
        io,
        data,
        suggestions={"archetypes": Suggestion(["enterprise-rag"], "from your description")},
        clarifying_questions=["Which ticketing system executes refunds?"],
        persist=saved.append,
    )
    with pytest.raises(InterviewPaused):
        session.run()
    assert data["business_outcome"] == "Faster grounded answers"
    assert data["users"] == ["agents", "approvers"]
    assert data["user_roles"] == []
    assert data["client_channels"] == ["web app"]
    assert data["archetypes"] == ["enterprise-rag"]
    assert data["tool_side_effects"] == "approval"
    assert any("choose one of" in error for error in io.errors)
    assert saved and saved[-1]["tool_side_effects"] == "approval"
    archetype_prompt = QUESTION_BY_FIELD["archetypes"].prompt
    assert io.hints[archetype_prompt] == "AI suggestion — from your description"
    evidence = {item["location"]: item for item in data["evidence"]}
    assert evidence["REQ-ARCHETYPES"]["rationale"] == "confirmed AI suggestion in guided interview"


def test_critical_questions_cannot_be_skipped_and_clarifications_are_recorded():
    data = dict(FULL)
    del data["tenant_isolation"]
    io = ScriptedIO(["skip", "", "single", "ServiceNow", "Refund faster"], review=["1", ""])
    session = InterviewSession(
        io, data, clarifying_questions=["Which ticketing system executes refunds?"]
    )
    result = session.run()
    assert result["tenant_isolation"] == "single"
    assert sum("required" in error for error in io.errors) == 2
    assert result["clarifications"] == [
        {"question": "Which ticketing system executes refunds?", "answer": "ServiceNow"}
    ]
    assert result["business_outcome"] == "Refund faster"  # edited from the review table


def test_conflicts_are_resolved_interactively():
    data = dict(FULL)
    data["conflicts"] = [
        {"id": "c", "field": "region", "values": ["westeurope", "eastus"], "message": "m"}
    ]
    io = ScriptedIO(["1"])
    result = InterviewSession(io, data, review=False).run()
    assert result["region"] == "westeurope"
    assert result["conflicts"] == []
