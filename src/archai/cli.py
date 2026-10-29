from __future__ import annotations

import contextlib
import difflib
import json
import os
import shutil
import sys
from importlib.util import find_spec
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from dotenv import dotenv_values, set_key, unset_key
from pydantic import ValidationError as PydanticValidationError
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from archai import __version__, config
from archai.application.registry import (
    COMPILED_COMPONENTS,
    COMPONENTS,
    DOCUMENT_PACKAGES,
    review_scope,
)
from archai.application.service import (
    add_lock,
    auto_scope,
    generation_plan,
    remove_lock,
    roles_for_scope,
    run_generation,
)
from archai.compilers.export import DIAGRAM_VIEWS, export_revision, normalize_formats
from archai.domain.validation import validate_design
from archai.errors import ArchAIError, IncompleteRequirementsError, InterviewPaused, ValidationError
from archai.ingestion import load_structured
from archai.interview.questions import QUESTION_BY_ID
from archai.persistence.store import ProjectStore, json_bytes
from archai.schemas.models import ExportBundleManifest, RunState
from archai.simulators.scenario import simulate_scenario
from archai.ui import (
    RichInterviewer,
    RichProgress,
    ask_multiline,
    banner,
    print_status,
    print_summary,
)

console = Console()
err_console = Console(stderr=True)
app = typer.Typer(
    name="arch",
    help="ArchAI: design managed-API enterprise AI systems without deploying them.\n\n"
    "Complete design: `arch auto` (interviews you on a terminal). Components: `arch system`, "
    "`arch infra`, `arch auth`, ... Compiled documents: `arch hld`, `arch lld`, `arch doc`. "
    "Project operations: `status`, `inspect`, `export`, `validate`, `lock`, `edit`, `diff`, "
    "`simulate`, `setup`, `doctor`.",
    no_args_is_help=False,
    rich_markup_mode="markdown",
)
catalog_app = typer.Typer(help="Inspect and validate trusted packaged catalogs.")
app.add_typer(catalog_app, name="catalog")
model_app = typer.Typer(
    help="Show, list, and switch architect models (OpenAI, Anthropic, Gemini, DeepSeek)."
)
app.add_typer(model_app, name="model")

OutputDir = Annotated[
    Path | None,
    typer.Option(
        "--output-dir", help="Project store root (default ARCHAI_OUTPUT_DIR or ./output)."
    ),
]


def _output(path: Path | None) -> Path:
    return path if path is not None else config.load_settings().output_dir


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _fail(exc: BaseException) -> None:
    if isinstance(exc, typer.Exit | typer.Abort):
        raise exc
    if isinstance(exc, KeyboardInterrupt):
        err_console.print("\n[yellow]Interrupted.[/yellow] Saved progress is kept in the run.")
        raise typer.Exit(130) from exc
    if isinstance(exc, InterviewPaused):
        err_console.print("[yellow]Interview saved.[/yellow] " + str(exc))
        if exc.run_id:
            err_console.print(f"Resume with: [bold]archai resume PROJECT --run {exc.run_id}[/bold]")
        raise typer.Exit(exc.exit_code) from exc
    if isinstance(exc, IncompleteRequirementsError) and exc.question_ids:
        table = Table(title="Unanswered critical questions", header_style="bold")
        table.add_column("ID", style="cyan")
        table.add_column("Question")
        for question_id in exc.question_ids:
            question = QUESTION_BY_ID.get(question_id)
            table.add_row(question_id, question.prompt if question else "")
        err_console.print(table)
        err_console.print(
            json.dumps({"unresolved_questions": exc.question_ids, "run_id": exc.run_id})
        )
        err_console.print(
            "Answer them in a terminal with [bold]archai auto -p PROJECT[/bold] (without "
            "--non-interactive), or pass [bold]--answers answers.yaml[/bold]."
        )
    if isinstance(exc, ArchAIError):
        code = exc.exit_code
    elif isinstance(exc, ValueError | PydanticValidationError | FileNotFoundError):
        code = 2
    else:
        code = 1
    err_console.print(f"[red]Error:[/red] {exc}", soft_wrap=True)
    raise typer.Exit(code) from exc


def _validate_provider(name: str | None) -> None:
    if name and name.lower() not in config.PROVIDER_NAMES:
        raise ValueError(f"architect provider must be one of {', '.join(config.PROVIDER_NAMES)}")


