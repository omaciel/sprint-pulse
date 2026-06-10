"""Departed-member feature: tenure columns, helpers, services, rendering."""
import pytest
from datetime import date

from sprint_pulse.config import Config, JiraConfig, in_tenure, tenure_overlaps
from sprint_pulse.db import models as m
from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
from sprint_pulse.errors import ValidationError
from sprint_pulse.services import config_service as cfgsvc
from sprint_pulse.services import sprint_service as spsvc
from sprint_pulse.services import time_off_service as tosvc


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


def _cfg(**kw) -> Config:
    base = dict(
        working_days_per_sprint=10,
        jira=JiraConfig(site="x", board="1"),
        roster=["Alice Anderson", "Bob Brown"],
        excluded=set(),
        name_aliases={},
    )
    base.update(kw)
    return Config(**base)


def test_in_tenure_all_combinations():
    d = date(2026, 5, 15)
    assert in_tenure(None, d)                                   # no tenure recorded
    assert in_tenure((None, None), d)
    assert in_tenure((date(2026, 5, 1), None), d)
    assert not in_tenure((date(2026, 6, 1), None), d)           # joins later
    assert in_tenure((None, date(2026, 5, 15)), d)              # leaves that day (inclusive)
    assert not in_tenure((None, date(2026, 5, 14)), d)          # already left
    assert in_tenure((date(2026, 5, 15), date(2026, 5, 15)), d)


def test_tenure_overlaps_sprint_window():
    s, e = date(2026, 5, 4), date(2026, 5, 17)
    assert tenure_overlaps(None, s, e)
    assert tenure_overlaps((None, None), s, e)
    assert tenure_overlaps((None, date(2026, 5, 4)), s, e)      # leaves on sprint start
    assert not tenure_overlaps((None, date(2026, 5, 3)), s, e)  # left before
    assert tenure_overlaps((date(2026, 5, 17), None), s, e)     # joins on sprint end
    assert not tenure_overlaps((date(2026, 5, 18), None), s, e) # joins after


def test_capacity_override():
    cfg = _cfg()
    assert cfg.capacity == 20  # 2 members x 10 — unchanged default behavior
    assert _cfg(capacity_override=13).capacity == 13
    assert _cfg(capacity_override=0).capacity == 0  # 0 is a real value, not "unset"


@pytest.fixture
def engine():
    eng = get_engine(":memory:")
    create_db_and_tables(eng)
    return eng


def test_add_member_with_start_date(engine):
    with session_scope(engine) as s:
        member = cfgsvc.add_member(s, "New Hire", start_date=date(2026, 6, 1))
        assert member.start_date == date(2026, 6, 1)
        assert member.end_date is None


def test_depart_member_sets_end_date_and_trims_future_time_off(engine):
    with session_scope(engine) as s:
        member = cfgsvc.add_member(s, "Alice Anderson")
        mid = member.id
        # Mon 2026-05-25 (kept), Fri 2026-05-29 (departure day, kept), and Mon 2026-06-01 (after departure, trimmed)
        tosvc.set_days(s, mid, [date(2026, 5, 25)], "pto")
        tosvc.set_days(s, mid, [date(2026, 5, 29)], "pto")
        tosvc.set_days(s, mid, [date(2026, 6, 1)], "pto")
    with session_scope(engine) as s:
        cfgsvc.depart_member(s, mid, date(2026, 5, 29))
    with session_scope(engine) as s:
        assert cfgsvc.get_member(s, mid).end_date == date(2026, 5, 29)
        remaining = tosvc.member_calendar(s, mid, 2026, 5) | tosvc.member_calendar(s, mid, 2026, 6)
        assert date(2026, 5, 25) in remaining
        assert date(2026, 5, 29) in remaining
        assert date(2026, 6, 1) not in remaining


def test_depart_member_rejects_end_before_start(engine):
    with session_scope(engine) as s:
        member = cfgsvc.add_member(s, "New Hire", start_date=date(2026, 6, 1))
        with pytest.raises(ValidationError):
            cfgsvc.depart_member(s, member.id, date(2026, 5, 1))


def test_depart_member_rejects_already_departed(engine):
    with session_scope(engine) as s:
        member = cfgsvc.add_member(s, "Alice Anderson")
        mid = member.id
        cfgsvc.depart_member(s, mid, date(2026, 5, 29))
        with pytest.raises(ValidationError):
            cfgsvc.depart_member(s, mid, date(2026, 6, 5))


def test_rejoin_member_clears_end_date(engine):
    with session_scope(engine) as s:
        member = cfgsvc.add_member(s, "Alice Anderson")
        mid = member.id
        cfgsvc.depart_member(s, mid, date(2026, 5, 29))
    with session_scope(engine) as s:
        cfgsvc.rejoin_member(s, mid)
        assert cfgsvc.get_member(s, mid).end_date is None


