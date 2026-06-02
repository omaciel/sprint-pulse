# Individual-Level Time-Off Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move time-off from sprint-anchored to member-anchored, add a per-member calendar page for viewing/editing availability, and make sprints derive their team outage from date overlap.

**Architecture:** Replace the `TimeOff` + `TimeOffDay` tables with a single flat `MemberDayOff(member_id, date, type, notes)` table (unique per member/day). A one-off engine migration flattens legacy data. A new `time_off_service` owns all day-off reads/writes and reconstructs the existing frozen `TimeOffEntry` objects so `render.py` and the capacity math are reused unchanged. The member page is server-rendered Jinja + HTMX with one small `calendar.js` for click-to-paint. Sprints lose their time-off form, gain editable dates and a read-only derived outage list.

**Tech Stack:** Python 3.13, FastAPI, SQLModel/SQLAlchemy, Jinja2, HTMX, pytest (run via `uv run`).

**Branch:** `individual-time-off-calendar` (already created; the design spec is committed there).

---

## File Structure

**Create:**
- `sprint_pulse/services/time_off_service.py` — day-off CRUD, weekday validation, type-priority, `TimeOffEntry` reconstruction, month-grid + member-summary builders.
- `sprint_pulse/web/templates/member_detail.html` — the member page.
- `sprint_pulse/web/templates/partials/_calendar.html` — the swappable calendar + sidebar fragment (root `<div id="calendar">`).
- `sprint_pulse/web/templates/partials/_sprint_outage.html` — read-only derived outage list on the sprint page.
- `sprint_pulse/web/static/calendar.js` — palette selection + click-to-paint via `htmx.ajax`.
- `tests/test_time_off_service.py`, `tests/test_member_calendar.py` — new tests.

**Modify:**
- `sprint_pulse/db/models.py` — add `MemberDayOff`; remove `TimeOff`, `TimeOffDay` (Task 6).
- `sprint_pulse/db/engine.py` — add legacy-flatten migration.
- `sprint_pulse/sprints.py` — extract `weekday_error`; reuse in `working_day_error`.
- `sprint_pulse/services/sprint_service.py` — derive outage from `MemberDayOff`; drop `add/delete_time_off`; `delete_sprint` cascades events only; add `set_sprint_dates`.
- `sprint_pulse/services/config_service.py` — `remove_member` cascades `MemberDayOff`.
- `sprint_pulse/migrate.py` — import writes `MemberDayOff`; update `_wipe` + counts.
- `sprint_pulse/web/routers/members.py` — member-detail GET + time-off set/clear POSTs.
- `sprint_pulse/web/routers/sprints.py` — remove time-off routes; add edit-dates; derived outage in `_detail_context`.
- `sprint_pulse/web/templates/sprint_detail.html` — remove time-off form; add edit-dates form + outage include.
- `sprint_pulse/web/templates/partials/_members_table.html` — link member name to `/members/{id}`.
- `tests/test_services.py`, `tests/test_api.py`, `tests/test_migration.py`, `tests/test_render.py` — update for the new model.

**Delete:**
- `sprint_pulse/web/templates/partials/_timeoff.html` (Task 4).

---

## Task 1: Add `MemberDayOff` model + legacy-flatten migration

**Files:**
- Modify: `sprint_pulse/db/models.py`
- Modify: `sprint_pulse/db/engine.py:91-110`
- Test: `tests/test_migration.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_migration.py`:

```python
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
    tables = {t for (t,) in eng.connect().exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "timeoff" not in tables and "timeoffday" not in tables
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_migration.py::test_legacy_timeoff_is_flattened_and_dropped -v`
Expected: FAIL — `MemberDayOff` does not exist / table not flattened.

- [ ] **Step 3: Add the model** — in `sprint_pulse/db/models.py`, add the import and class (leave `TimeOff`/`TimeOffDay` in place for now):

```python
from sqlalchemy import UniqueConstraint  # add near the top imports
```

```python
class MemberDayOff(SQLModel, table=True):
    """One row per (member, working day) absence. Replaces TimeOff + TimeOffDay.
    Not anchored to a sprint — sprints derive outage by date overlap."""
    id: Optional[int] = Field(default=None, primary_key=True)
    member_id: int = Field(foreign_key="teammember.id", index=True)
    date: date = Field(index=True)
    type: str = "pto"  # pto | holiday | company | partial | tentative
    notes: str = ""
    __table_args__ = (UniqueConstraint("member_id", "date", name="uq_member_day"),)
```

- [ ] **Step 4: Add the migration** — in `sprint_pulse/db/engine.py`, add the priority map + flatten function and call it from `create_db_and_tables`:

```python
# Higher wins when the same (member, day) carried two types in legacy data.
_TYPE_PRIORITY = {"company": 4, "holiday": 3, "pto": 2, "partial": 1, "tentative": 0}


def _migrate_legacy_timeoff(engine: Engine) -> None:
    """Flatten legacy TimeOff+TimeOffDay into MemberDayOff, then drop them.
    No-op once the legacy tables are gone (idempotent)."""
    with engine.begin() as conn:
        names = {row[0] for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "timeoff" not in names or "timeoffday" not in names:
            return
        rows = conn.exec_driver_sql(
            "SELECT t.member_id, d.date, t.type, t.notes "
            "FROM timeoff t JOIN timeoffday d ON d.time_off_id = t.id"
        ).fetchall()
        best: dict[tuple, tuple[str, str]] = {}
        for member_id, dt, type_, notes in rows:
            key = (member_id, dt)
            cur = best.get(key)
            if cur is None or _TYPE_PRIORITY.get(type_, 0) > _TYPE_PRIORITY.get(cur[0], 0):
                best[key] = (type_, notes or (cur[1] if cur else ""))
            elif not cur[1] and notes:
                best[key] = (cur[0], notes)
        for (member_id, dt), (type_, notes) in best.items():
            conn.exec_driver_sql(
                "INSERT OR IGNORE INTO memberdayoff (member_id, date, type, notes) "
                "VALUES (?, ?, ?, ?)", (member_id, dt, type_, notes or ""))
        conn.exec_driver_sql("DROP TABLE timeoffday")
        conn.exec_driver_sql("DROP TABLE timeoff")
```

