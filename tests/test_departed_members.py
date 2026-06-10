"""Departed-member feature: tenure columns, helpers, services, rendering."""
from sprint_pulse.db import models as m
from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope


def test_teammember_has_tenure_fields():
    member = m.TeamMember(name="Alice Anderson")
    assert member.start_date is None
    assert member.end_date is None


def test_existing_db_gains_tenure_columns():
    """A pre-upgrade DB (teammember without the new columns) is migrated in place."""
    eng = get_engine(":memory:")
    with eng.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE teammember (id INTEGER PRIMARY KEY, name VARCHAR, "
            "is_excluded BOOLEAN DEFAULT 0, sort_order INTEGER DEFAULT 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO teammember (name, is_excluded, sort_order) VALUES ('Alice', 0, 0)"
        )
    create_db_and_tables(eng)
    with eng.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(teammember)")}
    assert {"start_date", "end_date"} <= cols
    with session_scope(eng) as s:
        alice = s.get(m.TeamMember, 1)
        assert alice.start_date is None
        assert alice.end_date is None
