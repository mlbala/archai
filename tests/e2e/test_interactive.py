from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from archai.cli import app

runner = CliRunner()


@pytest.fixture
def interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("archai.cli._is_interactive", lambda: True)


def partial_requirements(tmp_path: Path) -> Path:
    data = yaml.safe_load(Path("examples/azure-enterprise-rag/requirements.yaml").read_text())
    del data["monthly_budget"]
    del data["tenant_isolation"]
    path = tmp_path / "partial.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_auto_interviews_for_missing_answers_then_designs_and_exports(tmp_path, interactive):
    source = partial_requirements(tmp_path)
    # roles, channels, optional parts, integrations, data sources, docs/day,
    # existing services, IdP: defaults
    answers = ["", "", "", "", "", "", "", "", "multi", "", "", "", "", "", "20000", ""]
    result = runner.invoke(
        app,
        ["auto", "-p", "guided", "-f", str(source), "--output-dir", str(tmp_path / "out")],
        input="\n".join(answers) + "\n",
    )
    assert result.exit_code == 0, result.output
    assert "Is it single-tenant or multi-tenant?" in result.output
    assert "Hard monthly spending limit" in result.output
    assert "Review your answers" in result.output
    assert "Accepted revision 1" in result.output
    assert "Design saved" in result.output
    project = tmp_path / "out" / "guided"
    design = json.loads((project / "revisions/0001/state/enterprise_design.json").read_text())
    assert design["requirements"]["tenant_isolation"] == "multi"
    assert design["requirements"]["monthly_budget"] == "20000"
    assert design["requirements"]["identity_provider"] == "Entra ID"
    bundle = next((project / "exports/0001").iterdir())
    assert (bundle / "Complete_AI_System_Design.pdf").read_bytes().startswith(b"%PDF")
    assert (bundle / "documents/Identity_Design.pdf").exists()
    assert (bundle / "diagrams/oauth-user.png").read_bytes().startswith(b"\x89PNG")
    status = runner.invoke(app, ["status", "guided", "--output-dir", str(tmp_path / "out")])
    assert status.exit_code == 0, status.output
    assert "Completeness: complete" in status.output


def test_auto_asks_for_project_and_description_and_can_pause(tmp_path, interactive):
    result = runner.invoke(
        app,
        ["auto", "--output-dir", str(tmp_path)],
        input="Support Copilot\nA copilot that answers support questions.\n\nsave\n",
    )
    assert result.exit_code == 130, result.output
    assert "Describe the AI application" in result.output
    assert "Interview saved" in result.output
    run_id = re.search(r"--run ([0-9a-f]{32})", result.output)
    assert run_id is not None
    state = json.loads(
        (tmp_path / "support-copilot/runs" / run_id.group(1) / "run.json").read_text()
    )
    assert state["status"] == "interviewing"
    inputs = json.loads(
        (tmp_path / "support-copilot/runs" / run_id.group(1) / "inputs.json").read_text()
    )
    assert inputs["idea"] == "A copilot that answers support questions."
    status = runner.invoke(app, ["status", "support-copilot", "--output-dir", str(tmp_path)])
    assert "Resume with" in status.output


def test_non_tty_auto_never_prompts(tmp_path):
    result = runner.invoke(
        app, ["auto", "-p", "ci", "-i", "A copilot", "--output-dir", str(tmp_path)], input=""
    )
    assert result.exit_code == 2
    assert "REQ-MONTHLY_BUDGET" in result.output
    assert "Review your answers" not in result.output