Then update `create_db_and_tables`:

```python
def create_db_and_tables(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    _ensure_columns(engine)
    _migrate_legacy_timeoff(engine)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_migration.py::test_legacy_timeoff_is_flattened_and_dropped -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sprint_pulse/db/models.py sprint_pulse/db/engine.py tests/test_migration.py
git commit -m "Add MemberDayOff model + legacy time-off flatten migration"
```

---

## Task 2: `time_off_service` — reads, writes, validation, view builders

**Files:**
- Create: `sprint_pulse/services/time_off_service.py`
- Modify: `sprint_pulse/sprints.py:94-103` (extract `weekday_error`)
- Test: `tests/test_time_off_service.py`

- [ ] **Step 1: Extract `weekday_error` in `sprints.py`** (DRY — reused by the new service):

Replace the body of `working_day_error` and add `weekday_error` above it:

```python
def weekday_error(d: date) -> str | None:
    """Why ``d`` is not a Mon–Fri working day (or None)."""
    if d.weekday() >= 5:
        return f"{d.isoformat()} is a {_WEEKDAY_NAMES[d.weekday()]}"
    return None


def working_day_error(d: date, start: date, end: date) -> str | None:
    """Why ``d`` is not a valid working day inside ``[start, end]`` (or None)."""
    err = weekday_error(d)
    if err:
        return err
    if not (start <= d <= end):
        return (
            f"{d.isoformat()} is outside sprint range "
            f"{start.isoformat()}..{end.isoformat()}"
        )
    return None
```

- [ ] **Step 2: Write the failing test** — create `tests/test_time_off_service.py`:

```python
"""time_off_service: day-off CRUD, validation, outage derivation, view builders."""
from datetime import date

import pytest

from sprint_pulse.db import models as m
from sprint_pulse.db.engine import get_engine, session_scope
from sprint_pulse.errors import ValidationError
from sprint_pulse.migrate import import_yaml
from sprint_pulse.services import config_service as cfgsvc
from sprint_pulse.services import time_off_service as tos


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
        grid = tos.build_month_grid(2026, 7, tos.member_calendar(s, aid, 2026, 7))
    cells = [c for week in grid for c in week]
    marked = next(c for c in cells if c["date"] == date(2026, 7, 20))
    assert marked["type"] == "pto" and marked["letter"] == "P" and marked["in_month"]
    sat = next(c for c in cells if c["date"] == date(2026, 7, 25))
    assert sat["weekend"] is True
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_time_off_service.py -v`
Expected: FAIL — `time_off_service` module does not exist.

- [ ] **Step 4: Implement `sprint_pulse/services/time_off_service.py`:**

```python
"""Member day-off CRUD + derivations.

Time-off lives on the member (one MemberDayOff row per working day), never on a
sprint. The dashboard reconstructs the existing frozen ``TimeOffEntry`` objects
from these rows (grouped per type+notes) so ``render.py`` is reused unchanged;
sprints derive their outage by date overlap.
"""
from __future__ import annotations

import calendar as _cal
from datetime import date

from sqlmodel import Session, select

from sprint_pulse.db import models as m
from sprint_pulse.errors import ValidationError
from sprint_pulse.render import TYPE_LETTERS
from sprint_pulse.sprints import TimeOffEntry, weekday_error

VALID_TYPES = ("pto", "holiday", "company", "partial", "tentative")
# Higher wins when grouping/merging conflicting days.
TYPE_PRIORITY = {"company": 4, "holiday": 3, "pto": 2, "partial": 1, "tentative": 0}


def _require_member(session: Session, member_id: int) -> m.TeamMember:
    member = session.get(m.TeamMember, member_id)
    if member is None:
        raise ValidationError(f"no team member with id {member_id}")
    return member


def set_days(session: Session, member_id: int, dates, type_: str, notes: str = "") -> None:
    """Upsert one MemberDayOff per date (replacing type/notes if present)."""
    _require_member(session, member_id)
    if type_ not in VALID_TYPES:
        raise ValidationError(
            f'unknown type "{type_}" (expected {"/".join(VALID_TYPES)})', field="type"
        )
    dates = list(dates)
    if not dates:
        raise ValidationError("at least one day is required", field="days")
    for d in dates:
        err = weekday_error(d)
        if err:
            raise ValidationError(err, field="days")
    for d in dates:
        row = session.exec(
            select(m.MemberDayOff).where(
                m.MemberDayOff.member_id == member_id, m.MemberDayOff.date == d
            )
        ).first()
        if row is None:
            session.add(m.MemberDayOff(member_id=member_id, date=d, type=type_, notes=notes or ""))
        else:
            row.type = type_
            row.notes = notes or ""
            session.add(row)


def clear_days(session: Session, member_id: int, dates) -> None:
    for d in dates:
        row = session.exec(
            select(m.MemberDayOff).where(
                m.MemberDayOff.member_id == member_id, m.MemberDayOff.date == d
            )
        ).first()
        if row is not None:
            session.delete(row)


def member_calendar(session: Session, member_id: int, year: int, month: int) -> dict:
    """{date: (type, notes)} for the given member + month."""
    lo = date(year, month, 1)
    hi = date(year, month, _cal.monthrange(year, month)[1])
    rows = session.exec(
        select(m.MemberDayOff).where(
            m.MemberDayOff.member_id == member_id,
            m.MemberDayOff.date >= lo,
            m.MemberDayOff.date <= hi,
        )
    ).all()
    return {r.date: (r.type, r.notes) for r in rows}


def _entries_from_rows(rows, member_name: dict) -> list[TimeOffEntry]:
    """Group MemberDayOff rows into TimeOffEntry objects per (member, type, notes)."""
    by_kind: dict[tuple, list[date]] = {}
    for r in rows:
        if r.member_id not in member_name:
            continue
        by_kind.setdefault((r.member_id, r.type, r.notes), []).append(r.date)
    out: list[TimeOffEntry] = []
    for (mid, type_, notes), days in by_kind.items():
        out.append(
            TimeOffEntry(
                associate=member_name[mid], days=tuple(sorted(days)), notes=notes, type=type_
            )
        )
    return out


def outage_entries(session: Session, start: date, end: date, member_name: dict) -> list[TimeOffEntry]:
    """TimeOffEntry list for all members whose days fall in [start, end]."""
    rows = session.exec(
        select(m.MemberDayOff).where(
            m.MemberDayOff.date >= start, m.MemberDayOff.date <= end
        )
    ).all()
    return _entries_from_rows(rows, member_name)


def entries_for_sprints(rows, member_name: dict, start: date, end: date) -> list[TimeOffEntry]:
    """In-memory variant used by the bulk dashboard load (rows already fetched)."""
    in_range = [r for r in rows if start <= r.date <= end]
    return _entries_from_rows(in_range, member_name)


def build_month_grid(year: int, month: int, day_map: dict) -> list[list[dict]]:
    """Weeks (Mon-first) of cell dicts for the calendar template."""
    weeks: list[list[dict]] = []
    for week in _cal.Calendar(firstweekday=0).monthdatescalendar(year, month):
        cells: list[dict] = []
        for d in week:
            type_, notes = day_map.get(d, ("", ""))
            cells.append({
                "date": d,
                "day": d.day,
                "in_month": d.month == month,
                "weekend": d.weekday() >= 5,
                "type": type_,
                "notes": notes,
                "letter": TYPE_LETTERS.get(type_, ""),
            })
        weeks.append(cells)
    return weeks
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_time_off_service.py tests/test_sprints.py -v`
Expected: PASS (the `weekday_error` extraction keeps `test_sprints.py` green).

