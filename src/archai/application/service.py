from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import yaml
from pydantic import ValidationError as PydanticValidationError

from archai import config
from archai.application.designer import apply_scope, baseline_component, build_graph
from archai.application.extraction import apply_quoted_suggestions, interview_suggestions
from archai.application.merge import enforce_invariants
from archai.application.registry import (
    AUTO_COMPONENTS,
    COMPILED_COMPONENTS,
    COMPONENTS,
    DOCUMENT_PACKAGES,
)
from archai.application.supervisor import (
    ROLE_COMPONENTS,
    ROLE_NAMES,
    STEP_TITLES,
    CallBudget,
    DesignTeam,
    NullReporter,
    ProgressReporter,
    Supervisor,
    analyze_requirements,
)
from archai.architect_providers.factory import (
    DEFAULT_MODELS,
    RoleBinding,
    api_key_for,
    create_provider,
    resolve_role_bindings,
    selected_model,
)
from archai.domain.validation import validate_design
from archai.errors import (
    IncompleteRequirementsError,
    InterviewPaused,
    ProviderError,
    StateConflictError,
    ValidationError,
)
from archai.ingestion import merge_inputs, parse_requirements, sha256_bytes
from archai.interview.questions import missing_questions
from archai.interview.session import Suggestion
from archai.persistence.store import ProjectStore, json_bytes
from archai.schemas.models import (
    ComponentState,
    ComponentStatus,
    DecisionLock,
    EnterpriseDesign,
    ManualDecision,
    RequirementsSpec,
    RevisionManifest,
    RunState,
    ValidationDiagnostic,
)

OWNED_ROOTS: dict[str, set[str]] = {
    "requirements": {"requirements", "prd"},
    "system": {"services"},
    "api": {"api_contracts"},
    "routing": {"endpoints", "model_aliases", "routing_policy"},
    "budget": {"budget_policy"},
    "cache": {"cache_policy"},
    "workflow": {"workflows"},
    "rag": {"rag_pipeline"},
    "data": {"data_stores"},
    "infra": {"deployment"},
    "resilience": {"queue_policy", "resilience"},
    "auth": {"identity_policy"},
    "guard": {"guardrails"},
    "security": {"risks", "threats"},
    "observe": {"observability"},
    "eval": {"eval_plan"},
    "cost": {"capacity", "costs"},
}
DERIVED_ROOTS = {"capacity", "costs"}


class Interviewer(Protocol):
    def interview(
        self,
        data: dict[str, Any],
        *,
        suggestions: dict[str, Suggestion],
        clarifying_questions: list[str],
        persist: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]: ...

    def fix(
        self,
        data: dict[str, Any],
        fields: list[str],
        reason: str,
        persist: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]: ...


def generation_plan(
    store: ProjectStore,
    scope: list[str],
    files: list[Path],
    formats: str,
) -> dict[str, Any]:
    existing = store.project_file.exists()
    roles = sorted(
        {
            role
            for name in scope
            if (spec := COMPONENTS.get(name)) is not None and (role := spec.role) is not None
        }
        | {"Design Verifier and Compiler"}
    )
    documents = [COMPONENTS[name].outputs[0] for name in scope if name in COMPONENTS]
    if "doc" in scope:
        documents.extend(spec.outputs[0] for spec in DOCUMENT_PACKAGES.values())
    return {
        "project": store.slug,
        "baseline_revision": store.metadata().latest_revision if existing else 0,
        "scope": scope,
        "roles": roles,
        "inputs": [str(path) for path in files],
        "writes": [f"revision state for {name}" for name in scope if name in COMPONENTS],
        "documents": documents,
        "invalidates": sorted(
            {
                item
                for name in scope
                if name in COMPONENTS
                for item in COMPONENTS[name].invalidates
                if item not in scope
            }
        ),
        "formats": formats,
        "llm_calls": 0,
        "note": "Dry-run performs no writes, provider calls, or renderer execution.",
    }


