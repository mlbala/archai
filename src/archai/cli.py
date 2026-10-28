from __future__ import annotations

import difflib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from dotenv import set_key
from pydantic import ValidationError as PydanticValidationError
from rich.console import Console
from rich.table import Table

from archai import __version__
from archai.application.registry import COMPONENTS
from archai.application.service import (
    add_lock,
    auto_scope,
    generation_plan,
    remove_lock,
    run_generation,
)
from archai.compilers.export import export_revision, normalize_formats
from archai.config import Settings
from archai.domain.validation import validate_design
from archai.errors import ArchAIError, ValidationError
from archai.ingestion import load_structured
from archai.persistence.store import ProjectStore, json_bytes
from archai.simulators.scenario import simulate_scenario

console = Console()
err_console = Console(stderr=True)
app = typer.Typer(
    name="arch",
    help="ArchAI: design managed-API enterprise AI systems without deploying them.",
    no_args_is_help=False,
    rich_markup_mode="markdown",
)
catalog_app = typer.Typer(help="Inspect and validate trusted packaged catalogs.")
app.add_typer(catalog_app, name="catalog")


def _fail(exc: Exception) -> None:
    if isinstance(exc, typer.Exit):
        raise exc
    if isinstance(exc, ArchAIError):
        code = exc.exit_code
    elif isinstance(exc, (ValueError, PydanticValidationError, FileNotFoundError)):
        code = 2
    else:
        code = 1
    err_console.print(f"[red]Error:[/red] {exc}", soft_wrap=True)
    raise typer.Exit(code) from exc


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
        _execute_generation(project=legacy_project, scope=auto_scope(), files=legacy_file or [])
        return
    table = Table(title="ArchAI guided component selector")
    table.add_column("Command")
    table.add_column("Scope")
    table.add_row("arch auto", "Complete applicable design, validation, documents, and artifacts")
    for name, spec in COMPONENTS.items():
        table.add_row(f"arch {name}", f"{spec.title} only")
    console.print(table)
    console.print(
        "Use `arch COMMAND --help`. Automatic mode never prompts or deploys infrastructure."
    )


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
        typer.Option("--architect-provider", help="Architect provider: openai or gemini."),
    ] = None,
    architect_model: Annotated[
        str | None, typer.Option("--architect-model", help="Designer model identifier.")
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
    output_dir: Annotated[Path, typer.Option("--output-dir", help="Project store root.")] = Path(
        "output"
    ),
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
    del mode, non_interactive, sections
    component = str(ctx.info_name)
    if component == "design":
        component = "system"
    try:
        store = ProjectStore(output_dir, project)
        if architect_provider and architect_provider.lower() not in {"gemini", "openai"}:
            raise ValueError("architect provider must be openai or gemini")
        if audience not in {"technical", "executive"}:
            raise ValueError("--audience must be technical or executive")
        if template != "default":
            raise ValueError("unknown trusted document template")
        if view and component != "diagram":
            raise ValueError("--view is valid only for the diagram command")
        if view and view not in {
            "system",
            "deployment",
            "request",
            "ingestion",
            "guardrails",
            "workflow",
            "fallback",
            "budget",
            "recovery",
        }:
            raise ValueError("unknown diagram view")
        selected_files = list(files or [])
        if policy:
            selected_files.append(policy)
        if component in {"doc", "diagram"} and not any(
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
        ):
            number = base_revision or store.metadata().latest_revision
            selected_scope = scope.split(",") if scope else None
            bundle, manifest = export_revision(
                store, number, normalize_formats(formats), selected_scope
            )
            _print_result(store, number, bundle, manifest)
            return
        if scope and component != "doc":
            raise ValueError("--scope is valid only for the doc command")
        if dry_run:
            console.print_json(data=generation_plan(store, [component], selected_files, formats))
            return
        store, revision = run_generation(
            project=project,
            scope=[component],
            output_dir=output_dir,
            files=selected_files,
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
        )
        export_scope = scope.split(",") if scope else [component]
        bundle, manifest = export_revision(
            store, revision, normalize_formats(formats), export_scope
        )
        _print_result(store, revision, bundle, manifest)
    except Exception as exc:
        _fail(exc)


for _name, _spec in COMPONENTS.items():
    app.command(
        name=_name,
        help=f"Design {_spec.title.lower()} only and create its standalone document.",
    )(component_entry)
app.command(name="design", help="Alias of `arch system`; not a complete design.")(component_entry)


@app.command("auto")
def auto(
    project: Annotated[str | None, typer.Option("--project", "-p")] = None,
    files: Annotated[list[Path] | None, typer.Option("--file", "-f")] = None,
    idea: Annotated[str | None, typer.Option("--idea", "-i")] = None,
    stdin: Annotated[bool, typer.Option("--stdin")] = False,
    answers: Annotated[Path | None, typer.Option("--answers")] = None,
    architect_provider: Annotated[str | None, typer.Option("--architect-provider")] = None,
    architect_model: Annotated[str | None, typer.Option("--architect-model")] = None,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
    target_providers: Annotated[str | None, typer.Option("--target-providers")] = None,
    topology: Annotated[str | None, typer.Option("--topology")] = None,
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    archetype: Annotated[list[str] | None, typer.Option("--archetype")] = None,
    base_revision: Annotated[int | None, typer.Option("--base-revision")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    non_interactive: Annotated[bool, typer.Option("--non-interactive")] = True,
    allow_assumptions: Annotated[bool, typer.Option("--allow-assumptions")] = False,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
    formats: Annotated[str, typer.Option("--formats")] = "all",
) -> None:
    del non_interactive
    if not project:
        err_console.print(
            "Provide a project and requirements, for example:\n"
            "  archai auto -p my-project -f requirements.yaml --formats core\n"
            "Run `archai setup` to configure OpenAI or Gemini; use `archai auto --help` for options."
        )
        raise typer.Exit(2)
    if architect_provider and architect_provider.lower() not in {"openai", "gemini"}:
        _fail(ValueError("architect provider must be openai or gemini"))
    selected_files = list(files or [])
    if policy:
        selected_files.append(policy)
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
    )


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
    output_dir: Path = Path("output"),
    formats: str = "core",
    base_revision: int | None = None,
    architect_provider: str | None = None,
    architect_model: str | None = None,
) -> None:
    try:
        store = ProjectStore(output_dir, project)
        if dry_run:
            console.print_json(data=generation_plan(store, scope, files, formats))
            return
        store, revision = run_generation(
            project=project,
            scope=scope,
            output_dir=output_dir,
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
            requested_base_revision=base_revision,
            architect_provider=architect_provider,
            architect_model=architect_model,
        )
        bundle, manifest = export_revision(store, revision, normalize_formats(formats), scope)
        _print_result(store, revision, bundle, manifest)
    except Exception as exc:
        _fail(exc)