def test_rejoin_rejects_active_member(engine):
    with session_scope(engine) as s:
        member = cfgsvc.add_member(s, "Alice Anderson")
        with pytest.raises(ValidationError):
            cfgsvc.rejoin_member(s, member.id)


def test_set_days_rejects_dates_outside_tenure(engine):
    with session_scope(engine) as s:
        member = cfgsvc.add_member(s, "New Hire", start_date=date(2026, 6, 1))
        mid = member.id
        with pytest.raises(ValidationError, match="tenure"):
            tosvc.set_days(s, mid, [date(2026, 5, 25)], "pto")  # before they joined
    with session_scope(engine) as s:
        cfgsvc.depart_member(s, mid, date(2026, 6, 5))
        with pytest.raises(ValidationError, match="tenure"):
            tosvc.set_days(s, mid, [date(2026, 6, 8)], "pto")  # after they left
        tosvc.set_days(s, mid, [date(2026, 6, 3)], "pto")  # inside tenure: OK


@pytest.fixture
def team_engine():
    """Two members, two 14-day sprints (10 working days each)."""
    eng = get_engine(":memory:")
    create_db_and_tables(eng)
    with session_scope(eng) as s:
        cfgsvc.add_member(s, "Alice Anderson")
        cfgsvc.add_member(s, "Bob Brown")
        spsvc.create_sprint(s, "2026-22", date(2026, 5, 25), date(2026, 6, 7))
        spsvc.create_sprint(s, "2026-24", date(2026, 6, 8), date(2026, 6, 21))
    return eng


def test_dateless_roster_reproduces_current_numbers(team_engine):
    with session_scope(team_engine) as s:
        by_id = spsvc.build_sprint_configs(s)
    for cfg in by_id.values():
        assert cfg.roster == ["Alice Anderson", "Bob Brown"]
        assert cfg.capacity == 20  # 2 x 10, identical to pre-feature math
        assert cfg.tenures == {}


def test_departed_member_dropped_from_later_sprints(team_engine):
    with session_scope(team_engine) as s:
        bob = next(mm for mm in cfgsvc.list_members(s) if mm.name == "Bob Brown")
        cfgsvc.depart_member(s, bob.id, date(2026, 6, 7))  # leaves at sprint boundary
    with session_scope(team_engine) as s:
        by_id = spsvc.build_sprint_configs(s)
    assert "Bob Brown" in by_id["2026-22"].roster
    assert by_id["2026-22"].capacity == 20  # covered every working day
    assert "Bob Brown" not in by_id["2026-24"].roster
    assert by_id["2026-24"].capacity == 10


def test_mid_sprint_departure_prorates_capacity(team_engine):
    with session_scope(team_engine) as s:
        bob = next(mm for mm in cfgsvc.list_members(s) if mm.name == "Bob Brown")
        # Wed of week 1 of sprint 2026-22 -> 3 in-tenure working days (Mon-Wed)
        cfgsvc.depart_member(s, bob.id, date(2026, 5, 27))
    with session_scope(team_engine) as s:
        by_id = spsvc.build_sprint_configs(s)
    assert by_id["2026-22"].capacity == 13  # Alice 10 + Bob 3
    assert by_id["2026-22"].tenures["Bob Brown"] == (None, date(2026, 5, 27))


def test_mid_sprint_join_prorates_capacity(team_engine):
    with session_scope(team_engine) as s:
        # Joins Thu of week 2 of sprint 2026-24 -> 2 in-tenure working days
        cfgsvc.add_member(s, "New Hire", start_date=date(2026, 6, 18))
    with session_scope(team_engine) as s:
        by_id = spsvc.build_sprint_configs(s)
    assert "New Hire" not in by_id["2026-22"].roster
    assert by_id["2026-22"].capacity == 20
    assert "New Hire" in by_id["2026-24"].roster
    assert by_id["2026-24"].capacity == 22  # 10 + 10 + 2


def test_excluded_member_contributes_zero_even_with_tenure(team_engine):
    with session_scope(team_engine) as s:
        bob = next(mm for mm in cfgsvc.list_members(s) if mm.name == "Bob Brown")
        cfgsvc.toggle_excluded(s, bob.id)
        cfgsvc.depart_member(s, bob.id, date(2026, 5, 27))
    with session_scope(team_engine) as s:
        by_id = spsvc.build_sprint_configs(s)
    assert by_id["2026-22"].capacity == 10  # only Alice counts
    assert "Bob Brown" in by_id["2026-22"].excluded
