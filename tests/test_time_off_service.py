"""time_off_service: day-off CRUD, validation, outage derivation, view builders."""
from datetime import date

import pytest

from sprint_pulse.db.engine import get_engine, session_scope
from sprint_pulse.errors import ValidationError
from sprint_pulse.migrate import import_yaml
from sprint_pulse.services import config_service as cfgsvc
from sprint_pulse.services import time_off_service as tos
from sprint_pulse.services import type_service as tsvc


@pytest.fixture
def engine(valid_dir):
    eng = get_engine(":memory:")
    import_yaml(eng, valid_dir / "config.yaml", valid_dir / "sprints_dir")
    return eng


def _alice(session):
    return next(m for m in cfgsvc.list_members(session) if m.name == "Alice Anderson")


def test_set_days_creates_one_row_per_day(engine):
    with session_scope(engine) as s:
        aid = _alice(s).id
        tos.set_days(s, aid, [date(2026, 7, 20), date(2026, 7, 21)], "pto", "Vacation")
    with session_scope(engine) as s:
        cal = tos.member_calendar(s, aid, 2026, 7)
    assert cal[date(2026, 7, 20)] == ("pto", "Vacation")
    assert cal[date(2026, 7, 21)] == ("pto", "Vacation")


def test_set_days_is_idempotent_upsert(engine):
    with session_scope(engine) as s:
        aid = _alice(s).id
        tos.set_days(s, aid, [date(2026, 7, 20)], "pto", "v1")
        tos.set_days(s, aid, [date(2026, 7, 20)], "holiday", "v2")  # same day, retype
    with session_scope(engine) as s:
        cal = tos.member_calendar(s, aid, 2026, 7)
    assert cal[date(2026, 7, 20)] == ("holiday", "v2")  # exactly one row, replaced


def test_set_days_rejects_weekend(engine):
    with session_scope(engine) as s:
        aid = _alice(s).id
        with pytest.raises(ValidationError):
            tos.set_days(s, aid, [date(2026, 7, 25)], "pto", "")  # Saturday


def test_set_days_rejects_unknown_type(engine):
    with session_scope(engine) as s:
        aid = _alice(s).id
        with pytest.raises(ValidationError):
            tos.set_days(s, aid, [date(2026, 7, 20)], "vacation", "")


def test_clear_days_removes_rows(engine):
    with session_scope(engine) as s:
        aid = _alice(s).id
        tos.set_days(s, aid, [date(2026, 7, 20), date(2026, 7, 21)], "pto", "")
        tos.clear_days(s, aid, [date(2026, 7, 20)])
    with session_scope(engine) as s:
        cal = tos.member_calendar(s, aid, 2026, 7)
    assert date(2026, 7, 20) not in cal and date(2026, 7, 21) in cal


def test_outage_entries_filters_by_date_range(engine):
    with session_scope(engine) as s:
        aid = _alice(s).id
        tos.set_days(s, aid, [date(2026, 7, 20), date(2026, 8, 3)], "pto", "")
        names = {mem.id: mem.name for mem in cfgsvc.list_members(s)}
        entries = tos.outage_entries(s, date(2026, 7, 13), date(2026, 7, 24), names)
    flat = {(e.associate, d) for e in entries for d in e.days}
    assert ("Alice Anderson", date(2026, 7, 20)) in flat
    assert all(d <= date(2026, 7, 24) for e in entries for d in e.days)  # Aug 3 excluded


def test_build_month_grid_marks_weekends_and_types(engine):
    with session_scope(engine) as s:
        aid = _alice(s).id
        tos.set_days(s, aid, [date(2026, 7, 20)], "pto", "")
        letters = {t.key: t.abbreviation for t in tsvc.list_absence_types(s)}
        grid = tos.build_month_grid(2026, 7, tos.member_calendar(s, aid, 2026, 7), letters)
    cells = [c for week in grid for c in week]
    marked = next(c for c in cells if c["date"] == date(2026, 7, 20))
    assert marked["type"] == "pto" and marked["letter"] == "P" and marked["in_month"]
    sat = next(c for c in cells if c["date"] == date(2026, 7, 25))
    assert sat["weekend"] is True