def _print_result(store: ProjectStore, revision: int, bundle: Path, manifest: Any) -> None:
    failed = [item for item in manifest.artifacts if item.status == "failed"]
    console.print(f"[green]Accepted revision {revision}[/green] for `{store.slug}`")
    console.print(f"Export bundle: {bundle}")
    if failed:
        for item in failed:
            err_console.print(f"[yellow]Export failed:[/yellow] {item.path}: {item.reason}")
        raise typer.Exit(5)


@app.command("update")
def update(
    project: str,
    files: Annotated[list[Path] | None, typer.Option("--file", "-f")] = None,
    instruction: Annotated[str | None, typer.Option("--instruction", "-i")] = None,
    answers: Annotated[Path | None, typer.Option("--answers")] = None,
    non_interactive: Annotated[bool, typer.Option("--non-interactive")] = True,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
    formats: Annotated[str, typer.Option("--formats")] = "core",
) -> None:
    del non_interactive
    _execute_generation(
        project=project,
        scope=auto_scope(),
        files=files or [],
        idea=instruction,
        answers=answers,
        output_dir=output_dir,
        formats=formats,
    )


@app.command("inspect")
def inspect_project(
    project: str,
    revision: Annotated[int | None, typer.Option("--revision")] = None,
    component: Annotated[str | None, typer.Option("--component")] = None,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
) -> None:
    try:
        store = ProjectStore(output_dir, project)
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
def list_projects(
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
) -> None:
    if not output_dir.exists():
        console.print("No projects.")
        return
    for path in sorted(output_dir.iterdir()):
        if path.is_dir() and (path / "project.json").exists():
            metadata = json.loads((path / "project.json").read_text())
            console.print(
                f"{path.name}\trevision={metadata['latest_revision']}\tcomplete={metadata.get('latest_complete_revision')}"
            )


