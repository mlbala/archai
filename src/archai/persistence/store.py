from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock
from pydantic import BaseModel, TypeAdapter

from archai.ingestion import safe_slug, sha256_bytes
from archai.schemas.models import (
    ArchitectureGraph,
    DecisionLock,
    EnterpriseDesign,
    ManualDecision,
    ProjectMetadata,
    RevisionManifest,
    RunState,
    SourceDocument,
)


def json_bytes(value: BaseModel | dict[str, Any] | list[Any]) -> bytes:
    data: Any = (
        value.model_dump(mode="json", exclude_none=False) if isinstance(value, BaseModel) else value
    )
    # TypeAdapter handles nested Pydantic models, Decimal, datetime, and enums in mappings.
    normalized = TypeAdapter(Any).dump_python(data, mode="json")
    return (json.dumps(normalized, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


class ProjectStore:
    def __init__(self, output_root: Path, project: str) -> None:
        self.output_root = output_root.resolve()
        self.slug = safe_slug(project)
        self.root = (self.output_root / self.slug).resolve()
        if self.output_root != self.root and self.output_root not in self.root.parents:
            raise ValueError("project path escapes output root")
        self.lock_path = self.output_root / f".{self.slug}.lock"

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with FileLock(str(self.lock_path), timeout=30):
            yield

    def initialize(self) -> ProjectMetadata:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("sources", "runs", "revisions"):
            (self.root / name).mkdir(exist_ok=True, mode=0o700)
        if self.project_file.exists():
            return self.metadata()
        metadata = ProjectMetadata(slug=self.slug)
        self._atomic_write(self.project_file, json_bytes(metadata))
        self.save_locks([])
        self.save_manual_decisions([])
        return metadata

    @property
    def project_file(self) -> Path:
        return self.root / "project.json"

    @property
    def locks_file(self) -> Path:
        return self.root / "decision_locks.json"

    @property
    def decisions_file(self) -> Path:
        return self.root / "manual_decisions.json"

    def metadata(self) -> ProjectMetadata:
        return ProjectMetadata.model_validate_json(self.project_file.read_text(encoding="utf-8"))

    def list_revisions(self) -> list[int]:
        path = self.root / "revisions"
        if not path.exists():
            return []
        return sorted(
            int(item.name) for item in path.iterdir() if item.is_dir() and item.name.isdigit()
        )

    def load_design(self, revision: int | None = None) -> EnterpriseDesign:
        number = revision or self.metadata().latest_revision
        if number <= 0:
            raise FileNotFoundError(f"project {self.slug} has no accepted revision")
        path = self.root / "revisions" / f"{number:04d}" / "state" / "enterprise_design.json"
        return EnterpriseDesign.model_validate_json(path.read_text(encoding="utf-8"))

    def load_graph(self, revision: int | None = None) -> ArchitectureGraph:
        number = revision or self.metadata().latest_revision
        path = self.root / "revisions" / f"{number:04d}" / "state" / "architecture_graph.json"
        return ArchitectureGraph.model_validate_json(path.read_text(encoding="utf-8"))

    def load_manifest(self, revision: int | None = None) -> RevisionManifest:
        number = revision or self.metadata().latest_revision
        path = self.root / "revisions" / f"{number:04d}" / "manifest.json"
        return RevisionManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def save_source(self, source_path: Path, text: str) -> SourceDocument:
        digest = sha256_bytes(text.encode())
        safe_name = safe_slug(source_path.stem) + source_path.suffix.lower()
        relative = Path("sources") / f"{digest}_{safe_name}"
        destination = self.root / relative
        if not destination.exists():
            self._atomic_write(destination, text.encode(), mode=0o600)
        return SourceDocument(
            id=f"src-{digest[:12]}",
            name=source_path.name,
            sha256=digest,
            media_type="text/plain",
            stored_path=str(relative),
        )

    def commit_revision(
        self,
        design: EnterpriseDesign,
        graph: ArchitectureGraph,
        manifest: RevisionManifest,
        documents: dict[str, str],
        base_revision: int,
    ) -> Path:
        metadata = self.metadata()
        if metadata.latest_revision != base_revision:
            raise RuntimeError(
                f"baseline changed from {base_revision} to {metadata.latest_revision}; retry the run"
            )
        revision = base_revision + 1
        if manifest.revision != revision:
            raise ValueError("manifest revision does not match next revision")
        revisions = self.root / "revisions"
        final = revisions / f"{revision:04d}"
        if final.exists():
            raise FileExistsError(f"revision {revision} already exists")
        temp = Path(tempfile.mkdtemp(prefix=f".{revision:04d}-", dir=revisions))
        try:
            state = temp / "state"
            requirements = temp / "requirements"
            docs = temp / "documents"
            state.mkdir()
            requirements.mkdir()
            docs.mkdir()
            (state / "enterprise_design.json").write_bytes(json_bytes(design))
            (state / "requirements.json").write_bytes(json_bytes(design.requirements))
            (state / "architecture_graph.json").write_bytes(json_bytes(graph))
            (state / "component_status.json").write_bytes(json_bytes(design.components))
            (state / "manual_decisions.json").write_bytes(json_bytes(self.load_manual_decisions()))
            (state / "decision_locks.json").write_bytes(json_bytes(self.load_locks()))
            (requirements / "AI_Enterprise_PRD.md").write_text(
                documents.get("AI_Enterprise_PRD.md", "# Requirements\n"), encoding="utf-8"
            )
            for name, content in sorted(documents.items()):
                (docs / name).write_text(content, encoding="utf-8")
            (temp / "changes.md").write_text(
                f"# Revision {revision}\n\nScope: {', '.join(manifest.selected_scope)}\n",
                encoding="utf-8",
            )
            (temp / "manifest.json").write_bytes(json_bytes(manifest))
            os.chmod(temp, 0o700)
            temp.rename(final)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise
        metadata.latest_revision = revision
        if manifest.project_complete:
            metadata.latest_complete_revision = revision
        self._atomic_write(self.project_file, json_bytes(metadata))
        return final

    def load_locks(self) -> list[DecisionLock]:
        if not self.locks_file.exists():
            return []
        return [
            DecisionLock.model_validate(item) for item in json.loads(self.locks_file.read_text())
        ]

    def save_locks(self, locks: list[DecisionLock]) -> None:
        self._atomic_write(self.locks_file, json_bytes(locks), mode=0o600)

    def load_manual_decisions(self) -> list[ManualDecision]:
        if not self.decisions_file.exists():
            return []
        return [
            ManualDecision.model_validate(item)
            for item in json.loads(self.decisions_file.read_text())
        ]

    def save_manual_decisions(self, decisions: list[ManualDecision]) -> None:
        self._atomic_write(self.decisions_file, json_bytes(decisions), mode=0o600)

    def write_export_metadata(self, bundle_id: str) -> None:
        metadata = self.metadata()
        metadata.latest_export = bundle_id
        self._atomic_write(self.project_file, json_bytes(metadata))

    def current_export_path(self) -> Path | None:
        if (self.root / "manifest.json").exists():
            return self.root
        return None

    def save_run(self, run: RunState, inputs: dict[str, Any] | None = None) -> Path:
        run_root = self.root / "runs" / run.id
        run_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._atomic_write(run_root / "run.json", json_bytes(run), mode=0o600)
        if inputs is not None:
            self._atomic_write(run_root / "inputs.json", json_bytes(inputs), mode=0o600)
        return run_root

    def load_run(self, run_id: str) -> tuple[RunState, Path | None]:
        if not run_id or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in run_id
        ):
            raise ValueError("invalid run ID")
        run_root = self.root / "runs" / run_id
        state = RunState.model_validate_json((run_root / "run.json").read_text(encoding="utf-8"))
        inputs = run_root / "inputs.json"
        return state, inputs if inputs.exists() else None

    def _atomic_write(self, path: Path, data: bytes, mode: int = 0o600) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError(f"refusing to write through symlink: {path}")
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def new_bundle_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
