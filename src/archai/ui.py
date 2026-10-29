"""Rich terminal presentation: guided interview, live agent status, and run summaries."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from archai.application.registry import COMPONENTS
from archai.application.supervisor import StepStatus
from archai.interview.session import InterviewSession, Suggestion
from archai.schemas.models import (
    ComponentStatus,
    EnterpriseDesign,
    ExportBundleManifest,
    RevisionManifest,
    RunState,
)

ICONS = {
    "pending": "[dim]·[/dim]",
    "done": "[green]✔[/green]",
    "failed": "[yellow]![/yellow]",
    "skipped": "[dim]–[/dim]",
}
STATUS_STYLE = {
    ComponentStatus.valid: "green",
    ComponentStatus.not_applicable: "dim",
    ComponentStatus.stale: "yellow",
    ComponentStatus.blocked: "red",
    ComponentStatus.draft: "cyan",
    ComponentStatus.missing: "red",
}


def banner(console: Console, subtitle: str) -> None:
    console.print(
        Panel.fit(
            f"[bold]ArchAI[/bold] · enterprise AI solutions architect\n[dim]{subtitle}[/dim]",
            border_style="blue",
        )
    )


def ask_multiline(console: Console, prompt: str) -> str:
    console.print(f"[bold cyan]?[/bold cyan] {prompt}")
    console.print("[dim]  Type or paste your description; finish with an empty line.[/dim]")
    lines: list[str] = []
    while True:
        try:
            line = console.input("  [cyan]›[/cyan] ")
        except EOFError:
            break
        if not line.strip():
            if lines:
                break
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- interview


class RichInterviewIO:
    def __init__(self, console: Console) -> None:
        self.console = console

    def section(self, title: str) -> None:
        self.console.rule(f"[bold]{title}[/bold]", style="blue", align="left")

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
    ) -> str:
        marker = "[red]*[/red]" if critical else " "
        self.console.print(f"{marker}[bold cyan][{label}][/bold cyan] [bold]{prompt}[/bold]")
        if help_text:
            self.console.print(f"   [dim]{help_text}[/dim]")
        if choices:
            options = "   ".join(
                f"[cyan]{n}[/cyan]) {choice}" for n, choice in enumerate(choices, 1)
            )
            self.console.print(f"   {options}")
        if hint:
            self.console.print(f"   [magenta]✦ {hint}[/magenta]")
        try:
            return Prompt.ask(
                "   [cyan]›[/cyan]",
                console=self.console,
                default=default or "",
                show_default=bool(default),
            )
        except EOFError:
            return "save"

    def info(self, text: str) -> None:
        self.console.print(f"[dim]{text}[/dim]")

    def error(self, text: str) -> None:
        self.console.print(f"   [red]✖ {text}[/red]")

    def review(self, rows: list[tuple[str, str, str, str]]) -> str:
        table = Table(title="Review your answers", show_lines=False, header_style="bold")
        table.add_column("#", justify="right", style="cyan")
        table.add_column("Group", style="dim")
        table.add_column("Field")
        table.add_column("Value", overflow="fold")
        for row in rows:
            table.add_row(*row)
        self.console.print(table)
        try:
            return Prompt.ask(
                "Press [bold]Enter[/bold] to start the design, a [cyan]number[/cyan] to change "
                "an answer, or [bold]save[/bold] to finish later",
                console=self.console,
                default="",
                show_default=False,
            )
        except EOFError:
            return ""


class RichInterviewer:
    """Adapter between the service-layer Interviewer protocol and the guided session."""

    def __init__(self, console: Console, progress: RichProgress | None = None) -> None:
        self.io = RichInterviewIO(console)
        self.console = console
        self.progress = progress

    def interview(
        self,
        data: dict[str, Any],
        *,
        suggestions: dict[str, Suggestion],
        clarifying_questions: list[str],
        persist: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        session = InterviewSession(
            self.io,
            data,
            suggestions=suggestions,
            clarifying_questions=clarifying_questions,
            persist=persist,
        )
        if self.progress is not None:
            self.progress.pause()
        try:
            return session.run()
        finally:
            if self.progress is not None:
                self.progress.resume()

    def fix(
        self,
        data: dict[str, Any],
        fields: list[str],
        reason: str,
        persist: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        session = InterviewSession(self.io, data, persist=persist, review=False)
        if self.progress is not None:
            self.progress.pause()
        try:
            return session.reask(fields, reason)
        finally:
            if self.progress is not None:
                self.progress.resume()


# ---------------------------------------------------------------- live status


@dataclass
class _Step:
    title: str
    status: StepStatus
    detail: str
    started: float
    finished: float | None = None


class RichProgress:
    """Thread-safe live board of design steps.

    On a terminal the board is a Rich Live panel that pauses while the interview prompts; on
    other consoles (CI, pipes, tests) each finished step is printed as one line.
    """

    def __init__(self, console: Console, title: str) -> None:
        self.console = console
        self.title = title
        self.steps: dict[str, _Step] = {}
        self._lock = threading.Lock()
        self._live: Live | None = None
        self._paused = False
        self._spinner = Spinner("dots", style="cyan")

    def __enter__(self) -> RichProgress:
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop()

    def _start(self) -> None:
        if self._live is None and not self._paused and self.console.is_terminal:
            self._live = Live(self, console=self.console, refresh_per_second=8, transient=False)
            self._live.start()

    def _stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def pause(self) -> None:
        """Stop the live board (keeping what it showed) so prompts can use the terminal."""
        self._stop()
        self._paused = True
        with self._lock:
            self.steps = {key: step for key, step in self.steps.items() if step.status == "running"}

    def resume(self) -> None:
        self._paused = False

    def step(self, key: str, title: str, status: StepStatus, detail: str = "") -> None:
        with self._lock:
            now = time.monotonic()
            current = self.steps.get(key)
            if current is None:
                self.steps[key] = _Step(title, status, detail, now)
            else:
                if current.status == "pending" and status == "running":
                    current.started = now
                current.title, current.status = title, status
                current.detail = detail or current.detail
                if status in {"done", "failed", "skipped"}:
                    current.finished = now
        if self.console.is_terminal:
            self._start()
        elif status in {"done", "failed"}:
            self.console.print(f"{ICONS.get(status, '')} {title} [dim]{detail}[/dim]")

    def message(self, text: str) -> None:
        self.console.print(f"[dim]{text}[/dim]")

    def __rich__(self) -> RenderableType:
        table = Table.grid(padding=(0, 1))
        table.add_column(width=2)
        table.add_column(min_width=40)
        table.add_column(style="dim", overflow="fold")
        table.add_column(justify="right", style="dim", width=6)
        with self._lock:
            items = list(self.steps.values())
        now = time.monotonic()
        for item in items:
            icon: RenderableType = (
                self._spinner
                if item.status == "running"
                else Text.from_markup(ICONS.get(item.status, "·"))
            )
            elapsed = ""
            if item.status != "pending":
                elapsed = f"{(item.finished or now) - item.started:.0f}s"
            table.add_row(icon, item.title, item.detail, elapsed)
        return Panel(
            table, title=f"[bold]{self.title}[/bold]", border_style="blue", title_align="left"
        )


# ---------------------------------------------------------------- summaries


def component_table(design: EnterpriseDesign, title: str = "Components") -> Table:
    from archai.compilers.report import document_name, source_label

    table = Table(title=title, header_style="bold", title_justify="left")
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Designed by", overflow="fold")
    table.add_column("Document", style="dim")
    for name, spec in COMPONENTS.items():
        state = design.components.get(name)
        if state is None or name == "doc":
            continue
        style = STATUS_STYLE.get(state.status, "")
        table.add_row(
            spec.title,
            f"[{style}]{state.status.value}[/{style}]",
            source_label(state.source),
            document_name(name),
        )
    return table


def print_summary(
    console: Console,
    design: EnterpriseDesign,
    revision_manifest: RevisionManifest,
    bundle: Path,
    export: ExportBundleManifest,
    run: RunState | None,
) -> None:
    console.print(component_table(design, f"Revision {revision_manifest.revision} components"))
    generated = [item for item in export.artifacts if item.status == "generated"]
    failed = [item for item in export.artifacts if item.status == "failed"]
    pdfs = [item.path for item in generated if item.path.endswith(".pdf")]
    docs = [item.path for item in generated if item.path.endswith(".md")]
    diagrams = [item.path for item in generated if item.path.startswith("diagrams/")]
    infra = [
        item.path for item in generated if item.path.startswith(("infrastructure/", "workloads/"))
    ]
    errors = [d for d in revision_manifest.diagnostics if d.severity == "error"]
    warnings = [d for d in revision_manifest.diagnostics if d.severity == "warning"]
    lines = [
        f"[bold]Project[/bold] {design.project} · revision {revision_manifest.revision} · "
        + (
            "[green]complete design[/green]"
            if revision_manifest.project_complete
            else "[yellow]partial design[/yellow]"
        ),
        f"[bold]Bundle[/bold] {bundle}",
        f"[bold]Artifacts[/bold] {len(docs)} documents · {len(pdfs)} PDFs · "
        f"{len(diagrams)} diagram files · {len(infra)} IaC/workload files"
        + (f" · [yellow]{len(failed)} failed[/yellow]" if failed else ""),
        f"[bold]Validation[/bold] {len(errors)} errors · {len(warnings)} warnings · "
        f"{len(design.verification)} verifier findings",
    ]
    if run and run.role_calls:
        tokens = sum((c.input_tokens or 0) + (c.output_tokens or 0) for c in run.role_calls)
        models = sorted({f"{c.provider}:{c.model}" for c in run.role_calls})
        lines.append(
            f"[bold]Architect models[/bold] {', '.join(models)} · {len(run.role_calls)} calls · "
            f"{tokens / 1000:.1f}k tokens"
        )
    elif run:
        lines.append(
            "[bold]Architect models[/bold] none (deterministic baseline; run "
            "`archai setup` to enable the AI architect team)"
        )
    main_pdf = next((p for p in pdfs if p.startswith("Complete_AI_System_Design")), None)
    if main_pdf:
        lines.append(f"[bold]Open[/bold] {bundle / main_pdf}")
    elif pdfs:
        lines.append(f"[bold]Open[/bold] {bundle / pdfs[0]}")
    master_pdf = next((path for path in pdfs if path.startswith("master_design/")), None)
    if master_pdf:
        lines.append(f"[bold]Master design[/bold] {bundle / master_pdf}")
    console.print(
        Panel(
            "\n".join(lines),
            title="[bold green]Design saved[/bold green]",
            border_style="green",
            title_align="left",
        )
    )
    for item in warnings[:6]:
        console.print(f"[yellow]warning[/yellow] {item.component or ''} {item.message}")
    if len(warnings) > 6:
        console.print(f"[dim]… {len(warnings) - 6} more warnings in validation_report.json[/dim]")


def print_status(
    console: Console,
    design: EnterpriseDesign,
    revision: RevisionManifest,
    export_path: Path | None,
    last_run: RunState | None,
) -> None:
    console.print(component_table(design, f"{design.project} · revision {revision.revision}"))
    body = [
        f"Completeness: {'complete' if revision.project_complete else 'partial'}",
        f"Last revision scope: {', '.join(revision.selected_scope)}",
        f"Latest export: {export_path or 'none'}",
    ]
    if last_run is not None:
        body.append(f"Last run: {last_run.id} ({last_run.status})")
        if last_run.status in {"blocked", "interviewing"}:
            body.append(f"Resume with: archai resume {design.project} --run {last_run.id}")
    console.print(Panel("\n".join(body), border_style="blue"))


def confirm(console: Console, prompt: str, default: bool = True) -> bool:
    try:
        return Confirm.ask(prompt, console=console, default=default)
    except EOFError:
        return default