# ---------------------------------------------------------------- root and guided selector


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show version and exit.")] = False,
    legacy_project: Annotated[
        str | None,
        typer.Option("--project", "-p", help="Legacy file-only invocation maps to auto."),
    ] = None,
    legacy_file: Annotated[
        list[Path] | None, typer.Option("--file", "-f", help="Legacy requirements file.")
    ] = None,
    legacy_update: Annotated[bool, typer.Option("--update", help="Legacy update mapping.")] = False,
) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is not None:
        return
    if legacy_project:
        if legacy_update:
            console.print("Legacy --update maps to `arch update PROJECT`.")
            raise typer.Exit(2)
        _execute_generation(
            project=legacy_project,
            scope=auto_scope(),
            files=legacy_file or [],
            interactive=False,
        )
        return
    table = Table(title="ArchAI guided component selector")
    table.add_column("Command")
    table.add_column("Scope")
    table.add_row("arch auto", "Complete applicable design, validation, documents, and artifacts")
    for name, spec in COMPONENTS.items():
        suffix = " from the saved revision" if name in COMPILED_COMPONENTS else " only"
        table.add_row(f"arch {name}", f"{spec.title}{suffix}")
    for name, spec in DOCUMENT_PACKAGES.items():
        table.add_row(f"arch {name}", f"{spec.title} from the saved revision")
    console.print(table)
    if not _is_interactive():
        console.print("Use `arch COMMAND --help`. Automatic mode never deploys infrastructure.")
        return
    choice = (
        Prompt.ask(
            "What would you like to do? [cyan]auto[/cyan] (complete design), a component name, "
            "[cyan]status[/cyan], [cyan]setup[/cyan], or Enter to quit",
            console=console,
            default="",
            show_default=False,
        )
        .strip()
        .lower()
    )
    if not choice:
        return
    if choice == "auto":
        auto()
    elif choice == "status":
        status()
    elif choice == "setup":
        setup()
    elif choice in COMPILED_COMPONENTS or choice in DOCUMENT_PACKAGES:
        project = Prompt.ask("Project name", console=console).strip()
        if not project:
            return
        try:
            store = ProjectStore(_output(None), project)
            number = store.metadata().latest_revision
            design = store.load_design(number)
            selected_scope = review_scope(design.components) if choice == "doc" else [choice]
            bundle, manifest = export_revision(
                store, number, normalize_formats("all"), selected_scope
            )
            _print_result(store, number, bundle, manifest)
        except Exception as exc:
            _fail(exc)
    elif choice in COMPONENTS:
        project = Prompt.ask("Project name", console=console)
        _execute_generation(project=project, scope=[choice], files=[], interactive=True)
    else:
        console.print(f"Unknown choice {choice!r}. Run `arch --help`.")


# ---------------------------------------------------------------- generation


def _execute_generation(
    *,
    project: str,
    scope: list[str],
    files: list[Path],
    idea: str | None = None,
    stdin: bool = False,
    answers: Path | None = None,
    profile: str | None = None,
    region: str | None = None,
    target_providers: str | None = None,
    topology: str | None = None,
    archetype: list[str] | None = None,
    dry_run: bool = False,
    allow_assumptions: bool = False,
    output_dir: Path | None = None,
    formats: str = "core",
    base_revision: int | None = None,
    architect_provider: str | None = None,
    architect_model: str | None = None,
    role_models: list[str] | None = None,
    offline: bool = False,
    override: Path | None = None,
    interactive: bool = False,
    export_scope: list[str] | None = None,
    run_id: str | None = None,
) -> None:
    try:
        _validate_provider(architect_provider)
        format_set = normalize_formats(formats)
        store = ProjectStore(_output(output_dir), project)
        if dry_run:
            plan = generation_plan(store, scope, files, formats)
            plan["roles"] = roles_for_scope(scope)
            console.print_json(data=plan)
            return
        title = (
            f"ArchAI · designing {store.slug}"
            if len(scope) > 1
            else f"ArchAI · {COMPONENTS[scope[0]].title} design for {store.slug}"
        )
        with RichProgress(console, title) as progress:
            interviewer = RichInterviewer(console, progress) if interactive else None
            store, revision = run_generation(
                project=project,
                scope=scope,
                output_dir=_output(output_dir),
                files=files,
                idea=idea,
                stdin_enabled=stdin,
                answers=answers,
                profile=profile,
                region=region,
                target_providers=target_providers,
                topology=topology,
                archetypes=archetype or [],
                allow_assumptions=allow_assumptions,
                override=override,
                requested_base_revision=base_revision,
                architect_provider=architect_provider,
                architect_model=architect_model,
                role_models=role_models,
                offline=offline,
                interviewer=interviewer,
                reporter=progress,
                run_id=run_id,
            )
            progress.step("export", "Documents, diagrams, PDF & IaC export", "running")
            bundle, manifest = export_revision(store, revision, format_set, export_scope or scope)
            generated = sum(1 for item in manifest.artifacts if item.status == "generated")
            progress.step(
                "export", "Documents, diagrams, PDF & IaC export", "done", f"{generated} files"
            )
        _print_result(store, revision, bundle, manifest)
    except BaseException as exc:
        _fail(exc)


def _latest_run(store: ProjectStore, revision: int | None = None) -> RunState | None:
    runs = store.root / "runs"
    if not runs.exists():
        return None
    states: list[RunState] = []
    for path in runs.iterdir():
        target = path / "run.json"
        if target.exists():
            try:
                states.append(RunState.model_validate_json(target.read_text(encoding="utf-8")))
            except PydanticValidationError:
                continue
    if revision is not None:
        matching = [state for state in states if state.revision == revision]
        if matching:
            return max(matching, key=lambda state: state.created_at)
    return max(states, key=lambda state: state.created_at) if states else None


def _print_result(
    store: ProjectStore, revision: int, bundle: Path, manifest: ExportBundleManifest
) -> None:
    console.print(f"[green]Accepted revision {revision}[/green] for `{store.slug}`")
    try:
        design = store.load_design(revision)
        revision_manifest = store.load_manifest(revision)
        print_summary(
            console, design, revision_manifest, bundle, manifest, _latest_run(store, revision)
        )
    except (OSError, PydanticValidationError) as exc:  # pragma: no cover - defensive display
        console.print(f"Export bundle: {bundle} ({exc})")
    failed = [item for item in manifest.artifacts if item.status == "failed"]
    if failed:
        for item in failed:
            err_console.print(f"[yellow]Export failed:[/yellow] {item.path}: {item.reason}")
        raise typer.Exit(5)