def build_team(
    settings: config.Settings,
    architect_provider: str | None,
    architect_model: str | None,
    role_models: list[str] | None,
    offline: bool,
    reporter: ProgressReporter,
) -> DesignTeam | None:
    """Return the configured architect team, or None for the deterministic baseline."""
    if offline:
        return None
    bindings = resolve_role_bindings(settings, architect_provider, architect_model, role_models)
    keyed = [name for name in DEFAULT_MODELS if api_key_for(settings, name)]
    default = bindings["requirements"]
    if architect_provider is None and default.provider not in keyed:
        if not keyed:
            return None
        other = keyed[0]
        reporter.message(f"No {default.provider} API key; using {other} for the design team.")
        bindings = resolve_role_bindings(settings, other, None, role_models)
        default = bindings["requirements"]
    for role, binding in list(bindings.items()):
        if binding.provider != default.provider and binding.provider not in keyed:
            reporter.message(
                f"No {binding.provider} key for {ROLE_NAMES[role]}; using {default.provider}."
            )
            bindings[role] = default
    alternates: dict[str, RoleBinding] = {}
    for name in DEFAULT_MODELS:
        others = [other for other in keyed if other != name]
        if others:
            candidate = next(
                (b for b in bindings.values() if b.provider == others[0]),
                RoleBinding(others[0], selected_model(settings, others[0], None)),
            )
            alternates[name] = candidate
    return DesignTeam(
        bindings=bindings,
        factory=lambda provider, model: create_provider(settings, provider, model),
        budget=CallBudget(settings.max_generation_calls, settings.max_generation_tokens),
        reporter=reporter,
        alternates=alternates,
    )


def run_generation(
    *,
    project: str,
    scope: list[str],
    output_dir: Path,
    files: list[Path],
    idea: str | None,
    stdin_enabled: bool,
    answers: Path | None,
    profile: str | None,
    region: str | None,
    target_providers: str | None,
    topology: str | None,
    archetypes: list[str],
    allow_assumptions: bool,
    override: Path | None = None,
    requested_base_revision: int | None = None,
    architect_provider: str | None = None,
    architect_model: str | None = None,
    role_models: list[str] | None = None,
    offline: bool = False,
    interviewer: Interviewer | None = None,
    reporter: ProgressReporter | None = None,
    run_id: str | None = None,
    edit_only: bool = False,
) -> tuple[ProjectStore, int]:
    progress = reporter or NullReporter()
    settings = config.load_settings()
    store = ProjectStore(output_dir, project)
    stdin_text = sys.stdin.read() if stdin_enabled else None
    with store.locked():
        metadata = store.initialize()
        base_revision = metadata.latest_revision
        if requested_base_revision is not None and requested_base_revision != base_revision:
            raise StateConflictError(
                f"requested base revision {requested_base_revision} is not latest revision {base_revision}"
            )
        baseline = store.load_design() if base_revision else None
        run_state = RunState(
            id=run_id or uuid4().hex,
            project=store.slug,
            base_revision=base_revision,
            selected_scope=scope,
            status="running",
        )
        store.save_run(run_state)
        team = build_team(
            settings, architect_provider, architect_model, role_models, offline, progress
        )
        run_state.design_mode = "multi-agent" if team else "deterministic-baseline"
        if team:
            run_state.architect_provider = team.bindings["requirements"].provider
            run_state.architect_model = team.bindings["requirements"].model
        try:
            requirements, raw_sources, input_snapshot = _prepare_requirements(
                store=store,
                run_state=run_state,
                baseline=baseline,
                team=team,
                interviewer=interviewer,
                progress=progress,
                files=files,
                idea=idea,
                stdin_text=stdin_text,
                answers=answers,
                profile=profile,
                region=region,
                target_providers=target_providers,
                topology=topology,
                archetypes=archetypes,
                allow_assumptions=allow_assumptions,
            )
        except ProviderError as exc:
            run_state.status = "failed"
            run_state.diagnostics.append(
                ValidationDiagnostic(
                    code="ARCHITECT_PROVIDER_ERROR", severity="error", message=str(exc)
                )
            )
            if team:
                run_state.role_calls = list(team.calls)
            store.save_run(run_state)
            raise
        store.save_run(run_state, input_snapshot)
        locks = store.load_locks()
        locked_selected = {lock.component for lock in locks} & set(scope)
        if baseline and locked_selected and requirements != baseline.requirements:
            raise StateConflictError(
                "Changed requirements affect locked selected components: "
                + ", ".join(sorted(locked_selected))
            )
        for path, text in raw_sources:
            store.save_source(path, text)
        if edit_only:
            if baseline is None:
                raise ValueError("edit requires an existing accepted revision")
            design = baseline.model_copy(deep=True)
            for name in scope:
                state = design.components.get(name)
                if state is None:
                    design.components[name] = ComponentState(
                        name=name, status=ComponentStatus.valid, source="user_set"
                    )
                else:
                    state.status = ComponentStatus.valid
                    state.reason = None
                    state.source = "user_set"
        else:
            design = apply_scope(baseline, store.slug, requirements, scope, locks)
        diagnostics: list[ValidationDiagnostic] = []
        supervisor = Supervisor(
            design,
            scope,
            locks,
            None if edit_only else team,
            progress,
            validator=lambda candidate: validate_design(candidate, build_graph(candidate), scope),
        )
        try:
            result = supervisor.run()
        except ProviderError as exc:
            run_state.status = "failed"
            run_state.role_calls = list(team.calls) if team else []
            run_state.diagnostics.append(
                ValidationDiagnostic(
                    code="ARCHITECT_PROVIDER_ERROR", severity="error", message=str(exc)
                )
            )
            store.save_run(run_state, input_snapshot)
            raise
        diagnostics.extend(result.diagnostics)
        if "cost" in scope and design.components.get("cost") is not None and not edit_only:
            baseline_component(design, "cost")
            progress.step("cost", STEP_TITLES["cost"], "done", "deterministic engine")
        diagnostics.extend(enforce_invariants(design))
        design, manual_diagnostics = reapply_manual_decisions(
            design, store.load_manual_decisions(), scope, locks
        )
        diagnostics.extend(manual_diagnostics)
        if baseline is not None:
            design = restore_locked(design, baseline, locks)
        if override is not None:
            if len(scope) != 1:
                raise ValueError("--override is scoped to exactly one component command")
            design, decisions = apply_override(design, scope[0], override, locks)
            store.save_manual_decisions(store.load_manual_decisions() + decisions)
        graph = build_graph(design)
        next_revision = base_revision + 1
        input_hash = sha256_bytes(json_bytes(requirements))
        for name in scope:
            if name in design.components:
                design.components[name].revision = next_revision
                design.components[name].input_hash = input_hash
        diagnostics.extend(validate_design(design, graph, scope))
        errors = [item for item in diagnostics if item.severity == "error"]
        run_state.role_calls = list(team.calls) if team else []
        if team:
            run_state.architect_usage = {
                "calls": len(team.calls),
                "input_tokens": sum(item.input_tokens or 0 for item in team.calls),
                "output_tokens": sum(item.output_tokens or 0 for item in team.calls),
            }
        if errors:
            run_state.status = "failed"
            run_state.diagnostics = diagnostics
            store.save_run(run_state, input_snapshot)
            raise ValidationError("; ".join(item.message for item in errors))
        valid_components = {
            name
            for name, state in design.components.items()
            if state.status in {ComponentStatus.valid, ComponentStatus.not_applicable}
        }
        required = set(COMPONENTS) - COMPILED_COMPONENTS
        complete = required <= valid_components
        manifest = RevisionManifest(
            project=store.slug,
            revision=next_revision,
            created_at=datetime.now(UTC),
            selected_scope=scope,
            design_sha256=sha256_bytes(json_bytes(design)),
            scope_valid=True,
            project_complete=complete,
            diagnostics=diagnostics,
            locks=locks,
            manual_decisions=store.load_manual_decisions(),
            run_id=run_state.id,
        )
        from archai.compilers.report import revision_documents

        documents = revision_documents(design, graph, diagnostics, scope)
        store.commit_revision(design, graph, manifest, documents, base_revision)
        run_state.status = "accepted"
        run_state.revision = next_revision
        run_state.completed_steps = [
            "requirements",
            *[name for name in scope if name != "requirements"],
            "validation",
            "revision",
        ]
        run_state.diagnostics = diagnostics
        store.save_run(run_state, input_snapshot)
        return store, next_revision