- [ ] **Step 6: Commit**

```bash
git add sprint_pulse/services/time_off_service.py sprint_pulse/sprints.py tests/test_time_off_service.py
git commit -m "Add time_off_service: member day-off CRUD, outage derivation, calendar builders"
```

---

## Task 3: Route the dashboard + import + cascades through `MemberDayOff`

This makes the app write/read the new table everywhere except the (about-to-be-removed) sprint time-off routes. After this task the legacy `TimeOff` model is no longer read or written.

**Files:**
- Modify: `sprint_pulse/migrate.py:79-110, 113-126`
- Modify: `sprint_pulse/services/sprint_service.py:47-82, 158-168, 308-365`
- Modify: `sprint_pulse/services/config_service.py:147-162`
- Test: `tests/test_migration.py`, `tests/test_services.py`

- [ ] **Step 1: Update `migrate.py` import + `_wipe`.** Replace the time-off loop (lines ~88-100) with a deduped per-day write, and update the wipe/counters:

```python
from sprint_pulse.services.time_off_service import TYPE_PRIORITY  # add to imports
```

Replace the `for entry in sprint.time_off:` block and the counters with:

```python
        # Sprints + events.
        n_events = 0
        day_off: dict[tuple, tuple[str, str]] = {}  # (member_id, date) -> (type, notes)
        for sprint in sprints:
            session.add(m.Sprint(id=sprint.id, start=sprint.start, end=sprint.end))
            for ev in sprint.events:
                session.add(
                    m.Event(sprint_id=sprint.id, date=ev.date, kind=ev.kind, title=ev.title)
                )
                n_events += 1
            for entry in sprint.time_off:
                mid = members[entry.associate].id
                for d in entry.days:
                    key = (mid, d)
                    cur = day_off.get(key)
                    if cur is None or TYPE_PRIORITY[entry.type] > TYPE_PRIORITY[cur[0]]:
                        day_off[key] = (entry.type, entry.notes or (cur[1] if cur else ""))
                    elif not cur[1] and entry.notes:
                        day_off[key] = (cur[0], entry.notes)
        for (mid, d), (type_, notes) in day_off.items():
            session.add(m.MemberDayOff(member_id=mid, date=d, type=type_, notes=notes))

    return {
        "members": len(cfg.roster),
        "orchestration": len(cfg.orchestration),
        "aliases": len(cfg.name_aliases),
        "sprints": len(sprints),
        "events": n_events,
        "days_off": len(day_off),
    }
```

In `_wipe`, swap the legacy tables for the new one:

```python
    for model in (
        m.MemberDayOff,
        m.Event,
        m.Sprint,
        m.NameAlias,
        m.TeamMember,
        m.Settings,
    ):
```

- [ ] **Step 2: Update `tests/test_migration.py` counts.** Find the assertion on the import return dict and replace the time-off keys. Add/adjust:

```python
def test_import_counts_days_off(valid_dir):
    from sprint_pulse.db.engine import get_engine
    from sprint_pulse.migrate import import_yaml
    eng = get_engine(":memory:")
    counts = import_yaml(eng, valid_dir / "config.yaml", valid_dir / "sprints_dir")
    assert "days_off" in counts and counts["days_off"] > 0
    assert "time_off" not in counts
```

Update any existing test in this file that asserts `counts["time_off"]` / `counts["time_off_days"]` to use `counts["days_off"]`.

- [ ] **Step 3: Update `sprint_service._load`** to derive outage from `MemberDayOff`. Replace lines ~52-80 (the `timeoff_by_sprint`/`days_by_entry` queries and the per-sprint time_off build):

```python
    member_name = {member.id: member.name for member in config_service.list_members(session)}

    rows = list(session.exec(select(m.Sprint)).all())
    events_by_sprint = _group(session.exec(select(m.Event)).all(), lambda e: e.sprint_id)
    dayoff_rows = list(session.exec(select(m.MemberDayOff)).all())

    sprints: list[Sprint] = []
    for row in rows:
        events = tuple(
            Event(date=e.date, kind=e.kind, title=e.title)
            for e in sorted(events_by_sprint.get(row.id, []), key=lambda e: e.date)
        )
        time_off = tuple(
            time_off_service.entries_for_sprints(dayoff_rows, member_name, row.start, row.end)
        )
        sprints.append(
            Sprint(id=row.id, start=row.start, end=row.end, events=events, time_off=time_off)
        )
    sprints.sort(key=sort_key)
    return sprints, {row.id: row for row in rows}
```

Add the import at the top of `sprint_service.py`:

```python
from sprint_pulse.services import config_service, jira_service, time_off_service
```

- [ ] **Step 4: Simplify `delete_sprint`** (time-off is no longer sprint-anchored — events only):