def component_entry(
    ctx: typer.Context,
    project: Annotated[str, typer.Option("--project", "-p", help="Project name.")],
    files: Annotated[
        list[Path] | None, typer.Option("--file", "-f", help="Requirements file; repeatable.")
    ] = None,
    idea: Annotated[
        str | None, typer.Option("--idea", "-i", help="Inline requirement or idea.")
    ] = None,
    stdin: Annotated[
        bool, typer.Option("--stdin", help="Read another input source from standard input.")
    ] = False,
    answers: Annotated[
        Path | None, typer.Option("--answers", help="Structured JSON/YAML answers.")
    ] = None,
    architect_provider: Annotated[
        str | None,
        typer.Option("--architect-provider", help="openai, anthropic, gemini, or deepseek."),
    ] = None,
    architect_model: Annotated[
        str | None, typer.Option("--architect-model", help="Designer model identifier.")
    ] = None,
    role_model: Annotated[
        list[str] | None,
        typer.Option("--role-model", help="Per-role model, e.g. verifier=openai:MODEL."),
    ] = None,
    profile: Annotated[
        str | None, typer.Option("--profile", help="azure-aca, azure-aks, aws-eks, or agnostic.")
    ] = None,
    region: Annotated[
        str | None, typer.Option("--region", help="Application hosting region.")
    ] = None,
    target_providers: Annotated[
        str | None,
        typer.Option("--target-providers", help="Comma-separated managed inference providers."),
    ] = None,
    topology: Annotated[
        str | None,
        typer.Option("--topology", help="single-cloud, provider-failover, or application-dr."),
    ] = None,
    policy: Annotated[
        Path | None, typer.Option("--policy", help="Structured policy constraints.")
    ] = None,
    archetype: Annotated[
        list[str] | None, typer.Option("--archetype", help="Workload archetype; repeatable.")
    ] = None,
    mode: Annotated[
        str, typer.Option("--mode", help="guided or auto for this component only.")
    ] = "guided",
    override: Annotated[
        Path | None, typer.Option("--override", help="Typed component-scoped override YAML.")
    ] = None,
    base_revision: Annotated[
        int | None, typer.Option("--base-revision", help="Expected latest revision.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print plan; make no calls or writes.")
    ] = False,
    non_interactive: Annotated[
        bool, typer.Option("--non-interactive", help="Never prompt.")
    ] = False,
    allow_assumptions: Annotated[
        bool,
        typer.Option("--allow-assumptions", help="Allow only noncritical documented defaults."),
    ] = False,
    offline: Annotated[
        bool, typer.Option("--offline", help="Deterministic baseline only; no model calls.")
    ] = False,
    output_dir: OutputDir = None,
    formats: Annotated[
        str, typer.Option("--formats", help="all, core, or comma-separated formats.")
    ] = "all",
    scope: Annotated[
        str | None, typer.Option("--scope", help="Document scopes, comma-separated.")
    ] = None,
    view: Annotated[str | None, typer.Option("--view", help="Diagram view selector.")] = None,
    sections: Annotated[str | None, typer.Option("--sections", help="Document sections.")] = None,
    audience: Annotated[
        str, typer.Option("--audience", help="technical or executive.")
    ] = "technical",
    template: Annotated[
        str, typer.Option("--template", help="Trusted packaged template name.")
    ] = "default",
) -> None:
    del sections
    component = str(ctx.info_name)
    if component == "design":
        component = "system"
    try:
        _validate_provider(architect_provider)
        if mode not in {"guided", "auto"}:
            raise ValueError("--mode must be guided or auto")
        if audience not in {"technical", "executive"}:
            raise ValueError("--audience must be technical or executive")
        if template != "default":
            raise ValueError("unknown trusted document template")
        if view and component != "diagram":
            raise ValueError("--view is valid only for the diagram command")
        if view and view not in DIAGRAM_VIEWS:
            raise ValueError(f"unknown diagram view; choose from {', '.join(DIAGRAM_VIEWS)}")
        store = ProjectStore(_output(output_dir), project)
        selected_files = list(files or [])
        if policy:
            selected_files.append(policy)
        has_inputs = any(
            [
                selected_files,
                idea,
                stdin,
                answers,
                profile,
                region,
                target_providers,
                topology,
                archetype,
                override,
            ]
        )
        if component in DOCUMENT_PACKAGES:
            if has_inputs:
                raise ValueError(
                    f"`arch {component}` compiles a saved revision; do not pass requirements "
                    "files. Run `arch auto` first, then this command."
                )
            if not store.project_file.exists() or store.metadata().latest_revision <= 0:
                raise FileNotFoundError(
                    f"No saved revision for {store.slug}. Run `arch auto -p {store.slug}` first, "
                    f"then `arch {component}`."
                )
            number = base_revision or store.metadata().latest_revision
            bundle, manifest = export_revision(
                store, number, normalize_formats(formats), [component]
            )
            _print_result(store, number, bundle, manifest)
            return
        if component in {"doc", "diagram"} and not has_inputs:
            number = base_revision or store.metadata().latest_revision
            design = store.load_design(number)
            if component == "doc":
                selected_scope = (
                    [item.strip() for item in scope.split(",") if item.strip()]
                    if scope
                    else review_scope(design.components)
                )
                unknown = set(selected_scope) - set(COMPONENTS) - set(DOCUMENT_PACKAGES)
                if unknown:
                    raise ValueError(f"unknown document scope: {', '.join(sorted(unknown))}")
            else:
                selected_scope = ["diagram"]
            bundle, manifest = export_revision(
                store, number, normalize_formats(formats), selected_scope, view
            )
            _print_result(store, number, bundle, manifest)
            return
        if scope and component != "doc":
            raise ValueError("--scope is valid only for the doc command")
        interactive = mode == "guided" and not non_interactive and not stdin and _is_interactive()
    except Exception as exc:
        _fail(exc)
        return
    _execute_generation(
        project=project,
        scope=[component],
        files=selected_files,
        idea=idea,
        stdin=stdin,
        answers=answers,
        profile=profile,
        region=region,
        target_providers=target_providers,
        topology=topology,
        archetype=archetype or [],
        dry_run=dry_run,
        allow_assumptions=allow_assumptions,
        output_dir=output_dir,
        formats=formats,
        base_revision=base_revision,
        architect_provider=architect_provider,
        architect_model=architect_model,
        role_models=role_model,
        offline=offline,
        override=override,
        interactive=interactive,
    )


