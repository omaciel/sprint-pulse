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


def test_import_counts_days_off(valid_dir):
    from sprint_pulse.db.engine import get_engine
    from sprint_pulse.migrate import import_yaml
    eng = get_engine(":memory:")
    counts = import_yaml(eng, valid_dir / "config.yaml", valid_dir / "sprints_dir")
    assert "days_off" in counts and counts["days_off"] > 0
    assert "time_off" not in counts


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


def test_legacy_timeoff_is_flattened_and_dropped():
    from datetime import date
    from sqlmodel import select, Session
    from sprint_pulse.db.engine import get_engine, create_db_and_tables
    from sprint_pulse.db import models as m

    eng = get_engine(":memory:")
    # Build the LEGACY schema by hand (raw SQL, so the test survives model removal).
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE teammember (id INTEGER PRIMARY KEY, name VARCHAR, is_orchestration BOOLEAN, sort_order INTEGER)")
        conn.exec_driver_sql("INSERT INTO teammember VALUES (1, 'Alice', 0, 0)")
        conn.exec_driver_sql("CREATE TABLE timeoff (id INTEGER PRIMARY KEY, sprint_id VARCHAR, member_id INTEGER, notes VARCHAR, type VARCHAR)")
        conn.exec_driver_sql("CREATE TABLE timeoffday (id INTEGER PRIMARY KEY, time_off_id INTEGER, date DATE)")
        # Same member+day appears in two sprints with different types -> conflict.
        conn.exec_driver_sql("INSERT INTO timeoff VALUES (1, 'A', 1, 'PTO', 'pto')")
        conn.exec_driver_sql("INSERT INTO timeoffday VALUES (1, 1, '2026-04-20')")
        conn.exec_driver_sql("INSERT INTO timeoff VALUES (2, 'B', 1, 'Holiday', 'holiday')")
        conn.exec_driver_sql("INSERT INTO timeoffday VALUES (2, 2, '2026-04-20')")  # conflict, holiday wins
        conn.exec_driver_sql("INSERT INTO timeoffday VALUES (3, 2, '2026-04-21')")

    create_db_and_tables(eng)  # creates memberdayoff, then flattens + drops legacy

    with Session(eng) as s:
        rows = sorted(s.exec(select(m.MemberDayOff)).all(), key=lambda r: r.date)
    assert [r.date for r in rows] == [date(2026, 4, 20), date(2026, 4, 21)]
    assert rows[0].type == "holiday"          # priority: holiday > pto
    assert rows[0].notes == "Holiday"
    with eng.connect() as conn:
        tables = {t for (t,) in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "timeoff" not in tables and "timeoffday" not in tables

    create_db_and_tables(eng)  # second call must be a harmless no-op
    with Session(eng) as s:
        assert len(s.exec(select(m.MemberDayOff)).all()) == 2