def _prepare_requirements(
    *,
    store: ProjectStore,
    run_state: RunState,
    baseline: EnterpriseDesign | None,
    team: DesignTeam | None,
    interviewer: Interviewer | None,
    progress: ProgressReporter,
    files: list[Path],
    idea: str | None,
    stdin_text: str | None,
    answers: Path | None,
    profile: str | None,
    region: str | None,
    target_providers: str | None,
    topology: str | None,
    archetypes: list[str],
    allow_assumptions: bool,
) -> tuple[RequirementsSpec, list[tuple[Path, str]], dict[str, Any]]:
    no_inputs = (
        not files
        and not idea
        and not stdin_text
        and answers is None
        and profile is None
        and region is None
        and target_providers is None
        and topology is None
        and not archetypes
    )
    raw_sources: list[tuple[Path, str]] = []
    if no_inputs and baseline is None and interviewer is None:
        raise IncompleteRequirementsError("A new project requires -f, -i, --stdin, or --answers")
    if no_inputs and baseline is not None:
        data: dict[str, Any] = baseline.requirements.model_dump(mode="json")
        if interviewer is None:
            return baseline.requirements, raw_sources, data
    else:
        data, raw_sources = merge_inputs(
            files,
            idea,
            stdin_text,
            answers,
            profile or (baseline.requirements.profile if baseline else None),
            region,
            target_providers,
            topology or (baseline.requirements.topology if baseline else None),
            archetypes,
        )
        if baseline:
            baseline_data = baseline.requirements.model_dump(mode="json")
            baseline_data.update(
                {key: value for key, value in data.items() if value not in (None, [], "")}
            )
            data = baseline_data
    prose = [text for path, text in raw_sources if path.suffix.lower() in {".md", ".txt"}]
    if idea:
        prose.append(idea)
    if stdin_text:
        prose.append(stdin_text)

    def persist(snapshot: dict[str, Any]) -> None:
        run_state.status = "interviewing"
        store.save_run(run_state, snapshot)

    store.save_run(run_state, data)
    suggestions: dict[str, Suggestion] = {}
    clarifying: list[str] = []
    if prose and team is not None:
        source = "\n\n".join(prose)
        progress.step("intake", STEP_TITLES["intake"], "running", team.describe("requirements"))
        progress.message(
            f"Sending your requirements to {team.describe('requirements')} for analysis; "
            "provider usage may be billed."
        )
        try:
            analysis = analyze_requirements(team, source, data)
        except ProviderError as exc:
            if exc.fatal:
                raise
            progress.step("intake", STEP_TITLES["intake"], "failed", str(exc)[:80])
            run_state.diagnostics.append(
                ValidationDiagnostic(
                    code="INTAKE_UNAVAILABLE",
                    severity="warning",
                    component="requirements",
                    message=f"Requirements analysis skipped: {exc}",
                )
            )
        else:
            progress.step("intake", STEP_TITLES["intake"], "done", team.last_detail("intake"))
            if interviewer is not None:
                suggestions = interview_suggestions(analysis, data)
                clarifying = list(analysis.clarifying_questions)
            else:
                data = apply_quoted_suggestions(analysis, data, source, allow_assumptions)
                if analysis.clarifying_questions:
                    data["notes"] = "\n".join(
                        filter(
                            None,
                            [
                                data.get("notes"),
                                "Open questions from the requirements architect: "
                                + " | ".join(analysis.clarifying_questions[:5]),
                            ],
                        )
                    )
    if interviewer is not None:
        try:
            data = interviewer.interview(
                data, suggestions=suggestions, clarifying_questions=clarifying, persist=persist
            )
        except (InterviewPaused, KeyboardInterrupt, EOFError) as exc:
            run_state.status = "interviewing"
            store.save_run(run_state, data)
            raise InterviewPaused("Your answers so far are saved.", run_id=run_state.id) from exc
        run_state.status = "running"
    for _attempt in range(4):
        try:
            requirements = parse_requirements(data)
            return requirements, raw_sources, data
        except IncompleteRequirementsError as exc:
            questions = missing_questions(data, critical_only=True)
            ids = [question.id for question in questions]
            if interviewer is not None and ids:
                data = interviewer.fix(
                    data, [q.field for q in questions], "Some answers are still missing.", persist
                )
                continue
            run_state.status = "blocked"
            run_state.diagnostics.append(
                ValidationDiagnostic(
                    code="REQUIREMENTS_INCOMPLETE",
                    severity="error",
                    component="requirements",
                    message=str(exc),
                )
            )
            store.save_run(run_state, data)
            raise IncompleteRequirementsError(
                f"{exc}. Resume with run ID {run_state.id}", question_ids=ids, run_id=run_state.id
            ) from exc
        except PydanticValidationError as exc:
            fields = sorted(
                {str(error["loc"][0]) for error in exc.errors() if error.get("loc")} or {"peak_rps"}
            )
            messages = "; ".join(error["msg"] for error in exc.errors())
            if interviewer is not None:
                data = interviewer.fix(data, fields, f"Please correct: {messages}", persist)
                continue
            raise ValueError(f"Invalid requirements: {messages}") from exc
    raise IncompleteRequirementsError("Requirements could not be completed after several attempts")


