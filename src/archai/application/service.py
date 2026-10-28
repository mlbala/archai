from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from archai.application.designer import apply_scope, build_graph
from archai.application.registry import AUTO_COMPONENTS, COMPONENTS
from archai.compilers.report import complete_document, component_document, requirements_document
from archai.domain.validation import validate_design
from archai.errors import IncompleteRequirementsError, StateConflictError, ValidationError
from archai.ingestion import merge_inputs, parse_requirements, sha256_bytes
from archai.persistence.store import ProjectStore, json_bytes
from archai.schemas.models import (
    ComponentStatus,
    DecisionLock,
    EnterpriseDesign,
    ManualDecision,
    RevisionManifest,
    RunState,
    ValidationDiagnostic,
)

OWNED_ROOTS: dict[str, set[str]] = {
    "requirements": {"requirements"},
    "system": {"services"},
    "api": {"api_contracts"},
    "routing": {"endpoints", "model_aliases"},
    "budget": {"budget_policy"},
    "cache": {"cache_policy"},
    "workflow": {"workflows"},
    "rag": {"data_stores"},
    "data": {"data_stores"},
    "infra": {"deployment"},
    "resilience": {"queue_policy"},
    "auth": {"identity_policy"},
    "guard": {"guardrails"},
    "security": {"risks"},
    "observe": {"observability"},
    "eval": {"risks"},
}


def generation_plan(
    store: ProjectStore,
    scope: list[str],
    files: list[Path],
    formats: str,
) -> dict[str, Any]:
    existing = store.project_file.exists()
    return {
        "project": store.slug,
        "baseline_revision": store.metadata().latest_revision if existing else 0,
        "scope": scope,
        "roles": sorted(
            {COMPONENTS[name].role for name in scope if COMPONENTS[name].role is not None}
            | {"Design Verifier and Compiler"}
        ),
        "inputs": [str(path) for path in files],
        "writes": [f"revision state for {name}" for name in scope],
        "invalidates": sorted(
            {item for name in scope for item in COMPONENTS[name].invalidates if item not in scope}
        ),
        "formats": formats,
        "llm_calls": 0,
        "note": "Dry-run performs no writes, provider calls, or renderer execution.",
    }


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
) -> tuple[ProjectStore, int]:
    del allow_assumptions  # noncritical defaults are explicit in canonical templates
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
            id=uuid4().hex,
            project=store.slug,
            base_revision=base_revision,
            selected_scope=scope,
            status="running",
        )
        store.save_run(run_state)
        if (
            not files
            and not idea
            and not stdin_text
            and answers is None
            and profile is None
            and region is None
            and target_providers is None
            and topology is None
            and not archetypes
        ):
            if baseline is None:
                raise IncompleteRequirementsError(
                    "A new project requires -f, -i, --stdin, or --answers"
                )
            requirements = baseline.requirements
            raw_sources: list[tuple[Path, str]] = []
            input_snapshot = requirements.model_dump(mode="json")
        else:
            merged, raw_sources = merge_inputs(
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
                baseline_data = baseline.requirements.model_dump(mode="python")
                baseline_data.update(
                    {key: value for key, value in merged.items() if value not in (None, [], "")}
                )
                merged = baseline_data
            input_snapshot = merged
            try:
                requirements = parse_requirements(merged)
            except IncompleteRequirementsError as exc:
                run_state.status = "blocked"
                run_state.diagnostics.append(
                    ValidationDiagnostic(
                        code="REQUIREMENTS_INCOMPLETE",
                        severity="error",
                        component="requirements",
                        message=str(exc),
                    )
                )
                store.save_run(run_state, input_snapshot)
                raise IncompleteRequirementsError(
                    f"{exc}. Resume with run ID {run_state.id}"
                ) from exc
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
        design = apply_scope(baseline, store.slug, requirements, scope, locks)
        if override is not None:
            if len(scope) != 1:
                raise ValueError("--override is scoped to exactly one component command")
            design, decisions = apply_override(design, scope[0], override, locks)
            store.save_manual_decisions(store.load_manual_decisions() + decisions)
        graph = build_graph(design)
        next_revision = base_revision + 1
        for name in scope:
            if name in design.components:
                design.components[name].revision = next_revision
                design.components[name].input_hash = sha256_bytes(json_bytes(requirements))
        diagnostics = validate_design(design, graph, scope)
        errors = [item for item in diagnostics if item.severity == "error"]
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
        required = set(COMPONENTS) - {"diagram", "doc"}
        complete = required <= valid_components
        design_hash = sha256_bytes(json_bytes(design))
        manifest = RevisionManifest(
            project=store.slug,
            revision=next_revision,
            created_at=datetime.now(UTC),
            selected_scope=scope,
            design_sha256=design_hash,
            scope_valid=True,
            project_complete=complete,
            diagnostics=diagnostics,
            locks=locks,
            manual_decisions=store.load_manual_decisions(),
        )
        documents: dict[str, str] = {"AI_Enterprise_PRD.md": requirements_document(design)}
        for name in scope:
            if name in COMPONENTS and name not in {"doc"}:
                filename = COMPONENTS[name].outputs[0]
                documents[filename] = component_document(name, design, graph, diagnostics)
        if "doc" in scope:
            documents["Complete_AI_System_Design.md"] = complete_document(
                design, graph, diagnostics
            )
        store.commit_revision(design, graph, manifest, documents, base_revision)
        run_state.status = "accepted"
        run_state.completed_steps = ["requirements", *scope, "validation", "revision"]
        run_state.diagnostics = diagnostics
        store.save_run(run_state, input_snapshot)
        return store, next_revision


def auto_scope() -> list[str]:
    return list(AUTO_COMPONENTS)


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
    if root not in OWNED_ROOTS.get(component, set()):
        raise ValueError(f"{component} does not own field {field_path}")
    if root in {"capacity", "costs"}:
        raise ValueError("deterministic derived totals cannot be manually set")


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