@app.command("lock")
def lock_component(
    project: Annotated[str, typer.Option("--project", "-p")],
    component: Annotated[str, typer.Option("--component")],
    field: Annotated[str | None, typer.Option("--field")] = None,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
) -> None:
    try:
        store = ProjectStore(output_dir, project)
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
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
) -> None:
    try:
        store = ProjectStore(output_dir, project)
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
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
) -> None:
    if non_interactive and not yes:
        _fail(ValueError("non-interactive edit requires --yes"))
    if not yes:
        console.print(file.read_text(encoding="utf-8"))
        if not typer.confirm("Commit this typed override as a new revision?"):
            raise typer.Abort()
    try:
        store, revision = run_generation(
            project=project,
            scope=[component],
            output_dir=output_dir,
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
        )
        bundle, manifest = export_revision(store, revision, normalize_formats("core"), [component])
        _print_result(store, revision, bundle, manifest)
    except Exception as exc:
        _fail(exc)


@app.command("validate")
def validate_project(
    project: str,
    revision: Annotated[int | None, typer.Option("--revision")] = None,
    scope: Annotated[str | None, typer.Option("--scope")] = None,
    strict: Annotated[bool, typer.Option("--strict")] = False,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
) -> None:
    try:
        store = ProjectStore(output_dir, project)
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
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
) -> None:
    del offline
    try:
        store = ProjectStore(output_dir, project)
        number = revision or store.metadata().latest_revision
        bundle, manifest = export_revision(store, number, normalize_formats(formats))
        _print_result(store, number, bundle, manifest)
    except Exception as exc:
        _fail(exc)


@app.command("diff")
def diff_revisions(
    project: str,
    rev_a: int,
    rev_b: int,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
) -> None:
    try:
        store = ProjectStore(output_dir, project)
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
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
) -> None:
    try:
        store = ProjectStore(output_dir, project)
        store.load_design(revision)
        console.print_json(data=simulate_scenario(load_structured(scenario)))
    except Exception as exc:
        _fail(exc)


@app.command("resume")
def resume(
    project: str,
    run: Annotated[str, typer.Option("--run")],
    answers: Annotated[Path | None, typer.Option("--answers")] = None,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
    formats: Annotated[str, typer.Option("--formats")] = "core",
) -> None:
    try:
        store = ProjectStore(output_dir, project)
        run_state, inputs = store.load_run(run)
        if run_state.status == "accepted":
            console.print(f"Run {run} is already accepted; no resume is needed.")
            return
        if inputs is None:
            raise ValueError(f"run {run!r} has no saved input snapshot")
        store, revision = run_generation(
            project=project,
            scope=run_state.selected_scope,
            output_dir=output_dir,
            files=[inputs],
            idea=None,
            stdin_enabled=False,
            answers=answers,
            profile=None,
            region=None,
            target_providers=None,
            topology=None,
            archetypes=[],
            allow_assumptions=False,
            requested_base_revision=run_state.base_revision,
        )
        bundle, manifest = export_revision(
            store, revision, normalize_formats(formats), run_state.selected_scope
        )
        _print_result(store, revision, bundle, manifest)
    except Exception as exc:
        _fail(exc)


