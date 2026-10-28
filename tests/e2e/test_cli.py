import re

from typer.testing import CliRunner

from archai.cli import app

runner = CliRunner()


def test_complete_create_validate_simulate_and_export(tmp_path, requirements_file):
    result = runner.invoke(
        app,
        [
            "auto",
            "-p",
            "eu-support",
            "-f",
            str(requirements_file),
            "--formats",
            "core",
            "--output-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Accepted revision 1" in result.output
    result = runner.invoke(
        app, ["validate", "eu-support", "--strict", "--output-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        [
            "simulate",
            "eu-support",
            "--scenario",
            "examples/provider-failover/timeout-and-429.yaml",
            "--output-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"liability": "9.4"' in result.output
    result = runner.invoke(
        app,
        [
            "export",
            "eu-support",
            "--revision",
            "1",
            "--offline",
            "--formats",
            "core",
            "--output-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output


def test_focused_command_and_dry_run_do_not_expand_scope(tmp_path, requirements_file):
    result = runner.invoke(
        app,
        ["guard", "-p", "guard-only", "-f", str(requirements_file), "--output-dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    state = tmp_path / "guard-only/revisions/0001/state/component_status.json"
    assert '"guard"' in state.read_text()
    assert '"infra"' not in state.read_text()
    dry_root = tmp_path / "dry"
    result = runner.invoke(
        app,
        [
            "infra",
            "-p",
            "dry",
            "-f",
            str(requirements_file),
            "--dry-run",
            "--output-dir",
            str(dry_root),
        ],
    )
    assert result.exit_code == 0
    assert not dry_root.exists()


def test_missing_critical_requirements_returns_exit_two(tmp_path):
    result = runner.invoke(
        app, ["auto", "-p", "incomplete", "-i", "Build a copilot", "--output-dir", str(tmp_path)]
    )
    assert result.exit_code == 2
    assert "Question IDs" in result.output
    run_id = re.search(r"run ID ([0-9a-f]{32})", result.output)
    assert run_id is not None
    resumed = runner.invoke(
        app,
        [
            "resume",
            "incomplete",
            "--run",
            run_id.group(1),
            "--answers",
            "examples/azure-enterprise-rag/requirements.yaml",
            "--output-dir",
            str(tmp_path),
        ],
    )
    assert resumed.exit_code == 0, resumed.output
    assert "Accepted revision 1" in resumed.output


def test_alias_component_design_is_system_only(tmp_path, requirements_file):
    result = runner.invoke(
        app, ["design", "-p", "alias", "-f", str(requirements_file), "--output-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    status = (tmp_path / "alias/revisions/0001/state/component_status.json").read_text()
    assert '"system"' in status
    assert '"guard"' not in status


def test_document_rerender_does_not_create_revision(tmp_path, requirements_file):
    created = runner.invoke(
        app,
        ["auto", "-p", "docs", "-f", str(requirements_file), "--output-dir", str(tmp_path)],
    )
    assert created.exit_code == 0, created.output
    rendered = runner.invoke(
        app,
        [
            "doc",
            "-p",
            "docs",
            "--scope",
            "guard,infra",
            "--formats",
            "md",
            "--output-dir",
            str(tmp_path),
        ],
    )
    assert rendered.exit_code == 0, rendered.output
    assert not (tmp_path / "docs/revisions/0002").exists()


def test_auto_without_project_explains_next_step():
    result = runner.invoke(app, ["auto"])
    assert result.exit_code == 2
    assert "archai auto -p my-project" in result.output


def test_openai_selected_for_prose_and_critical_inputs_still_required(
    tmp_path, monkeypatch, fake_architect
):
    def fake_factory(settings, name, model):
        assert name == "openai"
        assert model == "chosen-model"
        return fake_architect

    monkeypatch.setattr("archai.application.service.create_provider", fake_factory)
    result = runner.invoke(
        app,
        [
            "auto",
            "-p",
            "prose",
            "-i",
            "A copilot for agents",
            "--architect-provider",
            "openai",
            "--architect-model",
            "chosen-model",
            "--non-interactive",
            "--output-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    assert [name for name, _ in fake_architect.prompts] == ["RequirementsAnalysis"]
    assert "REQ-TOOL_SIDE_EFFECTS" in result.output
    assert "REQ-MONTHLY_BUDGET" in result.output
    assert "unresolved_questions" in result.output


def test_setup_stores_secret_without_printing_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("archai.cli._is_interactive", lambda: True)
    monkeypatch.delenv("ARCHAI_ARCHITECT_PROVIDER", raising=False)
    monkeypatch.delenv("ARCHAI_ARCHITECT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = runner.invoke(app, ["setup"], input="openai\ncustom-model\nprivate-test-key\n")
    assert result.exit_code == 0, result.output
    assert "private-test-key" not in result.output
    config = tmp_path / ".env"
    assert "ARCHAI_ARCHITECT_PROVIDER='openai'" in config.read_text()
    assert "ARCHAI_ARCHITECT_MODEL='custom-model'" in config.read_text()
    assert "ARCHAI_OPENAI_API_KEY='private-test-key'" in config.read_text()
    assert config.stat().st_mode & 0o777 == 0o600
