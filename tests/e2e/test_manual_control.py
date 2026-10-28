import json

from typer.testing import CliRunner

from archai.cli import app

runner = CliRunner()


def test_override_lock_and_auto_preserve_guardrails(tmp_path, requirements_file):
    output = str(tmp_path)
    first = runner.invoke(
        app,
        [
            "guard",
            "-p",
            "controlled",
            "-f",
            str(requirements_file),
            "--override",
            "examples/azure-enterprise-rag/guard-overrides.yaml",
            "--output-dir",
            output,
        ],
    )
    assert first.exit_code == 0, first.output
    state_path = tmp_path / "controlled/revisions/0001/state/enterprise_design.json"
    guarded = json.loads(state_path.read_text())["guardrails"]
    locked = runner.invoke(
        app, ["lock", "-p", "controlled", "--component", "guard", "--output-dir", output]
    )
    assert locked.exit_code == 0, locked.output
    completed = runner.invoke(
        app, ["auto", "-p", "controlled", "--formats", "core", "--output-dir", output]
    )
    assert completed.exit_code == 0, completed.output
    final_path = tmp_path / "controlled/revisions/0002/state/enterprise_design.json"
    assert json.loads(final_path.read_text())["guardrails"] == guarded
    report = next((tmp_path / "controlled/exports/0002").glob("*/Complete_AI_System_Design.md"))
    assert "exact refund arguments" in report.read_text()


def test_locked_component_rejects_incompatible_requirement_update(tmp_path, requirements_file):
    output = str(tmp_path)
    assert (
        runner.invoke(
            app, ["guard", "-p", "blocked", "-f", str(requirements_file), "--output-dir", output]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["lock", "-p", "blocked", "--component", "guard", "--output-dir", output]
        ).exit_code
        == 0
    )
    result = runner.invoke(
        app,
        [
            "auto",
            "-p",
            "blocked",
            "--answers",
            "examples/azure-enterprise-rag/update-answers.yaml",
            "--output-dir",
            output,
        ],
    )
    assert result.exit_code == 6
    assert "locked selected components" in result.output