for _name, _spec in COMPONENTS.items():
    _help = (
        f"Compile {_spec.title.lower()} from the saved revision."
        if _name in COMPILED_COMPONENTS
        else f"Design {_spec.title.lower()} only and create its standalone document."
    )
    app.command(name=_name, help=_help)(component_entry)
for _name, _spec in DOCUMENT_PACKAGES.items():
    app.command(name=_name, help=f"Compile {_spec.title.lower()} from the saved revision.")(
        component_entry
    )
app.command(name="design", help="Alias of `arch system`; not a complete design.")(component_entry)


@app.command("auto")
def auto(
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project name.")] = None,
    files: Annotated[
        list[Path] | None, typer.Option("--file", "-f", help="Requirements file; repeatable.")
    ] = None,
    idea: Annotated[
        str | None, typer.Option("--idea", "-i", help="Describe the application inline.")
    ] = None,
    stdin: Annotated[bool, typer.Option("--stdin", help="Read requirements from stdin.")] = False,
    answers: Annotated[
        Path | None, typer.Option("--answers", help="Structured JSON/YAML answers.")
    ] = None,
    architect_provider: Annotated[
        str | None,
        typer.Option("--architect-provider", help="openai, anthropic, gemini, or deepseek."),
    ] = None,
    architect_model: Annotated[
        str | None, typer.Option("--architect-model", help="Default architect model ID.")
    ] = None,
    role_model: Annotated[
        list[str] | None,
        typer.Option(
            "--role-model",
            help="Per-role model, e.g. verifier=openai:MODEL or security=gemini:MODEL.",
        ),
    ] = None,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
    target_providers: Annotated[str | None, typer.Option("--target-providers")] = None,
    topology: Annotated[str | None, typer.Option("--topology")] = None,
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    archetype: Annotated[list[str] | None, typer.Option("--archetype")] = None,
    base_revision: Annotated[int | None, typer.Option("--base-revision")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Plan only; no writes.")] = False,
    non_interactive: Annotated[
        bool, typer.Option("--non-interactive", help="Never prompt (CI and scripts).")
    ] = False,
    allow_assumptions: Annotated[bool, typer.Option("--allow-assumptions")] = False,
    offline: Annotated[
        bool, typer.Option("--offline", help="Deterministic baseline only; no model calls.")
    ] = False,
    output_dir: OutputDir = None,
    formats: Annotated[str, typer.Option("--formats", help="all, core, or a list.")] = "all",
) -> None:
    """Complete AI system design: interview, multi-agent design, validation, and documents.

    Writes the complete design, master design, high-level design, and low-level design
    packages from the same revision.
    """
    interactive = not non_interactive and not stdin and _is_interactive()
    try:
        _validate_provider(architect_provider)
        if not project:
            if not interactive:
                err_console.print(
                    "Provide a project and requirements, for example:\n"
                    "  archai auto -p my-project -f requirements.yaml --formats core\n"
                    "Configure a model with `archai model use PROVIDER` or `archai setup`; see `archai auto --help` "
                    "for options."
                )
                raise typer.Exit(2)
            banner(console, "Complete AI system design")
            project = Prompt.ask("Project name", console=console).strip()
            if not project:
                raise ValueError("a project name is required")
        selected_files = list(files or [])
        if policy:
            selected_files.append(policy)
        if interactive and not dry_run:
            store = ProjectStore(_output(output_dir), project)
            existing = store.project_file.exists() and store.metadata().latest_revision > 0
            if not existing:
                console.print(f"Creating project [bold]{store.slug}[/bold] in {store.root}")
            if not (selected_files or idea or answers or existing):
                idea = ask_multiline(console, "Describe the AI application you want to design")
                if not idea:
                    raise ValueError("a description, -f FILE, or --answers is required")
    except BaseException as exc:
        _fail(exc)
        return
    _execute_generation(
        project=project,
        scope=auto_scope(),
        files=selected_files,
        idea=idea,
        stdin=stdin,
        answers=answers,
        profile=profile,
        region=region,
        target_providers=target_providers,
        topology=topology,
        archetype=archetype or [],
        dry_run=dry_run,
        allow_assumptions=allow_assumptions,
        output_dir=output_dir,
        formats=formats,
        base_revision=base_revision,
        architect_provider=architect_provider,
        architect_model=architect_model,
        role_models=role_model,
        offline=offline,
        interactive=interactive,
    )


@app.command("update")
def update(
    project: str,
    files: Annotated[list[Path] | None, typer.Option("--file", "-f")] = None,
    instruction: Annotated[str | None, typer.Option("--instruction", "-i")] = None,
    answers: Annotated[Path | None, typer.Option("--answers")] = None,
    non_interactive: Annotated[bool, typer.Option("--non-interactive")] = False,
    offline: Annotated[bool, typer.Option("--offline")] = False,
    output_dir: OutputDir = None,
    formats: Annotated[str, typer.Option("--formats")] = "core",
) -> None:
    """Create a new revision of the complete design from changed requirements."""
    _execute_generation(
        project=project,
        scope=auto_scope(),
        files=files or [],
        idea=instruction,
        answers=answers,
        output_dir=output_dir,
        formats=formats,
        offline=offline,
        interactive=not non_interactive and _is_interactive(),
    )


@app.command("resume")
def resume(
    project: str,
    run: Annotated[str, typer.Option("--run")],
    answers: Annotated[Path | None, typer.Option("--answers")] = None,
    non_interactive: Annotated[bool, typer.Option("--non-interactive")] = False,
    offline: Annotated[bool, typer.Option("--offline")] = False,
    output_dir: OutputDir = None,
    formats: Annotated[str, typer.Option("--formats")] = "core",
) -> None:
    """Continue a blocked or paused run (asks remaining questions on a terminal)."""
    try:
        store = ProjectStore(_output(output_dir), project)
        run_state, inputs = store.load_run(run)
        if run_state.status == "accepted":
            console.print(f"Run {run} is already accepted; no resume is needed.")
            return
        if inputs is None:
            raise ValueError(f"run {run!r} has no saved input snapshot")
    except BaseException as exc:
        _fail(exc)
        return
    _execute_generation(
        project=project,
        scope=run_state.selected_scope,
        files=[inputs],
        answers=answers,
        output_dir=output_dir,
        formats=formats,
        base_revision=run_state.base_revision,
        offline=offline,
        interactive=not non_interactive and _is_interactive(),
        run_id=run,
    )


# ---------------------------------------------------------------- project operations


@app.command("status")
def status(
    project: Annotated[str | None, typer.Argument(help="Project; omit to list all.")] = None,
    output_dir: OutputDir = None,
) -> None:
    """Show component status, completeness, latest export, and resumable runs."""
    try:
        root = _output(output_dir)
        if project is None:
            list_projects(output_dir)
            return
        store = ProjectStore(root, project)
        metadata = store.metadata()
        if metadata.latest_revision == 0:
            run = _latest_run(store)
            console.print(f"{store.slug}: no accepted revision yet.")
            if run is not None:
                console.print(
                    f"Last run {run.id}: {run.status}. Resume with: archai resume "
                    f"{store.slug} --run {run.id}"
                )
            return
        design = store.load_design()
        manifest = store.load_manifest()
        print_status(console, design, manifest, store.current_export_path(), _latest_run(store))
    except BaseException as exc:
        _fail(exc)


@app.command("inspect")
def inspect_project(
    project: str,
    revision: Annotated[int | None, typer.Option("--revision")] = None,
    component: Annotated[str | None, typer.Option("--component")] = None,
    output_dir: OutputDir = None,
) -> None:
    try:
        store = ProjectStore(_output(output_dir), project)
        design = store.load_design(revision)
        if component:
            value: Any = {
                "state": design.components.get(component),
                "owned": _component_value(design, component),
            }
        else:
            value = design
        console.print_json(json=json_bytes(value).decode())
    except Exception as exc:
        _fail(exc)


@app.command("list")
def list_projects(output_dir: OutputDir = None) -> None:
    root = _output(output_dir)
    if not root.exists():
        console.print("No projects.")
        return
    table = Table(title=f"Projects in {root}", header_style="bold")
    table.add_column("Project")
    table.add_column("Revision", justify="right")
    table.add_column("Complete revision", justify="right")
    table.add_column("Latest export", style="dim")
    found = False
    for path in sorted(root.iterdir()):
        if path.is_dir() and (path / "project.json").exists():
            metadata = json.loads((path / "project.json").read_text())
            found = True
            table.add_row(
                path.name,
                str(metadata["latest_revision"]),
                str(metadata.get("latest_complete_revision") or "—"),
                str(metadata.get("latest_export") or "—"),
            )
    console.print(table if found else "No projects.")


@app.command("lock")
def lock_component(
    project: Annotated[str, typer.Option("--project", "-p")],
    component: Annotated[str, typer.Option("--component")],
    field: Annotated[str | None, typer.Option("--field")] = None,
    output_dir: OutputDir = None,
) -> None:
    try:
        store = ProjectStore(_output(output_dir), project)
        with store.locked():
            locks = add_lock(store, component, field)
        console.print(
            f"Locked {component}{'.' + field if field else ''}; active locks={len(locks)}"
        )
    except Exception as exc:
        _fail(exc)


@app.command("unlock")
def unlock_component(
    project: Annotated[str, typer.Option("--project", "-p")],
    component: Annotated[str, typer.Option("--component")],
    field: Annotated[str | None, typer.Option("--field")] = None,
    output_dir: OutputDir = None,
) -> None:
    try:
        store = ProjectStore(_output(output_dir), project)
        with store.locked():
            locks = remove_lock(store, component, field)
        console.print(
            f"Unlocked {component}{'.' + field if field else ''}; active locks={len(locks)}"
        )
    except Exception as exc:
        _fail(exc)


@app.command("edit")
def edit_component(
    project: Annotated[str, typer.Option("--project", "-p")],
    component: Annotated[str, typer.Option("--component")],
    file: Annotated[Path, typer.Option("--file")],
    yes: Annotated[bool, typer.Option("--yes")] = False,
    non_interactive: Annotated[bool, typer.Option("--non-interactive")] = False,
    output_dir: OutputDir = None,
) -> None:
    try:
        if component not in COMPONENTS:
            raise ValueError(f"unknown component {component}")
        if non_interactive and not yes:
            raise ValueError("non-interactive edit requires --yes")
        if not yes:
            console.print(file.read_text(encoding="utf-8"))
            if not typer.confirm("Commit this typed override as a new revision?"):
                raise typer.Abort()
        store, revision = run_generation(
            project=project,
            scope=[component],
            output_dir=_output(output_dir),
            files=[],
            idea=None,
            stdin_enabled=False,
            answers=None,
            profile=None,
            region=None,
            target_providers=None,
            topology=None,
            archetypes=[],
            allow_assumptions=False,
            override=file,
            offline=True,
            edit_only=True,
        )
        bundle, manifest = export_revision(store, revision, normalize_formats("core"), [component])
        _print_result(store, revision, bundle, manifest)
    except BaseException as exc:
        _fail(exc)


@app.command("validate")
def validate_project(
    project: str,
    revision: Annotated[int | None, typer.Option("--revision")] = None,
    scope: Annotated[str | None, typer.Option("--scope")] = None,
    strict: Annotated[bool, typer.Option("--strict")] = False,
    output_dir: OutputDir = None,
) -> None:
    try:
        store = ProjectStore(_output(output_dir), project)
        design = store.load_design(revision)
        graph = store.load_graph(revision)
        selected = scope.split(",") if scope else list(design.components)
        diagnostics = validate_design(design, graph, selected, strict)
        console.print_json(
            data={
                "scope_valid": not any(item.severity == "error" for item in diagnostics),
                "project_complete": store.load_manifest(revision).project_complete,
                "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
            }
        )
        if any(item.severity == "error" for item in diagnostics):
            raise ValidationError("validation failed")
    except Exception as exc:
        _fail(exc)


@app.command("export")
def export_project(
    project: str,
    revision: Annotated[int | None, typer.Option("--revision")] = None,
    formats: Annotated[str, typer.Option("--formats")] = "all",
    offline: Annotated[bool, typer.Option("--offline")] = False,
    output_dir: OutputDir = None,
) -> None:
    """Re-render a saved revision into a new export bundle (no model calls)."""
    del offline
    try:
        store = ProjectStore(_output(output_dir), project)
        number = revision or store.metadata().latest_revision
        design = store.load_design(number)
        bundle, manifest = export_revision(
            store,
            number,
            normalize_formats(formats),
            review_scope(design.components),
        )
        _print_result(store, number, bundle, manifest)
    except BaseException as exc:
        _fail(exc)


@app.command("diff")
def diff_revisions(
    project: str,
    rev_a: int,
    rev_b: int,
    output_dir: OutputDir = None,
) -> None:
    try:
        store = ProjectStore(_output(output_dir), project)
        left = json_bytes(store.load_design(rev_a)).decode().splitlines()
        right = json_bytes(store.load_design(rev_b)).decode().splitlines()
        console.print(
            "\n".join(
                difflib.unified_diff(
                    left, right, f"revision-{rev_a}", f"revision-{rev_b}", lineterm=""
                )
            )
        )
    except Exception as exc:
        _fail(exc)


@app.command("simulate")
def simulate(
    project: str,
    scenario: Annotated[Path, typer.Option("--scenario")],
    revision: Annotated[int | None, typer.Option("--revision")] = None,
    output_dir: OutputDir = None,
) -> None:
    try:
        store = ProjectStore(_output(output_dir), project)
        store.load_design(revision)
        console.print_json(data=simulate_scenario(load_structured(scenario)))
    except Exception as exc:
        _fail(exc)


@app.command("doctor")
def doctor(check_provider: Annotated[bool, typer.Option("--check-provider")] = False) -> None:
    """Check configuration presence (never prints secrets) and optional tool versions."""
    from archai.architect_providers.factory import PROVIDERS, api_key_for

    settings = config.load_settings()
    env_files = [str(path) for path in config._env_files() if path.exists()]
    try:
        roles = config.parse_role_models(settings.role_models)
    except ValueError as exc:
        roles = {"error": (str(exc), None)}
    checks: dict[str, Any] = {
        "python": sys.version.split()[0],
        "archai": __version__,
        "config_files": env_files or "none found",
        "output_dir": str(settings.output_dir),
        "architect_provider": settings.architect_provider,
        "architect_model": settings.architect_model or "provider default",
        "role_models": {key: ":".join(filter(None, value)) for key, value in roles.items()}
        or "all roles use the default architect",
    }
    for name in PROVIDERS:
        checks[f"{name}_configuration"] = "configured" if api_key_for(settings, name) else "missing"
    checks.update(
        {
            "pdf_renderer": "reportlab available" if find_spec("reportlab") else "missing",
            "png_renderer": "pillow available" if find_spec("PIL") else "missing",
            "terraform": shutil.which("terraform")
            or "not installed (IaC is generated, not validated)",
            "provider_network_probe": "not requested",
        }
    )
    if check_provider:
        checks["provider_network_probe"] = (
            "not run: doctor never makes an unbounded or hidden billed call"
        )
    console.print_json(data=checks)


# ---------------------------------------------------------------- configuration files


def _env_path(global_config: bool) -> Path:
    return config.user_env_file() if global_config else Path(".env")


def _write_env(path: Path, values: dict[str, str | None]) -> None:
    """Set (or, for None, remove) keys in a private .env file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("refusing to write .env through a symlink or non-file")
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    os.chmod(path, 0o600)
    for key, value in values.items():
        if value is None:
            unset_key(str(path), key)
        else:
            set_key(str(path), key, value)


def _role_models_in(path: Path) -> dict[str, tuple[str, str | None]]:
    current = dotenv_values(path).get("ARCHAI_ROLE_MODELS") if path.exists() else None
    return config.parse_role_models(current)


def _format_role_models(mapping: dict[str, tuple[str, str | None]]) -> str | None:
    if not mapping:
        return None
    return ",".join(
        f"{role}={provider}" + (f":{model}" if model else "")
        for role, (provider, model) in sorted(mapping.items())
    )


def _shadowed(keys: list[str]) -> list[str]:
    return [key for key in keys if key in os.environ]


@app.command("setup")
def setup(
    global_config: Annotated[
        bool,
        typer.Option("--global", help="Save to ~/.config/archai/.env instead of ./.env."),
    ] = False,
) -> None:
    """Configure architect providers, models, and API keys in a local, private .env file."""
    from archai.architect_providers.factory import DEFAULT_MODELS, PROVIDERS

    names = ", ".join(PROVIDERS)
    if not _is_interactive():
        err_console.print(
            "Interactive setup requires a terminal. Use `archai model use PROVIDER MODEL` or set "
            "ARCHAI_ARCHITECT_PROVIDER and the provider's API key variable instead."
        )
        raise typer.Exit(2)
    current = config.load_settings()
    provider = typer.prompt(
        f"Architect provider ({names})", default=current.architect_provider
    ).lower()
    if provider not in PROVIDERS:
        _fail(ValueError(f"architect provider must be one of {names}"))
    default_model = (
        current.architect_model
        if provider == current.architect_provider and current.architect_model
        else DEFAULT_MODELS[provider]
    )
    console.print(
        f"Suggested {PROVIDERS[provider].label} models: {', '.join(PROVIDERS[provider].suggested)}"
    )
    model = typer.prompt("Model ID", default=default_model).strip()
    if not model:
        _fail(ValueError("model ID cannot be empty"))
    console.print(
        "ArchAI sends requirements and design context to the chosen provider. API usage may be "
        "billed. Use --offline for a deterministic design without model calls."
    )
    key = typer.prompt(
        "API key (leave blank to use an existing environment key)",
        default="",
        hide_input=True,
        show_default=False,
    )
    env_path = _env_path(global_config)
    values: dict[str, str | None] = {
        "ARCHAI_ARCHITECT_PROVIDER": provider,
        "ARCHAI_ARCHITECT_MODEL": model,
    }
    if key:
        values[PROVIDERS[provider].key_envs[0]] = key
    try:
        _write_env(env_path, values)
    except ValueError as exc:
        _fail(exc)
    with contextlib.suppress(typer.Abort):
        other = (
            typer.prompt(
                "Second provider to cross-check designs as the Design Verifier (blank to skip)",
                default="",
                show_default=False,
            )
            .strip()
            .lower()
        )
        if other and other in PROVIDERS:
            other_model = typer.prompt(f"{other} model ID", default=DEFAULT_MODELS[other])
            other_key = typer.prompt(
                f"{other} API key (blank to keep existing)",
                default="",
                hide_input=True,
                show_default=False,
            )
            roles = _role_models_in(env_path)
            roles["verifier"] = (other, other_model)
            extra: dict[str, str | None] = {"ARCHAI_ROLE_MODELS": _format_role_models(roles)}
            if other_key:
                extra[PROVIDERS[other].key_envs[0]] = other_key
            _write_env(env_path, extra)
    console.print(f"Saved {provider} setup to {env_path}. Run `archai model show` to check.")


@model_app.command("show")
def model_show() -> None:
    """Show which provider and model each architect role uses, and which keys are configured."""
    from archai.architect_providers.factory import PROVIDERS, api_key_for, resolve_role_bindings

    try:
        settings = config.load_settings()
        bindings = resolve_role_bindings(settings, None, None)
    except (ValueError, ArchAIError) as exc:
        _fail(exc)
        return
    from archai.application.supervisor import ROLE_NAMES

    roles = Table(title="Architect team", header_style="bold", title_justify="left")
    roles.add_column("Role")
    roles.add_column("Provider")
    roles.add_column("Model")
    roles.add_column("API key")
    for role, binding in bindings.items():
        has_key = api_key_for(settings, binding.provider) is not None
        roles.add_row(
            ROLE_NAMES[role],
            binding.provider,
            binding.model,
            "[green]configured[/green]" if has_key else "[red]missing[/red]",
        )
    console.print(roles)
    providers = Table(title="Providers", header_style="bold", title_justify="left")
    providers.add_column("Provider")
    providers.add_column("Default model")
    providers.add_column("Key variable")
    providers.add_column("Key")
    for name, info in PROVIDERS.items():
        providers.add_row(
            name,
            info.default_model,
            info.key_envs[0],
            "configured" if api_key_for(settings, name) else "—",
        )
    console.print(providers)
    files = [str(path) for path in config._env_files() if path.exists()]
    console.print(f"Config files: {', '.join(files) or 'none'} (environment variables win)")
    console.print(
        "Switch with `archai model use PROVIDER [MODEL]`; per role with `--role verifier`."
    )


@model_app.command("list")
def model_list(
    provider: Annotated[str | None, typer.Argument(help="Provider to list.")] = None,
    remote: Annotated[
        bool,
        typer.Option("--remote", help="Ask the provider which models your key can use (free)."),
    ] = False,
) -> None:
    """List suggested models, or the models your API key can access with --remote."""
    from archai.architect_providers.factory import (
        PROVIDERS,
        check_provider,
        list_remote_models,
    )

    try:
        names = [check_provider(provider)] if provider else list(PROVIDERS)
        settings = config.load_settings()
        for name in names:
            info = PROVIDERS[name]
            console.rule(f"[bold]{info.label}[/bold] ({name})", align="left")
            console.print(f"[dim]{info.notes}[/dim]")
            for model in info.suggested:
                marker = " [green](default)[/green]" if model == info.default_model else ""
                console.print(f"  {model}{marker}")
            if remote:
                try:
                    available = list_remote_models(settings, name)
                except ArchAIError as exc:
                    console.print(f"  [yellow]{exc}[/yellow]")
                    continue
                console.print(f"  [bold]Available to your key ({len(available)}):[/bold]")
                console.print("  " + ", ".join(available))
    except BaseException as exc:
        _fail(exc)


@model_app.command("use")
def model_use(
    provider: Annotated[str, typer.Argument(help="openai, anthropic, gemini, or deepseek.")],
    model: Annotated[
        str | None, typer.Argument(help="Model ID (defaults to the provider's default).")
    ] = None,
    role: Annotated[
        str | None,
        typer.Option(
            "--role", help="Only this role: requirements, cloud, api, security, verifier."
        ),
    ] = None,
    key: Annotated[
        bool, typer.Option("--key", help="Prompt for this provider's API key and save it.")
    ] = False,
    global_config: Annotated[
        bool, typer.Option("--global", help="Save to ~/.config/archai/.env instead of ./.env.")
    ] = False,
) -> None:
    """Switch the architect provider/model for all roles, or for one role with --role."""
    from archai.architect_providers.factory import (
        DEFAULT_MODELS,
        PROVIDERS,
        api_key_for,
        check_provider,
    )

    try:
        name = check_provider(provider)
        chosen = model or DEFAULT_MODELS[name]
        path = _env_path(global_config)
        values: dict[str, str | None] = {}
        if role:
            if role not in config.ROLE_KEYS:
                raise ValueError(
                    f"unknown role {role!r}; choose from {', '.join(config.ROLE_KEYS)}"
                )
            roles = _role_models_in(path)
            roles[role] = (name, chosen)
            values["ARCHAI_ROLE_MODELS"] = _format_role_models(roles)
        else:
            values["ARCHAI_ARCHITECT_PROVIDER"] = name
            values["ARCHAI_ARCHITECT_MODEL"] = chosen
        if key:
            if not _is_interactive():
                raise ValueError("--key needs a terminal; set the key variable instead")
            secret = typer.prompt(
                f"{PROVIDERS[name].label} API key", hide_input=True, default="", show_default=False
            )
            if secret:
                values[PROVIDERS[name].key_envs[0]] = secret
        _write_env(path, values)
        target = f"role {role}" if role else "all architect roles"
        console.print(f"[green]Using {name} · {chosen} for {target}[/green] (saved to {path})")
        if not key and api_key_for(config.load_settings(), name) is None:
            console.print(
                f"[yellow]No {name} API key found.[/yellow] Add one with "
                f"`archai model use {name} {chosen} --key` or set {PROVIDERS[name].key_envs[0]}."
            )
        hidden = _shadowed(
            ["ARCHAI_ARCHITECT_PROVIDER", "ARCHAI_ARCHITECT_MODEL"]
            if not role
            else ["ARCHAI_ROLE_MODELS"]
        )
        if hidden:
            console.print(
                f"[yellow]Note:[/yellow] {', '.join(hidden)} is set in your shell environment and "
                "overrides the .env file; unset it to use this setting."
            )
    except BaseException as exc:
        _fail(exc)


@model_app.command("clear")
def model_clear(
    role: Annotated[str | None, typer.Option("--role", help="Clear only this role.")] = None,
    global_config: Annotated[bool, typer.Option("--global")] = False,
) -> None:
    """Remove per-role model overrides so every role uses the default architect."""
    try:
        path = _env_path(global_config)
        roles = _role_models_in(path)
        if role:
            roles.pop(role, None)
        else:
            roles = {}
        _write_env(path, {"ARCHAI_ROLE_MODELS": _format_role_models(roles)})
        console.print("Cleared " + (f"the {role} override" if role else "all role overrides"))
    except BaseException as exc:
        _fail(exc)


@catalog_app.command("show")
def catalog_show() -> None:
    from importlib.resources import files

    for name in ("capabilities.yaml", "owasp_llm_2025.yaml"):
        console.rule(name)
        console.print(files("archai.resources.catalogs").joinpath(name).read_text())


@catalog_app.command("validate")
def catalog_validate() -> None:
    from importlib.resources import files

    for name in ("capabilities.yaml", "owasp_llm_2025.yaml"):
        value = yaml.safe_load(files("archai.resources.catalogs").joinpath(name).read_text())
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            _fail(ValueError(f"invalid packaged catalog {name}"))
    console.print("Packaged catalogs are structurally valid.")


@catalog_app.command("import")
def catalog_import(path: Path) -> None:
    value = load_structured(path)
    console.print_json(
        data={
            "validated": True,
            "keys": sorted(value),
            "note": "Catalog import validation does not silently replace packaged catalogs.",
        }
    )


def _component_value(design: Any, component: str) -> Any:
    mapping = {
        "requirements": {"requirements": design.requirements, "prd": design.prd},
        "system": design.services,
        "api": design.api_contracts,
        "routing": {
            "endpoints": design.endpoints,
            "model_aliases": design.model_aliases,
            "routing_policy": design.routing_policy,
        },
        "budget": design.budget_policy,
        "cache": design.cache_policy,
        "workflow": design.workflows,
        "rag": design.rag_pipeline,
        "data": design.data_stores,
        "infra": design.deployment,
        "resilience": {"queue_policy": design.queue_policy, "resilience": design.resilience},
        "auth": design.identity_policy,
        "guard": design.guardrails,
        "security": {"threats": design.threats, "risks": design.risks},
        "observe": design.observability,
        "eval": design.eval_plan,
        "cost": {"capacity": design.capacity, "costs": design.costs},
    }
    return mapping.get(component)


if __name__ == "__main__":
    app()
