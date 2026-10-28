"""Resumable guided interview. Terminal rendering is injected through :class:`InterviewIO`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from archai.errors import InterviewPaused
from archai.interview.questions import (
    QUESTION_BY_FIELD,
    QUESTIONS,
    Question,
    format_value,
    is_missing,
    parse_answer,
)

BACK_WORDS = {"back", "b", "<"}
HELP_WORDS = {"?", "help", "h"}
SKIP_WORDS = {"skip", "-"}
EXIT_WORDS = {"exit", "quit", "save", "q"}
COMMAND_HELP = (
    "Commands: Enter = accept default · back · skip (optional only) · ? help · save = exit"
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
            if is_missing(data.get(question.field)) or question.field in self.suggestions
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
        return question.default_value(self.data), None

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
                self.data[question.field] = [] if question.kind in {"list", "multichoice"} else None
                self._save()
                return
            if not raw:
                if default_text is None:
                    if question.critical:
                        self.io.error(
                            "This answer is required. Type 'save' to stop and resume later."
                        )
                        continue
                    self.data[question.field] = (
                        [] if question.kind in {"list", "multichoice"} else None
                    )
                    self._save()
                    return
                raw_value: Any = default
            else:
                raw_value = raw
            try:
                value = parse_answer(question, raw_value, self.data)
            except ValueError as exc:
                self.io.error(str(exc))
                continue
            self.data[question.field] = value
            accepted_suggestion = not raw and question.field in self.suggestions
            self._record_evidence(question, value, accepted_suggestion)
            self.suggestions.pop(question.field, None)
            self._save()
            return

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

    def _record_evidence(self, question: Question, value: Any, from_suggestion: bool) -> None:
        evidence = [
            item
            for item in self.data.get("evidence") or []
            if not (
                isinstance(item, dict)
                and item.get("source_id") == "interview"
                and item.get("location") == question.id
            )
        ]
        evidence.append(
            {
                "source_id": "interview",
                "location": question.id,
                "value": value,
                "provenance": "provided",
                "rationale": "confirmed AI suggestion in guided interview"
                if from_suggestion
                else "answered in guided interview",
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