@app.command("doctor")
def doctor(check_provider: Annotated[bool, typer.Option("--check-provider")] = False) -> None:
    settings = Settings()
    checks = {
        "python": sys.version.split()[0],
        "terraform": shutil.which("terraform") or "not installed",
        "architect_provider": settings.architect_provider,
        "architect_model": settings.architect_model or "provider default",
        "openai_configuration": "configured" if settings.openai_api_key else "missing",
        "gemini_configuration": "configured"
        if settings.gemini_api_key
        else "missing (only generation requiring Gemini is blocked)",
        "provider_network_probe": "not requested",
    }
    if check_provider:
        checks["provider_network_probe"] = (
            "not run: doctor never makes an unbounded or hidden billed call"
        )
    console.print_json(data=checks)


@app.command("setup")
def setup() -> None:
    """Configure an architect provider and API key in a local, gitignored .env file."""
    if not _is_interactive():
        err_console.print(
            "Interactive setup requires a terminal. Set ARCHAI_ARCHITECT_PROVIDER and "
            "OPENAI_API_KEY or GEMINI_API_KEY in your environment instead."
        )
        raise typer.Exit(2)
    from archai.architect_providers.factory import DEFAULT_MODELS

    current = Settings()
    provider = typer.prompt(
        "Architect provider (openai or gemini)", default=current.architect_provider
    ).lower()
    if provider not in DEFAULT_MODELS:
        _fail(ValueError("architect provider must be openai or gemini"))
    default_model = (
        current.architect_model
        if provider == current.architect_provider and current.architect_model
        else DEFAULT_MODELS[provider]
    )
    model = typer.prompt("Model ID", default=default_model).strip()
    if not model:
        _fail(ValueError("model ID cannot be empty"))
    console.print(
        "ArchAI sends prose requirements to the chosen provider for extraction. "
        "API usage may be billed. Structured YAML/JSON can be used without a model call."
    )
    key = typer.prompt(
        "API key (leave blank to use an existing environment key)",
        default="",
        hide_input=True,
        show_default=False,
    )
    env_path = Path(".env")
    if env_path.is_symlink() or (env_path.exists() and not env_path.is_file()):
        _fail(ValueError("refusing to write .env through a symlink or non-file"))
    if not env_path.exists():
        descriptor = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    os.chmod(env_path, 0o600)
    set_key(str(env_path), "ARCHAI_ARCHITECT_PROVIDER", provider)
    set_key(str(env_path), "ARCHAI_ARCHITECT_MODEL", model)
    if key:
        set_key(
            str(env_path),
            "ARCHAI_OPENAI_API_KEY" if provider == "openai" else "ARCHAI_GEMINI_API_KEY",
            key,
        )
    console.print(f"Saved {provider} setup to .env. Run `archai doctor` to check configuration.")


def _is_interactive() -> bool:
    return sys.stdin.isatty()


@catalog_app.command("show")
def catalog_show() -> None:
    from importlib.resources import files

    catalog = files("archai.resources.catalogs").joinpath("capabilities.yaml").read_text()
    console.print(catalog)


@catalog_app.command("validate")
def catalog_validate() -> None:
    from importlib.resources import files

    value = yaml.safe_load(
        files("archai.resources.catalogs").joinpath("capabilities.yaml").read_text()
    )
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        _fail(ValueError("invalid packaged catalog"))
    console.print("Packaged capability catalog is structurally valid.")


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
        "requirements": design.requirements,
        "system": design.services,
        "api": design.api_contracts,
        "routing": {"endpoints": design.endpoints, "model_aliases": design.model_aliases},
        "budget": design.budget_policy,
        "cache": design.cache_policy,
        "workflow": design.workflows,
        "rag": design.data_stores,
        "data": design.data_stores,
        "infra": design.deployment,
        "resilience": design.queue_policy,
        "auth": design.identity_policy,
        "guard": design.guardrails,
        "security": design.risks,
        "observe": design.observability,
        "cost": {"capacity": design.capacity, "costs": design.costs},
    }
    return mapping.get(component)


if __name__ == "__main__":
    app()
