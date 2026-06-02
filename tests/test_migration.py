"""YAML -> SQLite import tests (uses the in-tree fixtures)."""
import pytest
from sqlmodel import select

from sprint_pulse.db import models as m
from sprint_pulse.db.engine import get_engine, session_scope
from sprint_pulse.migrate import MigrationError, import_yaml


@pytest.fixture
def engine():
    return get_engine(":memory:")


@pytest.fixture
def config_path(valid_dir):
    return valid_dir / "config.yaml"


@pytest.fixture
def sprints_dir(valid_dir):
    return valid_dir / "sprints_dir"


def test_import_counts(engine, config_path, sprints_dir):
    counts = import_yaml(engine, config_path, sprints_dir)
    assert counts["members"] == 11
    assert counts["orchestration"] == 2
    assert counts["aliases"] == 4
    assert counts["sprints"] == 2  # 2026-16, 2026-18 (archive/ ignored)


def test_orchestration_flags_persist(engine, config_path, sprints_dir):
    import_yaml(engine, config_path, sprints_dir)
    with session_scope(engine) as s:
        orch = s.exec(
            select(m.TeamMember).where(m.TeamMember.is_orchestration == True)  # noqa: E712
        ).all()
        names = {member.name for member in orch}
    assert names == {"Grace Hughes", "Hassan Ibrahim"}


def test_roster_order_preserved(engine, config_path, sprints_dir):
    import_yaml(engine, config_path, sprints_dir)
    with session_scope(engine) as s:
        names = [
            member.name
            for member in s.exec(
                select(m.TeamMember).order_by(m.TeamMember.sort_order)
            ).all()
        ]
    assert names[0] == "Alice Anderson"


def test_aliases_resolve_to_members(engine, config_path, sprints_dir):
    import_yaml(engine, config_path, sprints_dir)
    with session_scope(engine) as s:
        alias = s.exec(
            select(m.NameAlias).where(m.NameAlias.source == "Alyce Anderson")
        ).one()
        target_name = s.get(m.TeamMember, alias.target_member_id).name
    assert target_name == "Alice Anderson"


def test_timeoff_days_normalized(engine, config_path, sprints_dir):
    counts = import_yaml(engine, config_path, sprints_dir)
    with session_scope(engine) as s:
        n_days = len(s.exec(select(m.TimeOffDay)).all())
    # one TimeOffDay row per (entry, day)
    assert n_days >= counts["time_off"]


def test_token_not_imported(engine, config_path, sprints_dir):
    import_yaml(engine, config_path, sprints_dir)
    with session_scope(engine) as s:
        settings = s.get(m.Settings, 1)
        site, username, token_ref = settings.jira_site, settings.jira_username, settings.token_ref
    assert site == "redhat.atlassian.net"
    assert username == ""
    assert token_ref == "env"


def test_idempotent_guard(engine, config_path, sprints_dir):
    import_yaml(engine, config_path, sprints_dir)
    with pytest.raises(MigrationError):
        import_yaml(engine, config_path, sprints_dir)


def test_force_reimport(engine, config_path, sprints_dir):
    import_yaml(engine, config_path, sprints_dir)
    counts = import_yaml(engine, config_path, sprints_dir, force=True)
    assert counts["members"] == 11
    with session_scope(engine) as s:
        assert len(s.exec(select(m.TeamMember)).all()) == 11  # not doubled