```python
def delete_sprint(session: Session, sprint_id: str) -> None:
    sprint = _get_sprint(session, sprint_id)
    for event in session.exec(select(m.Event).where(m.Event.sprint_id == sprint_id)).all():
        session.delete(event)
    session.delete(sprint)
```

- [ ] **Step 5: Remove `add_time_off` / `delete_time_off`** from `sprint_service.py` (lines ~308-365, the whole `# --- Time-off CRUD` section) and drop the now-unused `infer_type`, `_suggest`, `_ALL` imports/usages if they are no longer referenced in this file. (Leave `working_day_error`, `event_kind_error` — still used by events.)

- [ ] **Step 6: Update `config_service.remove_member`** cascade (lines ~154-161) to delete `MemberDayOff`:

```python
    for row in session.exec(
        select(m.MemberDayOff).where(m.MemberDayOff.member_id == member_id)
    ).all():
        session.delete(row)
    session.delete(member)
```

- [ ] **Step 7: Update `tests/test_services.py`.** Remove/replace the `add_time_off`/`delete_time_off` tests (search `add_time_off`) with day-off equivalents driven through `time_off_service`, and assert dashboard hydration still produces the absence. Example replacement:

```python
def test_dashboard_hydration_reflects_member_day_off(engine):
    from sprint_pulse.services import time_off_service as tos
    with session_scope(engine) as s:
        alice = next(m for m in cfgsvc.list_members(s) if m.name == "Alice Anderson")
        sprint = spsvc._get_sprint(s, "2026-16")
        tos.set_days(s, alice.id, [sprint.start], "pto", "PTO")
    with session_scope(engine) as s:
        sprints = spsvc.build_sprints_from_db(s)
    target = next(sp for sp in sprints if sp.id == "2026-16")
    assert any(e.associate == "Alice Anderson" and target.start in e.days
               for e in target.time_off)
```

(Use a real sprint id + date from `tests/fixtures/valid`; `2026-16` and its `start` exist in the fixtures.)

- [ ] **Step 8: Run the affected suites**

Run: `uv run pytest tests/test_migration.py tests/test_services.py tests/test_render.py tests/test_integration.py -v`
Expected: PASS. If `test_render.py` snapshots differ, inspect the diff — output should be identical for equivalent data; only regenerate with `uv run pytest --snapshot-update` if the change is provably cosmetic-free.

- [ ] **Step 9: Commit**

```bash
git add sprint_pulse/migrate.py sprint_pulse/services/sprint_service.py \
        sprint_pulse/services/config_service.py tests/test_migration.py tests/test_services.py
git commit -m "Derive sprint outage from MemberDayOff; import + cascades use the flat model"
```

---

## Task 4: Rework the sprint page — drop time-off form, add edit-dates + derived outage

**Files:**
- Modify: `sprint_pulse/services/sprint_service.py` (add `set_sprint_dates`)
- Modify: `sprint_pulse/web/routers/sprints.py:163-275`
- Modify: `sprint_pulse/web/templates/sprint_detail.html`
- Create: `sprint_pulse/web/templates/partials/_sprint_outage.html`
- Delete: `sprint_pulse/web/templates/partials/_timeoff.html`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_api.py`:

```python
def test_edit_sprint_dates_rederives_outage(seeded_client):
    from datetime import date
    from sprint_pulse.db.engine import session_scope
    from sprint_pulse.services import config_service as cfgsvc
    from sprint_pulse.services import time_off_service as tos

    eng = seeded_client.app.state.engine
    with session_scope(eng) as s:
        alice = next(m for m in cfgsvc.list_members(s) if m.name == "Alice Anderson")
        tos.set_days(s, alice.id, [date(2026, 5, 5)], "pto", "PTO")  # outside 2026-16
    # Move the sprint window to cover May 5.
    r = seeded_client.post("/sprints/2026-16/dates",
                           data={"start": "2026-05-04", "end": "2026-05-15"})
    assert r.status_code in (200, 303)
    detail = seeded_client.get("/sprints/2026-16").text
    assert "Alice Anderson" in detail  # now appears in the derived outage list


