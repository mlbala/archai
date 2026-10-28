from archai.application.service import auto_scope, run_generation
from archai.persistence.store import ProjectStore


def test_revisions_are_immutable_and_exports_separate(tmp_path, requirements_file):
    store, revision = run_generation(
        project="Test Project",
        scope=auto_scope(),
        output_dir=tmp_path,
        files=[requirements_file],
        idea=None,
        stdin_enabled=False,
        answers=None,
        profile=None,
        region=None,
        target_providers=None,
        topology=None,
        archetypes=[],
        allow_assumptions=False,
    )
    assert revision == 1
    assert store.load_manifest().project_complete
    original = (store.root / "revisions/0001/state/enterprise_design.json").read_bytes()
    _store2, revision2 = run_generation(
        project="Test Project",
        scope=["guard"],
        output_dir=tmp_path,
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
    )
    assert revision2 == 2
    assert (store.root / "revisions/0001/state/enterprise_design.json").read_bytes() == original
    assert ProjectStore(tmp_path, "Test Project").metadata().latest_revision == 2


def test_update_preserves_unspecified_profile_and_topology(tmp_path, requirements_file):
    store, _ = run_generation(
        project="preserve",
        scope=auto_scope(),
        output_dir=tmp_path,
        files=[requirements_file],
        idea=None,
        stdin_enabled=False,
        answers=None,
        profile=None,
        region=None,
        target_providers=None,
        topology=None,
        archetypes=[],
        allow_assumptions=False,
    )
    store, _ = run_generation(
        project="preserve",
        scope=auto_scope(),
        output_dir=tmp_path,
        files=[],
        idea="Refine the approved business requirement",
        stdin_enabled=False,
        answers=None,
        profile=None,
        region=None,
        target_providers=None,
        topology=None,
        archetypes=[],
        allow_assumptions=False,
    )
    requirements = store.load_design().requirements
    assert requirements.profile == "azure-aca"
    assert requirements.topology == "provider-failover"
