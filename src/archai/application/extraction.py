"""Turn the requirements architect's analysis into interview defaults or evidence-backed facts."""

from __future__ import annotations

from typing import Any

from archai.interview.questions import QUESTION_BY_FIELD, is_missing, parse_answer
from archai.interview.session import Suggestion
from archai.schemas.proposals import RequirementsAnalysis

# Facts that may be taken from prose without a prompt when an exact supporting quote exists.
QUOTABLE_FIELDS = {
    "business_outcome",
    "users",
    "archetypes",
    "user_roles",
    "client_channels",
    "integrations",
    "data_sources",
    "compliance",
}
# Noncritical defaults that --allow-assumptions may record as explicit assumptions.
ASSUMABLE_FIELDS = {
    "identity_provider",
    "data_classification",
    "latency_p95_ms",
    "rto_minutes",
    "rpo_minutes",
    "documents_per_day",
}


def interview_suggestions(
    analysis: RequirementsAnalysis, data: dict[str, Any]
) -> dict[str, Suggestion]:
    """Typed suggestions for unanswered interview fields; the user confirms each one."""
    result: dict[str, Suggestion] = {}
    for item in analysis.suggestions:
        question = QUESTION_BY_FIELD.get(item.field)
        if question is None or not is_missing(data.get(question.field)):
            continue
        try:
            value = parse_answer(question, item.value, data)
        except ValueError:
            continue
        rationale = item.rationale.strip() or "recommended by the requirements architect"
        if item.source_quote.strip():
            rationale = f"from your description: “{item.source_quote.strip()[:120]}”"
        result[question.field] = Suggestion(value=value, rationale=rationale[:200])
    return result


def apply_quoted_suggestions(
    analysis: RequirementsAnalysis,
    data: dict[str, Any],
    source: str,
    allow_assumptions: bool = False,
) -> dict[str, Any]:
    """Non-interactive use: accept only quote-supported facts and permitted assumptions."""
    result = dict(data)
    evidence = list(result.get("evidence", []))
    assumptions = list(result.get("assumptions", []))
    for item in analysis.suggestions:
        question = QUESTION_BY_FIELD.get(item.field)
        if question is None or not is_missing(result.get(question.field)):
            continue
        quote = item.source_quote.strip()
        if question.field in QUOTABLE_FIELDS:
            if not quote or quote not in source or not item.value.strip():
                continue
            try:
                value = parse_answer(question, item.value, result)
            except ValueError:
                continue
            values = value if isinstance(value, list) else [value]
            supported = [entry for entry in values if str(entry).casefold() in quote.casefold()]
            if not supported:
                continue
            result[question.field] = supported if isinstance(value, list) else supported[0]
            evidence.append(
                {
                    "source_id": "architect-input",
                    "location": "quoted source text",
                    "value": quote,
                    "provenance": "inferred",
                    "rationale": f"Model extraction of {question.field}; verify before use",
                }
            )
        elif allow_assumptions and question.field in ASSUMABLE_FIELDS:
            try:
                value = parse_answer(question, item.value, result)
            except ValueError:
                continue
            result[question.field] = value
            assumptions.append(
                {
                    "id": f"assumption-{question.field.replace('_', '-')}",
                    "statement": f"{question.field} = {value}",
                    "rationale": item.rationale.strip()[:300] or "architect recommendation",
                    "critical": False,
                }
            )
            evidence.append(
                {
                    "source_id": "architect-input",
                    "location": question.id,
                    "value": value,
                    "provenance": "assumed",
                    "rationale": "noncritical default permitted by --allow-assumptions",
                }
            )
    result["evidence"] = evidence
    result["assumptions"] = assumptions
    return result