def test_sprint_timeoff_routes_are_gone(seeded_client):
    r = seeded_client.post("/sprints/2026-16/timeoff",
                           data={"associate": "Alice Anderson", "start": "2026-04-20",
                                 "end": "2026-04-20", "notes": "PTO"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_api.py::test_edit_sprint_dates_rederives_outage tests/test_api.py::test_sprint_timeoff_routes_are_gone -v`
Expected: FAIL — no `/dates` route; `/timeoff` still exists.

- [ ] **Step 3: Add `set_sprint_dates`** to `sprint_service.py` (near `create_sprint`):

```python
def set_sprint_dates(session: Session, sprint_id: str, start: date, end: date) -> m.Sprint:
    sprint = _get_sprint(session, sprint_id)
    if end < start:
        raise ValidationError(
            f"end ({end.isoformat()}) is before start ({start.isoformat()})", field="end"
        )
    sprint.start = start
    sprint.end = end
    session.add(sprint)
    return sprint
```

- [ ] **Step 4: Rewrite the sprint router's time-off section.** In `sprint_pulse/web/routers/sprints.py`:

Replace `_detail_context` (lines ~163-194) with a version that derives outage and drops the legacy time-off queries:

```python
def _detail_context(session: Session, sprint_id: str, *, event_error="", date_error=""):
    sprint = session.get(m.Sprint, sprint_id)
    events = session.exec(
        select(m.Event).where(m.Event.sprint_id == sprint_id).order_by(m.Event.date)
    ).all()
    member_name = {mem.id: mem.name for mem in config_service.list_members(session)}
    outage = []
    if sprint is not None:
        outage = sorted(
            time_off_service.outage_entries(session, sprint.start, sprint.end, member_name),
            key=lambda e: (e.associate, e.days[0]),
        )
    return {
        "active": "/sprints",
        "sprint": sprint,
        "events": events,
        "event_kinds": EVENT_KINDS,
        "outage": outage,
        "event_error": event_error,
        "date_error": date_error,
    }
```

Update imports at the top of the file:

```python
from sprint_pulse.services import config_service, sprint_service, time_off_service
```

Delete the `add_time_off` and `delete_time_off` routes (lines ~239-275) and the now-unused `working_days` import. Add the edit-dates route after `sprint_detail`:

```python
@router.post("/sprints/{sprint_id}/dates", response_class=HTMLResponse)
def set_dates(
    request: Request,
    sprint_id: str,
    start: date = Form(...),
    end: date = Form(...),
    session: Session = Depends(get_session),
):
    error = ""
    try:
        sprint_service.set_sprint_dates(session, sprint_id, start, end)
    except ValidationError as e:
        session.rollback()
        error = e.display()
    return templates.TemplateResponse(
        request, "sprint_detail.html", _detail_context(session, sprint_id, date_error=error)
    )
```

(The `add_event` / `delete_event` routes keep working — they call `_detail_context` with `event_error=...`, which still exists.)

- [ ] **Step 5: Create `partials/_sprint_outage.html`:**

```html
{% if outage %}
<table class="grid">
  <thead><tr><th>Associate</th><th>Days</th><th>Type</th></tr></thead>
  <tbody>
    {% for e in outage %}
    <tr>
      <td><a class="link" href="/members/{{ member_id_by_name[e.associate] }}">{{ e.associate }}</a></td>
      <td>{{ e.days[0] }}{% if e.days|length > 1 %} → {{ e.days[-1] }}{% endif %} ({{ e.days|length }}d)</td>
      <td><span class="pill {{ e.type }}">{{ e.type }}</span></td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<p class="muted">No one is out during this sprint.</p>
{% endif %}
```

The outage list links to member pages, so add `member_id_by_name` to `_detail_context`'s returned dict:

```python
        "member_id_by_name": {name: mid for mid, name in member_name.items()},
```

- [ ] **Step 6: Rewrite `sprint_detail.html`.** Replace the whole "Time off" card (lines 8-39) with an editable-dates card + read-only outage card; keep the Release events card unchanged:

```html
{% extends "base.html" %}
{% block title %}{{ sprint.id }} · Sprint Pulse{% endblock %}
{% block content %}
<p><a class="link" href="/sprints">← All sprints</a></p>
<h1>Sprint {{ sprint.id }}</h1>
<p class="subtitle">{{ sprint.start }} → {{ sprint.end }} · <span class="pill {{ sprint.jira_state }}">{{ sprint.jira_state }}</span></p>

<div class="card">
  <h2>Dates</h2>
  {% if date_error %}<p class="error">{{ date_error }}</p>{% endif %}
  <form hx-post="/sprints/{{ sprint.id }}/dates" hx-target="body" hx-swap="outerHTML">
    <div class="row" style="align-items:flex-end">
      <div><label for="start">Start</label>
        <input type="date" id="start" name="start" value="{{ sprint.start }}" required></div>
      <div><label for="end">End</label>
        <input type="date" id="end" name="end" value="{{ sprint.end }}" required></div>
      <div style="flex:0 0 auto; min-width:auto"><button type="submit">Save dates</button></div>
    </div>
    <p class="field-hint">Changing the window re-derives who is out from member calendars.</p>
  </form>
</div>

<div class="card">
  <h2>Out this sprint</h2>
  <p class="field-hint">Read-only — edit time off on each member's page (Team → name).</p>
  {% include "partials/_sprint_outage.html" %}
</div>

<div class="card">
  <h2>Release events</h2>
  <form hx-post="/sprints/{{ sprint.id }}/events" hx-target="#events" hx-swap="innerHTML"
        hx-on::after-request="if(event.detail.successful) this.reset()">
    <div class="row" style="align-items:flex-end">
      <div>
        <label for="event_date">Date</label>
        <input type="date" id="event_date" name="event_date" value="{{ sprint.start }}" required>
      </div>
      <div>
        <label for="kind">Kind</label>
        <select id="kind" name="kind" required>
          {% for k in event_kinds %}<option value="{{ k }}">{{ k }}</option>{% endfor %}
        </select>
      </div>
      <div style="flex:2">
        <label for="title">Title</label>
        <input type="text" id="title" name="title" placeholder="Git tags due · 4PM EST" required>
      </div>
      <div style="flex:0 0 auto; min-width:auto"><button type="submit">Add</button></div>
    </div>
  </form>
  <div id="events" style="margin-top:16px">
    {% include "partials/_events.html" %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 7: Delete the dead partial**

```bash
git rm sprint_pulse/web/templates/partials/_timeoff.html
```

- [ ] **Step 8: Run the suite**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS. (Search the file for any other `/timeoff` references and update/remove them.)

- [ ] **Step 9: Commit**

```bash
git add sprint_pulse/services/sprint_service.py sprint_pulse/web/routers/sprints.py \
        sprint_pulse/web/templates/sprint_detail.html \
        sprint_pulse/web/templates/partials/_sprint_outage.html tests/test_api.py
git commit -m "Sprint page: editable dates + read-only derived outage; remove time-off form"
```

---

## Task 5: Member calendar page

**Files:**
- Modify: `sprint_pulse/web/routers/members.py`
- Create: `sprint_pulse/web/templates/member_detail.html`
- Create: `sprint_pulse/web/templates/partials/_calendar.html`
- Create: `sprint_pulse/web/static/calendar.js`
- Modify: `sprint_pulse/web/templates/partials/_members_table.html:9`
- Test: `tests/test_member_calendar.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_member_calendar.py`:

```python
"""Member calendar page: render, paint, clear, range, roster link."""
import pytest
from fastapi.testclient import TestClient

from sprint_pulse.migrate import import_yaml
from sprint_pulse.web.app import create_app


@pytest.fixture
def client(valid_dir):
    app = create_app(":memory:")
    import_yaml(app.state.engine, valid_dir / "config.yaml", valid_dir / "sprints_dir")
    return TestClient(app)


def _alice_id(client):
    from sprint_pulse.db.engine import session_scope
    from sprint_pulse.services import config_service as cfgsvc
    with session_scope(client.app.state.engine) as s:
        return next(m.id for m in cfgsvc.list_members(s) if m.name == "Alice Anderson")


def test_member_page_renders_calendar(client):
    r = client.get(f"/members/{_alice_id(client)}?month=2026-07")
    assert r.status_code == 200
    assert "Alice Anderson" in r.text
    assert 'id="calendar"' in r.text


def test_paint_then_clear_single_day(client):
    mid = _alice_id(client)
    r = client.post(f"/members/{mid}/timeoff",
                    data={"date": "2026-07-20", "type": "pto", "notes": "PTO", "month": "2026-07"})
    assert r.status_code == 200 and "P" in r.text
    r2 = client.post(f"/members/{mid}/timeoff/clear",
                     data={"date": "2026-07-20", "month": "2026-07"})
    assert r2.status_code == 200
    from sprint_pulse.db.engine import session_scope
    from sprint_pulse.services import time_off_service as tos
    from datetime import date
    with session_scope(client.app.state.engine) as s:
        assert date(2026, 7, 20) not in tos.member_calendar(s, mid, 2026, 7)


def test_range_quick_add(client):
    mid = _alice_id(client)
    r = client.post(f"/members/{mid}/timeoff",
                    data={"start": "2026-07-20", "end": "2026-07-24", "type": "pto",
                          "notes": "", "month": "2026-07"})
    assert r.status_code == 200
    from sprint_pulse.db.engine import session_scope
    from sprint_pulse.services import time_off_service as tos
    with session_scope(client.app.state.engine) as s:
        cal = tos.member_calendar(s, mid, 2026, 7)
    assert len(cal) == 5  # Mon-Fri, weekend skipped


def test_weekend_paint_is_rejected_gracefully(client):
    mid = _alice_id(client)
    r = client.post(f"/members/{mid}/timeoff",
                    data={"date": "2026-07-25", "type": "pto", "notes": "", "month": "2026-07"})
    assert r.status_code == 200  # returns the calendar with an inline error, not a 500
    assert "Saturday" in r.text


def test_roster_links_to_member_page(client):
    r = client.get("/members")
    assert f'href="/members/{_alice_id(client)}"' in r.text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_member_calendar.py -v`
Expected: FAIL — routes/templates absent.

- [ ] **Step 3: Add routes to `sprint_pulse/web/routers/members.py`.** Add imports and a shared month-parser + calendar-context helper, then the three routes:

```python
from datetime import date

from sprint_pulse.services import config_service, time_off_service
from sprint_pulse.sprints import working_days
```

```python
def _parse_month(value: str | None) -> tuple[int, int]:
    """'YYYY-MM' -> (year, month); falls back to today."""
    try:
        y, mo = (value or "").split("-")
        return int(y), int(mo)
    except (ValueError, AttributeError):
        today = date.today()
        return today.year, today.month


def _shift_month(year: int, month: int, delta: int) -> str:
    idx = (year * 12 + (month - 1)) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _calendar_context(session: Session, member_id: int, month: str | None, *, error: str = "") -> dict:
    member = config_service._get_member(session, member_id)
    year, mo = _parse_month(month)
    day_map = time_off_service.member_calendar(session, member_id, year, mo)
    today = date.today()
    all_rows = sorted(
        time_off_service.member_calendar_all(session, member_id).items()
    )
    return {
        "active": "/members",
        "member": member,
        "month_value": f"{year:04d}-{mo:02d}",
        "month_label": f"{date(year, mo, 1):%B %Y}",
        "prev_month": _shift_month(year, mo, -1),
        "next_month": _shift_month(year, mo, 1),
        "weeks": time_off_service.build_month_grid(year, mo, day_map),
        "types": time_off_service.VALID_TYPES,
        "summary": time_off_service.member_summary(session, member_id, today),
        "error": error,
    }


@router.get("/members/{member_id}", response_class=HTMLResponse)
def member_detail(request: Request, member_id: int, month: str = "", session: Session = Depends(get_session)):
    try:
        ctx = _calendar_context(session, member_id, month or None)
    except ValidationError:
        return RedirectResponse("/members", status_code=303)
    return templates.TemplateResponse(request, "member_detail.html", ctx)


@router.post("/members/{member_id}/timeoff", response_class=HTMLResponse)
def set_member_time_off(
    request: Request,
    member_id: int,
    date_: str = Form("", alias="date"),
    start: str = Form(""),
    end: str = Form(""),
    type: str = Form("pto"),
    notes: str = Form(""),
    month: str = Form(""),
    session: Session = Depends(get_session),
):
    error = ""
    try:
        if start and end:
            s, e = date.fromisoformat(start), date.fromisoformat(end)
            days = working_days(s, e) if e >= s else []
            if not days:
                raise ValidationError("end is before start", field="end")
        elif date_:
            days = [date.fromisoformat(date_)]
        else:
            raise ValidationError("a date is required", field="date")
        time_off_service.set_days(session, member_id, days, type, notes)
    except ValidationError as exc:
        session.rollback()
        error = exc.display()
    return templates.TemplateResponse(
        request, "partials/_calendar.html", _calendar_context(session, member_id, month, error=error)
    )


@router.post("/members/{member_id}/timeoff/clear", response_class=HTMLResponse)
def clear_member_time_off(
    request: Request,
    member_id: int,
    date_: str = Form("", alias="date"),
    month: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        if date_:
            time_off_service.clear_days(session, member_id, [date.fromisoformat(date_)])
    except ValidationError:
        session.rollback()
    return templates.TemplateResponse(
        request, "partials/_calendar.html", _calendar_context(session, member_id, month)
    )
```

Add `RedirectResponse` to the FastAPI imports at the top of the file:

```python
from fastapi.responses import HTMLResponse, RedirectResponse
```

- [ ] **Step 4: Add the two service helpers** referenced above to `time_off_service.py`:

```python
def member_calendar_all(session: Session, member_id: int) -> dict:
    rows = session.exec(
        select(m.MemberDayOff).where(m.MemberDayOff.member_id == member_id)
    ).all()
    return {r.date: (r.type, r.notes) for r in rows}


def _quarter(d: date) -> int:
    return (d.month - 1) // 3


def member_summary(session: Session, member_id: int, today: date) -> dict:
    rows = session.exec(
        select(m.MemberDayOff).where(m.MemberDayOff.member_id == member_id)
    ).all()
    year_days = [r for r in rows if r.date.year == today.year]
    quarter_days = [r for r in year_days if _quarter(r.date) == _quarter(today)]
    upcoming_rows = sorted((r for r in rows if r.date >= today), key=lambda r: r.date)
    # Merge consecutive same-type days into (start, end, type) runs.
    runs: list[dict] = []
    for r in upcoming_rows:
        if runs and runs[-1]["type"] == r.type and (r.date - runs[-1]["end"]).days <= 3:
            runs[-1]["end"] = r.date
        else:
            runs.append({"start": r.date, "end": r.date, "type": r.type})
    return {
        "year": len(year_days),
        "quarter": len(quarter_days),
        "upcoming": runs[:8],
    }
```

(The `<= 3` day gap merges Fri→Mon runs across a weekend without bridging unrelated absences.)

- [ ] **Step 5: Create `partials/_calendar.html`** (the swappable fragment — root carries `data-member`/`data-month` for `calendar.js`):

```html
<div id="calendar" data-member="{{ member.id }}" data-month="{{ month_value }}">
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  <div class="row" style="align-items:center; justify-content:space-between">
    <a class="link" hx-get="/members/{{ member.id }}?month={{ prev_month }}"
       hx-target="#calendar" hx-swap="outerHTML" href="#">‹ {{ prev_month }}</a>
    <strong>{{ month_label }}</strong>
    <a class="link" hx-get="/members/{{ member.id }}?month={{ next_month }}"
       hx-target="#calendar" hx-swap="outerHTML" href="#">{{ next_month }} ›</a>
  </div>
  <table class="cal">
    <thead><tr>
      <th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th><th>Sun</th>
    </tr></thead>
    <tbody>
      {% for week in weeks %}
      <tr>
        {% for c in week %}
          {% if c.weekend or not c.in_month %}
            <td class="cal-cell muted{% if not c.in_month %} outside{% endif %}">{{ c.day }}</td>
          {% else %}
            <td class="cal-cell day {{ c.type }}" data-date="{{ c.date }}" data-type="{{ c.type }}"
                title="{{ c.notes }}">{{ c.day }}<span class="cal-letter">{{ c.letter }}</span></td>
          {% endif %}
        {% endfor %}
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
```

Note the GET nav links target `#calendar` and swap `outerHTML`, but `member_detail` returns the *full page*; for the partial-only swap the GET must return the fragment when requested via HTMX. Handle that in `member_detail` by returning the partial when the `HX-Request` header is present:

```python
@router.get("/members/{member_id}", response_class=HTMLResponse)
def member_detail(request: Request, member_id: int, month: str = "", session: Session = Depends(get_session)):
    try:
        ctx = _calendar_context(session, member_id, month or None)
    except ValidationError:
        return RedirectResponse("/members", status_code=303)
    name = "partials/_calendar.html" if request.headers.get("HX-Request") else "member_detail.html"
    return templates.TemplateResponse(request, name, ctx)
```

- [ ] **Step 6: Create `member_detail.html`** (full page: palette + notes + calendar + sidebar). Reuse `_calendar.html` for the grid:

```html
{% extends "base.html" %}
{% block title %}{{ member.name }} · Sprint Pulse{% endblock %}
{% block content %}
<p><a class="link" href="/members">← Team</a></p>
<h1>{{ member.name }}</h1>

<div class="card">
  <div class="palette" id="palette">
    {% set letters = {"pto":"P","holiday":"H","company":"C","partial":"~","tentative":"?"} %}
    {% for t in types %}
      <span class="chip {{ t }}{% if loop.first %} sel{% endif %}" data-type="{{ t }}">{{ letters[t] }} {{ t }}</span>
    {% endfor %}
    <input type="text" id="cal-notes" placeholder="optional note…" style="flex:1; min-width:140px">
  </div>

  <div class="row" style="align-items:flex-start; gap:24px">
    <div style="flex:3">
      {% include "partials/_calendar.html" %}
      <p class="field-hint">Pick a type, then click weekdays to mark. Click a marked day of the same type to clear it.</p>
      <form hx-post="/members/{{ member.id }}/timeoff" hx-target="#calendar" hx-swap="outerHTML"
            hx-on::after-request="if(event.detail.successful) this.reset()" style="margin-top:10px">
        <input type="hidden" name="month" value="{{ month_value }}">
        <div class="row" style="align-items:flex-end">
          <div><label>From</label><input type="date" name="start" required></div>
          <div><label>To</label><input type="date" name="end" required></div>
          <div><label>Type</label><select name="type">
            {% for t in types %}<option value="{{ t }}">{{ t }}</option>{% endfor %}</select></div>
          <div style="flex:0 0 auto; min-width:auto"><button type="submit">Add range</button></div>
        </div>
      </form>
    </div>

    <div style="flex:1; min-width:180px">
      <div class="card" style="margin:0 0 12px"><h2>{{ summary.year }} days off</h2>
        <p class="muted">{{ summary.quarter }} this quarter</p></div>
      <div class="card" style="margin:0 0 12px"><h2>Orchestration</h2>
        <form hx-post="/members/{{ member.id }}/toggle" hx-target="#members-table" hx-swap="none">
          <label class="muted"><input type="checkbox" {% if member.is_orchestration %}checked{% endif %}
            onchange="this.form.requestSubmit()"> excluded from capacity</label>
        </form></div>
      <div class="card" style="margin:0"><h2>Upcoming</h2>
        {% if summary.upcoming %}<ul class="muted" style="padding-left:18px; margin:0">
          {% for u in summary.upcoming %}<li>{{ u.start }}{% if u.end != u.start %} → {{ u.end }}{% endif %} · {{ u.type }}</li>{% endfor %}
        </ul>{% else %}<p class="muted">Nothing scheduled.</p>{% endif %}</div>
    </div>
  </div>
</div>

<script src="/static/calendar.js"></script>
{% endblock %}
```

Add the calendar CSS to `base.html`'s `<style>` block (next to the existing `input[type=date]` rules) so cells/palette render:

```css
.cal { border-collapse:collapse; width:100%; font-size:13px; margin-top:6px }
.cal th { padding:5px; color:var(--muted); font-size:10px; text-transform:uppercase }
.cal-cell { border:1px solid var(--border); height:42px; width:14.2%; text-align:left;
  vertical-align:top; padding:4px; cursor:default }
.cal-cell.day { cursor:pointer }
.cal-cell.muted { background:#f6f6f6; color:#bbb }
.cal-cell.outside { background:#fafafa; color:#ccc }
.cal-letter { float:right; font-weight:600; font-size:11px }
.cal-cell.pto{background:var(--pto)} .cal-cell.holiday{background:var(--holiday)}
.cal-cell.partial{background:var(--partial)} .cal-cell.company{background:var(--company)}
.cal-cell.tentative{background:var(--tentative)}
.palette { display:flex; gap:6px; flex-wrap:wrap; align-items:center; margin-bottom:12px }
.chip { padding:5px 10px; border-radius:14px; font-size:12px; border:1px solid var(--border); cursor:pointer }
.chip.sel { outline:2px solid var(--text); font-weight:600 }
.chip.pto{background:var(--pto)} .chip.holiday{background:var(--holiday)}
.chip.partial{background:var(--partial)} .chip.company{background:var(--company)} .chip.tentative{background:var(--tentative)}
```

- [ ] **Step 7: Create `sprint_pulse/web/static/calendar.js`:**

```javascript
// Palette selection + click-to-paint for the member calendar. The only custom
// JS in the app: it tracks the active type and posts day clicks via HTMX.
(function () {
  let selectedType = "pto";

  document.addEventListener("click", function (e) {
    const chip = e.target.closest(".chip[data-type]");
    if (chip) {
      selectedType = chip.dataset.type;
      document.querySelectorAll(".chip[data-type]").forEach(function (c) {
        c.classList.toggle("sel", c === chip);
      });
      return;
    }
    const cell = e.target.closest("td.day[data-date]");
    if (!cell) return;
    const cal = document.getElementById("calendar");
    const memberId = cal.dataset.member;
    const month = cal.dataset.month;
    const notesEl = document.getElementById("cal-notes");
    const notes = notesEl ? notesEl.value : "";
    const clearing = cell.dataset.type === selectedType;
    const url = clearing
      ? "/members/" + memberId + "/timeoff/clear"
      : "/members/" + memberId + "/timeoff";
    const values = clearing
      ? { date: cell.dataset.date, month: month }
      : { date: cell.dataset.date, type: selectedType, notes: notes, month: month };
    htmx.ajax("POST", url, { target: "#calendar", swap: "outerHTML", values: values });
  });
})();
```

- [ ] **Step 8: Link roster names** — in `partials/_members_table.html`, change line 9 from `{{ member.name }}` to:

```html
<td><a class="link" href="/members/{{ member.id }}">{{ member.name }}</a></td>
```

- [ ] **Step 9: Run the suite**

Run: `uv run pytest tests/test_member_calendar.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add sprint_pulse/web/routers/members.py sprint_pulse/services/time_off_service.py \
        sprint_pulse/web/templates/member_detail.html \
        sprint_pulse/web/templates/partials/_calendar.html \
        sprint_pulse/web/templates/partials/_members_table.html \
        sprint_pulse/web/static/calendar.js \
        sprint_pulse/web/templates/base.html tests/test_member_calendar.py
git commit -m "Add member calendar page: click-to-paint time off + sidebar summary"
```

---

## Task 6: Remove the dead legacy models + final verification

**Files:**
- Modify: `sprint_pulse/db/models.py:88-99`
- Test: full suite

- [ ] **Step 1: Remove the legacy model classes.** Delete `TimeOff` (lines ~88-93) and `TimeOffDay` (lines ~96-99) from `sprint_pulse/db/models.py`. The flatten-migration in `engine.py` references the legacy tables only via raw SQL, so it keeps working on old DB files.

- [ ] **Step 2: Find any lingering references**

Run: `uv run python -c "import sprint_pulse.web.app"` and `grep -rn "TimeOffDay\|m\.TimeOff\b\|models.TimeOff" sprint_pulse tests`
Expected: no hits in `sprint_pulse/` (only the raw-SQL strings in `engine.py` and possibly the legacy-flatten test in `tests/test_migration.py`, which uses raw SQL — fine).

- [ ] **Step 3: Run the full suite + lint**

Run: `uv run pytest -v && uv run ruff check sprint_pulse tests`
Expected: all green.

- [ ] **Step 4: Manual smoke test** (optional but recommended)

```bash
SPRINT_PULSE_DB=$(mktemp -u).db uv run python -m uvicorn --factory sprint_pulse.web.app:create_app --port 8799 &
# open http://localhost:8799 → run the setup wizard or import, then:
#   Team → click a member → paint PTO on a weekday, navigate months, clear a day
#   Sprints → open a sprint → edit dates, confirm the outage list updates
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add sprint_pulse/db/models.py
git commit -m "Remove legacy TimeOff/TimeOffDay models (superseded by MemberDayOff)"
```

---

## Self-Review Notes

- **Spec coverage:** member-anchored model (Task 1, 3) ✓; weekday-only validation (Task 2) ✓; holidays stay per-member (no Holiday entity — unchanged) ✓; one-record-per-day + UNIQUE (Task 1) ✓; explicit type palette, inference kept for YAML import (Task 2, 3) ✓; one-big-month calendar (Task 5) ✓; sidebar stat/toggle/upcoming (Task 5) ✓; sprint page dates + events + read-only outage (Task 4) ✓; editable sprint dates (Task 4) ✓; migration flatten with conflict priority (Task 1) ✓; renderer reuse via `TimeOffEntry` reconstruction (Task 2, 3) ✓; tests across service/web/migration/snapshot (every task) ✓.
- **Out of scope (per spec):** team-wide Holiday entity; drag-to-paint (click + range quick-add only).
- **Type consistency:** `set_days`/`clear_days`/`member_calendar`/`outage_entries`/`entries_for_sprints`/`build_month_grid`/`member_calendar_all`/`member_summary` are defined in Task 2/5 and used with the same signatures in Tasks 3–5. `_detail_context` returns `outage` + `member_id_by_name` (Task 4) consumed by `_sprint_outage.html`. `#calendar` `data-member`/`data-month` (Task 5 template) match `calendar.js`.
- **Verification:** each task runs its own pytest selection; Task 6 runs the full suite + ruff; manual smoke covers the two user-facing flows.