def auto_scope() -> list[str]:
    return list(AUTO_COMPONENTS)


def roles_for_scope(scope: list[str]) -> list[str]:
    roles = [ROLE_NAMES["requirements"]] if "requirements" in scope else []
    roles += [
        ROLE_NAMES[role]
        for role, components in ROLE_COMPONENTS.items()
        if set(components) & set(scope)
    ]
    return [*roles, ROLE_NAMES["verifier"]]


def add_lock(store: ProjectStore, component: str, field: str | None) -> list[DecisionLock]:
    if component not in COMPONENTS:
        raise ValueError(f"unknown component {component}")
    locks = store.load_locks()
    lock = DecisionLock(component=component, field_path=field)
    if not any(item.component == component and item.field_path == field for item in locks):
        locks.append(lock)
        store.save_locks(locks)
    return locks


def remove_lock(store: ProjectStore, component: str, field: str | None) -> list[DecisionLock]:
    locks = store.load_locks()
    if field is None:
        locks = [item for item in locks if item.component != component]
    else:
        locks = [
            item for item in locks if not (item.component == component and item.field_path == field)
        ]
    store.save_locks(locks)
    return locks


def reapply_manual_decisions(
    design: EnterpriseDesign,
    decisions: list[ManualDecision],
    scope: list[str],
    locks: list[DecisionLock],
) -> tuple[EnterpriseDesign, list[ValidationDiagnostic]]:
    """User-set values survive regeneration of their component."""
    locked = {lock.component for lock in locks if lock.field_path is None}
    relevant = [
        item for item in decisions if item.component in scope and item.component not in locked
    ]
    if not relevant:
        return design, []
    data = design.model_dump(mode="python")
    diagnostics: list[ValidationDiagnostic] = []
    for decision in relevant:
        try:
            _set_path(data, decision.field_path.split("."), decision.value)
        except ValueError as exc:
            diagnostics.append(
                ValidationDiagnostic(
                    code="MANUAL_DECISION_CONFLICT",
                    severity="warning",
                    component=decision.component,
                    field=decision.field_path,
                    message=f"Could not re-apply user-set value: {exc}",
                )
            )
    return EnterpriseDesign.model_validate(data), diagnostics


