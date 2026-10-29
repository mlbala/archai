"""Resumable guided interview. Terminal rendering is injected through :class:`InterviewIO`."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from archai.errors import InterviewPaused
from archai.interview.exclusions import (
    QUESTION_COMPONENT,
    exclusion_targets,
    normalize_excluded,
)
from archai.interview.inference import best_answer
from archai.interview.questions import (
    QUESTION_BY_FIELD,
    QUESTIONS,
    Question,
    field_unanswered,
    format_value,
    is_missing,
    parse_answer,
)

BACK_WORDS = {"back", "b", "<"}
HELP_WORDS = {"?", "help", "h"}
SKIP_WORDS = {"skip", "-"}
EXIT_WORDS = {"exit", "quit", "save", "q"}
UNDECIDED_WORDS = {"none", "n/a", "na"}
_BARE_EXCLUSION = re.compile(
    r"^(?:i |we )?(?:don'?t|do not) need(?: it| this| that)?$"
    r"|^not required$|^not needed$|^excluded$|^exclude(?: it)?$|^no need$",
    re.IGNORECASE,
)
COMMAND_HELP = (
    "Commands: Enter or none = best fit from the project · back · skip (optional only) · "
    "? help · save = exit"
)


class InterviewIO(Protocol):
    def section(self, title: str) -> None: ...

    def ask(
        self,
        *,
        label: str,
        prompt: str,
        help_text: str,
        choices: Sequence[str],
        default: str | None,
        hint: str | None,
        critical: bool,
    ) -> str: ...

    def info(self, text: str) -> None: ...

    def error(self, text: str) -> None: ...

    def review(self, rows: list[tuple[str, str, str, str]]) -> str: ...


@dataclass(frozen=True)
class Suggestion:
    value: Any
    rationale: str


class _Back(Exception):
    pass


_UNRESOLVED = object()


def field_label(question: Question) -> str:
    return question.field.replace("_", " ").capitalize()


class InterviewSession:
    def __init__(
        self,
        io: InterviewIO,
        data: dict[str, Any],
        *,
        suggestions: dict[str, Suggestion] | None = None,
        clarifying_questions: list[str] | None = None,
        persist: Callable[[dict[str, Any]], None] | None = None,
        review: bool = True,
    ) -> None:
        self.io = io
        self.data = data
        self.suggestions = suggestions or {}
        self.clarifying = [item for item in (clarifying_questions or []) if item.strip()][:6]
        self.persist = persist or (lambda value: None)
        self.review_enabled = review
        self.targets = {
            question.field
            for question in QUESTIONS
            if field_unanswered(question, data) or question.field in self.suggestions
        }
        answered = {
            str(item.get("question"))
            for item in data.get("clarifications") or []
            if isinstance(item, dict)
        }
        self.clarifying = [item for item in self.clarifying if item not in answered]

    # ------------------------------------------------------------------ public API

    def run(self) -> dict[str, Any]:
        self._resolve_conflicts()
        items = self._items()
        if items:
            self.io.info(
                f"{len(items)} question(s) to answer. {COMMAND_HELP}. Progress is saved after "
                "every answer."
            )
        index = 0
        history: list[int] = []
        current_group: str | None = None
        while index < len(items):
            item = items[index]
            group = item.group if isinstance(item, Question) else "Architect's clarifying questions"
            if group != current_group:
                self.io.section(group)
                current_group = group
            try:
                if isinstance(item, Question):
                    self._ask_question(item, f"{index + 1}/{len(items)}")
                else:
                    self._ask_clarification(item, f"{index + 1}/{len(items)}")
            except _Back:
                if history:
                    index = history.pop()
                    current_group = None
                else:
                    self.io.info("Already at the first question.")
                continue
            history.append(index)
            index += 1
            items = self._items()
        if self.review_enabled:
            self._review()
        return self.data

    def reask(self, fields: list[str], reason: str) -> dict[str, Any]:
        """Ask specific questions again, for example after a cross-field validation error."""
        self.io.error(reason)
        for name in fields:
            question = QUESTION_BY_FIELD.get(name)
            if question is not None:
                self.io.section(question.group)
                self._ask_question(question, "fix", allow_back=False)
        return self.data

    # ------------------------------------------------------------------ internals

    def _items(self) -> list[Question | str]:
        questions: list[Question | str] = [
            question
            for question in QUESTIONS
            if question.field in self.targets and question.applies(self.data)
        ]
        return [*questions, *self.clarifying]

    def _save(self) -> None:
        self.persist(dict(self.data))

    def _pause(self) -> None:
        self._save()
        raise InterviewPaused("Interview saved; resume to continue answering.")

    def _default_for(self, question: Question) -> tuple[Any, str | None]:
        if question.field in self.suggestions:
            suggestion = self.suggestions[question.field]
            return suggestion.value, f"AI suggestion — {suggestion.rationale}"
        current = self.data.get(question.field)
        if not is_missing(current):
            return current, None
        chosen = best_answer(question, self.data)
        if chosen is not None:
            value, rationale = chosen
            if not is_missing(value):
                return value, f"Best fit — {rationale}"
        return None, None

    def _ask_question(self, question: Question, label: str, allow_back: bool = True) -> None:
        while True:
            default, hint = self._default_for(question)
            default_text = None if is_missing(default) else format_value(default)
            raw = self.io.ask(
                label=label,
                prompt=question.prompt,
                help_text=question.help,
                choices=question.choices,
                default=default_text,
                hint=hint,
                critical=question.critical,
            ).strip()
            command = raw.lower()
            if command in BACK_WORDS and allow_back:
                raise _Back()
            if command in HELP_WORDS:
                self.io.info(f"{question.help}\n{COMMAND_HELP}")
                continue
            if command in EXIT_WORDS:
                self._pause()
            if command in SKIP_WORDS:
                if question.critical:
                    self.io.error("This answer is required for a safe design.")
                    continue
                self._store_blank(question)
                return
            if question.field == "excluded_components" and command in {"none", "not required"}:
                self._keep_optional_parts(question)
                return
            related = QUESTION_COMPONENT.get(question.field)
            if related is not None and _BARE_EXCLUSION.match(raw):
                self._exclude([related])
                self._finish_exclusion(question)
                return
            targets = exclusion_targets(raw)
            if targets:
                self._exclude(targets)
                if question.field == "excluded_components" or (
                    related is not None and related in targets
                ):
                    self._finish_exclusion(question)
                    return
                self.io.info(
                    "Left out of the design: "
                    + ", ".join(targets)
                    + ". This question still needs an answer."
                )
                continue
            deferred = command in UNDECIDED_WORDS
            accept_shown = (not raw) or (default_text is not None and raw == default_text)
            if deferred or accept_shown:
                value, rationale = self._deferred_value(question, default, hint, deferred)
                if value is _UNRESOLVED:
                    if question.critical:
                        self.io.error(
                            "This answer is required. Type 'save' to stop and resume later."
                        )
                        continue
                    self._store_blank(question)
                    return
                if self._accept(question, value, rationale):
                    return
                continue
            if self._accept(question, raw, None):
                return

    def _deferred_value(
        self, question: Question, default: Any, hint: str | None, deferred: bool
    ) -> tuple[Any, str | None]:
        """Value to store when the user presses Enter or types none."""
        if deferred:
            if question.field in self.suggestions:
                return self.suggestions[question.field].value, None
            chosen = best_answer(question, self.data)
            if chosen is not None and not is_missing(chosen[0]):
                return chosen
            if not is_missing(default):
                shown = None
                if hint and hint.startswith("Best fit — "):
                    shown = hint.removeprefix("Best fit — ")
                return default, shown
            return _UNRESOLVED, None
        if is_missing(default):
            return _UNRESOLVED, None
        if hint and hint.startswith("Best fit — "):
            return default, hint.removeprefix("Best fit — ")
        if hint and hint.startswith("AI suggestion — "):
            return default, None
        return default, None

    def _ask_clarification(self, text: str, label: str) -> None:
        while True:
            raw = self.io.ask(
                label=label,
                prompt=text,
                help_text="Free-text answer; press Enter to leave it as an open question.",
                choices=(),
                default=None,
                hint=None,
                critical=False,
            ).strip()
            command = raw.lower()
            if command in BACK_WORDS:
                raise _Back()
            if command in EXIT_WORDS:
                self._pause()
            if command in HELP_WORDS:
                self.io.info(COMMAND_HELP)
                continue
            break
        if raw and command not in SKIP_WORDS:
            clarifications = [
                item
                for item in self.data.get("clarifications") or []
                if isinstance(item, dict) and item.get("question") != text
            ]
            clarifications.append({"question": text, "answer": raw})
            self.data["clarifications"] = clarifications
        self._save()

    def _exclude(self, names: list[str]) -> None:
        current = normalize_excluded(self.data.get("excluded_components")) or []
        for name in names:
            if name not in current:
                current.append(name)
        self.data["excluded_components"] = current

    def _keep_optional_parts(self, question: Question) -> None:
        self.data["excluded_components"] = []
        self.suggestions.pop(question.field, None)
        self._record_evidence(question, [], False, None)
        self.io.info("Optional parts stay in the design.")
        self._save()

    def _finish_exclusion(self, question: Question) -> None:
        excluded = self.data.get("excluded_components") or []
        if question.field == "profile":
            self.data["profile"] = "agnostic"
        elif question.field in {"existing_services", "user_roles", "data_sources"}:
            self.data[question.field] = []
        elif question.field == "identity_provider":
            self.data["identity_provider"] = None
        elif question.field == "documents_per_day":
            self.data["documents_per_day"] = None
        elif question.field == "excluded_components":
            self.data["excluded_components"] = excluded
        self.suggestions.pop(question.field, None)
        self._record_evidence(question, self.data.get(question.field), False, None)
        self.io.info("Left out of the design: " + ", ".join(excluded) + ".")
        self._save()

    def _store_blank(self, question: Question) -> None:
        self.data[question.field] = [] if question.kind in {"list", "multichoice"} else None
        self.suggestions.pop(question.field, None)
        self._clear_assumption(question)
        self._save()

    def _accept(self, question: Question, raw_value: Any, rationale: str | None) -> bool:
        try:
            value = parse_answer(question, raw_value, self.data)
        except ValueError as exc:
            self.io.error(str(exc))
            return False
        if question.field == "excluded_components":
            value = normalize_excluded(value) or []
        self.data[question.field] = value
        from_suggestion = (
            rationale is None
            and question.field in self.suggestions
            and raw_value == self.suggestions[question.field].value
        )
        self.suggestions.pop(question.field, None)
        self._clear_assumption(question)
        if rationale:
            self._add_assumption(question, value, rationale)
            self.io.info(f"{field_label(question)}: {format_value(value)}. {rationale}")
        self._record_evidence(question, value, from_suggestion, rationale)
        self._save()
        return True

    def _assumption_id(self, question: Question) -> str:
        return f"assumption-{question.field.replace('_', '-')}"

    def _clear_assumption(self, question: Question) -> None:
        identifier = self._assumption_id(question)
        self.data["assumptions"] = [
            item
            for item in self.data.get("assumptions") or []
            if not (isinstance(item, dict) and item.get("id") == identifier)
        ]

    def _add_assumption(self, question: Question, value: Any, rationale: str) -> None:
        assumptions = [
            item
            for item in self.data.get("assumptions") or []
            if isinstance(item, dict) and item.get("id") != self._assumption_id(question)
        ]
        assumptions.append(
            {
                "id": self._assumption_id(question),
                "statement": f"{question.field} = {format_value(value)}",
                "rationale": rationale[:300],
                "critical": question.critical,
            }
        )
        self.data["assumptions"] = assumptions

    def _record_evidence(
        self,
        question: Question,
        value: Any,
        from_suggestion: bool,
        rationale: str | None = None,
    ) -> None:
        evidence = [
            item
            for item in self.data.get("evidence") or []
            if not (
                isinstance(item, dict)
                and item.get("source_id") == "interview"
                and item.get("location") == question.id
            )
        ]
        if rationale:
            provenance = "assumed"
            recorded = rationale
        elif from_suggestion:
            provenance = "provided"
            recorded = "confirmed AI suggestion in guided interview"
        else:
            provenance = "provided"
            recorded = "answered in guided interview"
        evidence.append(
            {
                "source_id": "interview",
                "location": question.id,
                "value": value,
                "provenance": provenance,
                "rationale": recorded,
            }
        )
        self.data["evidence"] = evidence

    def _resolve_conflicts(self) -> None:
        remaining = []
        for conflict in self.data.get("conflicts") or []:
            if not isinstance(conflict, dict) or not conflict.get("blocking", True):
                remaining.append(conflict)
                continue
            field = str(conflict.get("field"))
            values = [format_value(value) for value in conflict.get("values", [])]
            self.io.section("Conflicting requirements")
            while True:
                raw = self.io.ask(
                    label="conflict",
                    prompt=f"Sources disagree on '{field}'. Which value is correct?",
                    help_text="Pick a number or type the correct value.",
                    choices=tuple(values),
                    default=None,
                    hint=None,
                    critical=True,
                ).strip()
                if raw.lower() in EXIT_WORDS:
                    self._pause()
                if raw.isdigit() and 1 <= int(raw) <= len(values):
                    chosen: Any = conflict["values"][int(raw) - 1]
                elif raw:
                    chosen = raw
                else:
                    self.io.error("Choose one of the values.")
                    continue
                question = QUESTION_BY_FIELD.get(field)
                try:
                    self.data[field] = parse_answer(question, chosen) if question else chosen
                except ValueError as exc:
                    self.io.error(str(exc))
                    continue
                break
        self.data["conflicts"] = remaining
        self._save()

    def _review(self) -> None:
        while True:
            visible = [question for question in QUESTIONS if question.applies(self.data)]
            rows = [
                (
                    str(number),
                    question.group,
                    field_label(question),
                    format_value(self.data.get(question.field)),
                )
                for number, question in enumerate(visible, start=1)
            ]
            choice = self.io.review(rows).strip().lower()
            if choice in {"", "y", "yes", "start", "go", "ok"}:
                return
            if choice in EXIT_WORDS:
                self._pause()
            if choice.isdigit() and 1 <= int(choice) <= len(visible):
                question = visible[int(choice) - 1]
                self.io.section(question.group)
                self._ask_question(question, "edit", allow_back=False)
                continue
            self.io.error("Press Enter to start the design, type a number to change it, or 'save'.")