def restore_locked(
    design: EnterpriseDesign, baseline: EnterpriseDesign, locks: list[DecisionLock]
) -> EnterpriseDesign:
    """Locked components and fields keep their previous values exactly."""
    if not locks:
        return design
    data = design.model_dump(mode="python")
    previous = baseline.model_dump(mode="python")
    for lock in locks:
        if lock.field_path is None:
            for root in OWNED_ROOTS.get(lock.component, set()) - {"requirements"} - DERIVED_ROOTS:
                data[root] = previous.get(root)
            if lock.component in previous.get("components", {}):
                data["components"][lock.component] = previous["components"][lock.component]
            data["decisions"] = [
                item for item in data["decisions"] if item["component"] != lock.component
            ] + [item for item in previous["decisions"] if item["component"] == lock.component]
        else:
            try:
                value = _get_path(previous, lock.field_path.split("."))
                _set_path(data, lock.field_path.split("."), value)
            except ValueError:
                continue
    return EnterpriseDesign.model_validate(data)


def apply_override(
    design: EnterpriseDesign,
    component: str,
    path: Path,
    locks: list[DecisionLock],
) -> tuple[EnterpriseDesign, list[ManualDecision]]:
    if any(lock.component == component for lock in locks):
        raise StateConflictError(f"component {component} is locked")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or loaded.get("component") != component:
        raise ValueError("override must be an object whose component matches the command")
    sets = loaded.get("set", {})
    unsets = loaded.get("unset", [])
    if not isinstance(sets, dict) or not isinstance(unsets, list):
        raise ValueError("override set must be an object and unset must be a list")
    data = design.model_dump(mode="python")
    decisions: list[ManualDecision] = []
    for field_path, value in sets.items():
        if not isinstance(field_path, str):
            raise ValueError("override field paths must be strings")
        _check_owned(component, field_path)
        _set_path(data, field_path.split("."), value)
        decisions.append(ManualDecision(component=component, field_path=field_path, value=value))
    for field_path in unsets:
        if not isinstance(field_path, str):
            raise ValueError("unset field paths must be strings")
        _check_owned(component, field_path)
        _unset_path(data, field_path.split("."))
    return EnterpriseDesign.model_validate(data), decisions


def _check_owned(component: str, field_path: str) -> None:
    root = field_path.split(".", 1)[0]
    if root in DERIVED_ROOTS:
        raise ValueError("deterministic derived totals cannot be manually set")
    if root not in OWNED_ROOTS.get(component, set()):
        raise ValueError(f"{component} does not own field {field_path}")


def _get_path(data: dict[str, Any], parts: list[str]) -> Any:
    current: Any = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"unknown path: {'.'.join(parts)}")
        current = current[part]
    return current


def _set_path(data: dict[str, Any], parts: list[str], value: Any) -> None:
    current: Any = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"unknown override path: {'.'.join(parts)}")
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise ValueError(f"unknown override path: {'.'.join(parts)}")
    current[parts[-1]] = value


def _unset_path(data: dict[str, Any], parts: list[str]) -> None:
    current: Any = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"unknown unset path: {'.'.join(parts)}")
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise ValueError(f"unknown unset path: {'.'.join(parts)}")
    del current[parts[-1]]
