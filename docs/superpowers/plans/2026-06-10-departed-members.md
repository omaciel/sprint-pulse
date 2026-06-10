# Departed Members with Preserved History — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Members get optional tenure dates; each sprint shows and counts exactly the people whose tenure overlaps it (prorated for mid-sprint joins/leaves), with a Former-members UX instead of destructive delete.

**Architecture:** Two nullable date columns on `TeamMember` (added via the existing `_ADDED_COLUMNS` startup migration). The service layer builds a per-sprint `Config` copy (`dataclasses.replace`) whose roster/excluded are tenure-filtered and whose capacity is prorated via a new `capacity_override` field. `render.py` gets one focused extension: out-of-tenure days render as inert gray cells. Spec: `docs/superpowers/specs/2026-06-10-departed-members-design.md`.

**Tech Stack:** Python, FastAPI, SQLModel/SQLite, Jinja2 + HTMX, pytest.

**Conventions:** Run tests with `python3 -m pytest`. Commit after every task. All paths relative to repo root.

---

### Task 1: Schema — tenure columns + startup migration

**Files:**
- Modify: `sprint_pulse/db/models.py:47-51` (TeamMember)
- Modify: `sprint_pulse/db/engine.py:93-100` (`_ADDED_COLUMNS`)
- Test: `tests/test_departed_members.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_departed_members.py`:

```python
"""Departed-member feature: tenure columns, helpers, services, rendering."""
from datetime import date

import pytest

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_departed_members.py -v`
Expected: FAIL — `AttributeError: ... object has no attribute 'start_date'` (and the migration test fails on the missing columns).

- [ ] **Step 3: Add the model fields**

In `sprint_pulse/db/models.py`, change `TeamMember` to:

```python
class TeamMember(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    is_excluded: bool = False
    sort_order: int = 0
    # Tenure: NULL start = member since before recorded history; NULL end =
    # still on the team. Sprints show/count members whose tenure overlaps them.
    start_date: Optional[date] = None
    end_date: Optional[date] = None
```

(`date` is already imported at the top of the file.)

- [ ] **Step 4: Register the columns in the startup migration**

In `sprint_pulse/db/engine.py`, extend `_ADDED_COLUMNS`:

```python
_ADDED_COLUMNS = {
    "settings": [("team_name", "VARCHAR DEFAULT 'My Team'")],
    "sprint": [
        ("archived", "BOOLEAN DEFAULT 0"),
        ("jira_sprint_id", "INTEGER"),
        ("label", "VARCHAR DEFAULT ''"),
    ],
    "teammember": [
        ("start_date", "DATE"),
        ("end_date", "DATE"),
    ],
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_departed_members.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Run the full suite (no regressions)**

Run: `python3 -m pytest`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add sprint_pulse/db/models.py sprint_pulse/db/engine.py tests/test_departed_members.py
git commit -m "feat(db): add tenure columns to TeamMember with in-place migration"
```

---

### Task 2: Tenure helpers + Config fields (`tenures`, `capacity_override`)

**Files:**
- Modify: `sprint_pulse/config.py` (imports, module helpers, `Config`)
- Test: `tests/test_departed_members.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_departed_members.py`:

```python
from sprint_pulse.config import Config, JiraConfig, in_tenure, tenure_overlaps


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_departed_members.py -v`
Expected: FAIL — `ImportError: cannot import name 'in_tenure'`.

- [ ] **Step 3: Implement in `sprint_pulse/config.py`**

Update the imports at the top:

```python
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
```

Add the helpers right after `normalize_site` (module level):

```python
# A tenure is (start_date, end_date); None on either side means unbounded.
Tenure = tuple[date | None, date | None]


def in_tenure(tenure: Tenure | None, d: date) -> bool:
    """True when day ``d`` falls inside the member's tenure (inclusive)."""
    if tenure is None:
        return True
    start, end = tenure
    return (start is None or start <= d) and (end is None or d <= end)


def tenure_overlaps(tenure: Tenure | None, start: date, end: date) -> bool:
    """True when the tenure overlaps the [start, end] window (inclusive)."""
    if tenure is None:
        return True
    t_start, t_end = tenure
    return (t_start is None or t_start <= end) and (t_end is None or t_end >= start)
```

Extend `Config` (new fields after `absence_types`, and the updated `capacity` property):

```python
    # Per-member tenure, populated only for members that have tenure dates;
    # absent key = full tenure. Drives out-of-tenure cell rendering.
    tenures: dict[str, Tenure] = field(default_factory=dict)
    # Per-sprint prorated capacity, set on the per-sprint Config copies built
    # by sprint_service; None = derive from the roster as before.
    capacity_override: int | None = None

    @property
    def effective(self) -> list[str]:
        return [n for n in self.roster if n not in self.excluded]

    @property
    def capacity(self) -> int:
        if self.capacity_override is not None:
            return self.capacity_override
        return len(self.effective) * self.working_days_per_sprint
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_departed_members.py tests/test_config.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add sprint_pulse/config.py tests/test_departed_members.py
git commit -m "feat(config): tenure helpers + Config tenures/capacity_override fields"
```

---

### Task 3: Services — `depart_member` / `rejoin_member` / `add_member(start_date=...)`

**Files:**
- Modify: `sprint_pulse/services/config_service.py:131-177`
- Test: `tests/test_departed_members.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_departed_members.py`:

```python
from sprint_pulse.errors import ValidationError
from sprint_pulse.services import config_service as cfgsvc
from sprint_pulse.services import time_off_service as tosvc


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
        # Mon 2026-05-25 (kept) and Mon 2026-06-01 (after departure, trimmed)
        tosvc.set_days(s, mid, [date(2026, 5, 25)], "pto")
        tosvc.set_days(s, mid, [date(2026, 6, 1)], "pto")
    with session_scope(engine) as s:
        cfgsvc.depart_member(s, mid, date(2026, 5, 29))
    with session_scope(engine) as s:
        assert cfgsvc.get_member(s, mid).end_date == date(2026, 5, 29)
        remaining = tosvc.member_calendar(s, mid, 2026, 5) | tosvc.member_calendar(s, mid, 2026, 6)
        assert date(2026, 5, 25) in remaining
        assert date(2026, 6, 1) not in remaining


def test_depart_member_rejects_end_before_start(engine):
    with session_scope(engine) as s:
        member = cfgsvc.add_member(s, "New Hire", start_date=date(2026, 6, 1))
        with pytest.raises(ValidationError):
            cfgsvc.depart_member(s, member.id, date(2026, 5, 1))


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_departed_members.py -v`
Expected: new tests FAIL — `add_member() got an unexpected keyword argument 'start_date'`, `module ... has no attribute 'depart_member'`.

- [ ] **Step 3: Implement in `sprint_pulse/services/config_service.py`**

Add `from datetime import date` to the imports. Change `add_member`'s signature and member construction:

```python
def add_member(
    session: Session,
    name: str,
    *,
    is_excluded: bool = False,
    start_date: date | None = None,
) -> m.TeamMember:
    name = (name or "").strip()
    if not name:
        raise ValidationError("name is required", field="name")
    if session.exec(select(m.TeamMember).where(m.TeamMember.name == name)).first():
        raise ValidationError(f'"{name}" is already on the roster', field="name")
    # max(sort_order)+1, not count: a prior removal would otherwise collide.
    existing = list_members(session)
    next_order = (max((member.sort_order for member in existing), default=-1)) + 1
    member = m.TeamMember(
        name=name, is_excluded=is_excluded, sort_order=next_order, start_date=start_date
    )
    session.add(member)
    session.flush()
    return member
```

Add the two new mutators right after `toggle_excluded`:

```python
def depart_member(session: Session, member_id: int, end_date: date) -> m.TeamMember:
    """Mark a member as departed: set end_date, drop time off past it.

    History (time off up to and including end_date, aliases) is kept so past
    sprints keep rendering this member; use remove_member only for mistakes.
    """
    member = _get_member(session, member_id)
    if member.start_date is not None and end_date < member.start_date:
        raise ValidationError(
            f"departure ({end_date.isoformat()}) is before "
            f"{member.name}'s start date ({member.start_date.isoformat()})",
            field="end_date",
        )
    for row in session.exec(
        select(m.MemberDayOff).where(
            m.MemberDayOff.member_id == member_id, m.MemberDayOff.date > end_date
        )
    ).all():
        session.delete(row)
    member.end_date = end_date
    session.add(member)
    return member


def rejoin_member(session: Session, member_id: int) -> m.TeamMember:
    member = _get_member(session, member_id)
    if member.end_date is None:
        raise ValidationError(f"{member.name} has not departed", field="end_date")
    member.end_date = None
    session.add(member)
    return member
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_departed_members.py tests/test_services.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add sprint_pulse/services/config_service.py tests/test_departed_members.py
git commit -m "feat(services): depart/rejoin members, optional join date"
```

---

### Task 4: Time-off validation — dates must fall inside tenure

**Files:**
- Modify: `sprint_pulse/services/time_off_service.py:35-60` (`set_days`)
- Test: `tests/test_departed_members.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_departed_members.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_departed_members.py::test_set_days_rejects_dates_outside_tenure -v`
Expected: FAIL — no ValidationError raised.

- [ ] **Step 3: Implement in `sprint_pulse/services/time_off_service.py`**

Add `from sprint_pulse.config import in_tenure` to the imports. In `set_days`, keep the existing member fetch but bind it, and extend the per-date loop:

```python
def set_days(session: Session, member_id: int, dates: Iterable[date], type_: str, notes: str = "") -> None:
    """Upsert one MemberDayOff per date (replacing type/notes if present)."""
    from sprint_pulse.services import type_service

    member = _require_member(session, member_id)
    if type_ not in type_service.absence_type_keys(session):
        raise ValidationError(f'unknown absence type "{type_}"', field="type")
    dates = list(dates)
    if not dates:
        raise ValidationError("at least one day is required", field="days")
    tenure = (member.start_date, member.end_date)
    for d in dates:
        err = weekday_error(d)
        if err:
            raise ValidationError(err, field="days")
        if not in_tenure(tenure, d):
            raise ValidationError(
                f"{d.isoformat()} is outside {member.name}'s tenure on the team",
                field="days",
            )
```

(The upsert loop below stays exactly as it is.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_departed_members.py tests/test_time_off_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add sprint_pulse/services/time_off_service.py tests/test_departed_members.py
git commit -m "feat(timeoff): reject days outside a member's tenure"
```

---

### Task 5: Per-sprint Config with tenure-filtered roster + prorated capacity

**Files:**
- Modify: `sprint_pulse/services/sprint_service.py` (new `_sprint_config` + `build_sprint_configs`)
- Test: `tests/test_departed_members.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_departed_members.py`:

```python
from sprint_pulse.services import sprint_service as spsvc


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_departed_members.py -v`
Expected: FAIL — `module ... has no attribute 'build_sprint_configs'`.

- [ ] **Step 3: Implement in `sprint_pulse/services/sprint_service.py`**

Add to the imports at the top:

```python
import dataclasses

from sprint_pulse.config import Config, in_tenure, tenure_overlaps
from sprint_pulse.sprints import working_days
```

(`Config` is already imported; merge rather than duplicate. `working_days` joins the existing `from sprint_pulse.sprints import (...)` block.)

Add after `build_dashboard_data`:

```python
def _sprint_config(
    cfg: Config, members: list[m.TeamMember], start: date, end: date
) -> Config:
    """Per-sprint Config: tenure-filtered roster/excluded + prorated capacity.

    A member with no tenure dates contributes working_days_per_sprint exactly
    as before this feature; a member whose tenure covers every working day of
    the sprint contributes the same; a partial overlap contributes its
    in-tenure working-day count.
    """
    present = [
        mm for mm in members if tenure_overlaps((mm.start_date, mm.end_date), start, end)
    ]
    roster = [mm.name for mm in present]
    excluded = {mm.name for mm in present if mm.is_excluded}
    tenures = {
        mm.name: (mm.start_date, mm.end_date)
        for mm in present
        if mm.start_date is not None or mm.end_date is not None
    }
    days = working_days(start, end)
    capacity = 0
    for mm in present:
        if mm.is_excluded:
            continue
        tenure = tenures.get(mm.name)
        if tenure is None:
            capacity += cfg.working_days_per_sprint
            continue
        in_days = sum(1 for d in days if in_tenure(tenure, d))
        if in_days == len(days):  # covers the whole sprint -> classic contribution
            capacity += cfg.working_days_per_sprint
        else:
            capacity += min(in_days, cfg.working_days_per_sprint)
    return dataclasses.replace(
        cfg, roster=roster, excluded=excluded, tenures=tenures, capacity_override=capacity
    )


def build_sprint_configs(session: Session, cfg: Config | None = None) -> dict[str, Config]:
    """{sprint_id: per-sprint Config} for every sprint row (archived included)."""
    if cfg is None:
        cfg = config_service.build_config_from_db(session)
    members = config_service.list_members(session)
    return {
        row.id: _sprint_config(cfg, members, row.start, row.end)
        for row in session.exec(select(m.Sprint)).all()
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_departed_members.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add sprint_pulse/services/sprint_service.py tests/test_departed_members.py
git commit -m "feat(services): per-sprint configs with tenure roster + prorated capacity"
```

---

### Task 6: Renderer — out-of-tenure gray cells + per-sprint configs in the dashboard

**Files:**
- Modify: `sprint_pulse/render.py:120-124` (CSS), `:188-212` (`_render_cell`), `:410-432` (`render_full_html`)
- Modify: `sprint_pulse/web/routers/dashboard.py:18-24`
- Test: `tests/test_departed_members.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_departed_members.py`:

```python
from sprint_pulse.render import render_sprint
from sprint_pulse.sprints import Sprint
from sprint_pulse.types_defaults import DEFAULT_ABSENCE_TYPES, DEFAULT_EVENT_TYPES
from sprint_pulse.config import TypeDef

_METRICS = {"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}


def _render_cfg(**kw) -> Config:
    base = dict(
        working_days_per_sprint=10,
        jira=JiraConfig(site="x", board="1"),
        roster=["Alice Anderson", "Bob Brown"],
        excluded=set(),
        name_aliases={},
        event_types=tuple(TypeDef(**r) for r in DEFAULT_EVENT_TYPES),
        absence_types=tuple(TypeDef(**r) for r in DEFAULT_ABSENCE_TYPES),
    )
    base.update(kw)
    return Config(**base)


def test_out_of_tenure_days_render_inactive_cells():
    sprint = Sprint(
        id="2026-22", label="2026-22",
        start=date(2026, 5, 25), end=date(2026, 6, 7),
        events=(), time_off=(),
    )
    cfg = _render_cfg(
        tenures={"Bob Brown": (None, date(2026, 5, 27))},  # leaves Wed of week 1
        capacity_override=13,
    )
    html, _ = render_sprint(sprint, cfg, metrics=_METRICS, state="closed")
    assert html.count('class="inactive"') == 7  # 10 working days - 3 in tenure
    assert "Bob Brown" in html
    # availability uses the prorated capacity: 0 days out of 13
    assert "100.0%" in html


def test_no_tenures_renders_no_inactive_cells():
    sprint = Sprint(
        id="2026-22", label="2026-22",
        start=date(2026, 5, 25), end=date(2026, 6, 7),
        events=(), time_off=(),
    )
    html, _ = render_sprint(sprint, _render_cfg(), metrics=_METRICS, state="closed")
    assert 'class="inactive"' not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_departed_members.py -v`
Expected: the two new tests FAIL (no `inactive` cells rendered, availability computed from 20).

- [ ] **Step 3: Implement the renderer changes in `sprint_pulse/render.py`**

Add `in_tenure` to the config import:

```python
from sprint_pulse.config import Config, in_tenure
```

In the `CSS` string, directly after the `td.excluded { background: #e5e7eb; }` line, add:

```css
td.inactive { background: #f3f4f6; }
```

In `_render_cell`, add the tenure check as the FIRST statement of the function body:

```python
def _render_cell(
    person: str,
    d: date,
    by_person: dict,
    cfg: Config,
    abs_letter: dict,
    abs_title: dict,
) -> tuple[str, int]:
    if not in_tenure(cfg.tenures.get(person), d):
        return '<td class="inactive" title="Not on the team"></td>', 0
    if person in cfg.excluded:
        ...
```

(The rest of the function is unchanged.)

In `render_full_html`, accept and apply per-sprint configs:

```python
def render_full_html(
    sprints_with_data: list[tuple[Sprint, dict, str]],
    cfg: Config,
    cfg_by_sprint: dict[str, Config] | None = None,
) -> str:
    """sprints_with_data: list of (sprint, jira_metrics, jira_state).

    ``cfg_by_sprint`` supplies per-sprint Config copies (tenure-filtered roster,
    prorated capacity); sprints without an entry fall back to ``cfg``.
    """
```

and in its render loop change the `render_sprint` call:

```python
    for sprint, metrics, state in sprints_asc:
        sprint_cfg = (cfg_by_sprint or {}).get(sprint.id, cfg)
        html, dpo = render_sprint(sprint, sprint_cfg, metrics, state)
```

- [ ] **Step 4: Wire the dashboard router**

In `sprint_pulse/web/routers/dashboard.py`, inside `dashboard()`:

```python
    cfg = config_service.build_config_from_db(session)
    data = sprint_service.build_dashboard_data(session, cfg)
    if data:
        # Render whenever there are (active) sprints — even before a team exists;
        # the heatmap just has no member rows yet and availability shows n/a.
        cfg_by_sprint = sprint_service.build_sprint_configs(session, cfg)
        return HTMLResponse(
            inject_app_bar(
                render_full_html(data, cfg, cfg_by_sprint=cfg_by_sprint), active="/"
            )
        )
```

Note: the global `cfg` keeps ALL members (including departed) in its roster — `list_members` returns every row — which is exactly what the summary table needs so departed members' historical totals still appear.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_departed_members.py tests/test_render.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full suite (snapshot tests must not change)**

Run: `python3 -m pytest`
Expected: all PASS — a dateless roster produces byte-identical HTML, so snapshots hold.

- [ ] **Step 7: Commit**

```bash
git add sprint_pulse/render.py sprint_pulse/web/routers/dashboard.py tests/test_departed_members.py
git commit -m "feat(render): gray out-of-tenure cells, per-sprint configs on dashboard"
```

---

### Task 7: Routes — depart / rejoin / join-date on add

**Files:**
- Modify: `sprint_pulse/web/routers/members.py:19-68`
- Test: `tests/test_departed_members.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_departed_members.py` (same TestClient pattern as `tests/test_api.py`: `create_app(":memory:")` exposes its engine at `app.state.engine`):

```python
from fastapi.testclient import TestClient

from sprint_pulse.web.app import create_app


@pytest.fixture
def client_with_team():
    app = create_app(":memory:")
    with session_scope(app.state.engine) as s:
        cfgsvc.add_member(s, "Alice Anderson")  # id 1 on a fresh DB
    return TestClient(app)


def test_depart_and_rejoin_routes(client_with_team):
    resp = client_with_team.post("/members/1/depart", data={"end_date": "2026-05-29"})
    assert resp.status_code == 200
    assert "Former members" in resp.text
    resp = client_with_team.post("/members/1/rejoin")
    assert resp.status_code == 200
    assert "Former members" not in resp.text


def test_add_member_route_accepts_start_date(client_with_team):
    resp = client_with_team.post(
        "/members", data={"name": "New Hire", "start_date": "2026-06-01"}
    )
    assert resp.status_code == 200
    assert "New Hire" in resp.text
```

(The "Former members" assertions depend on Task 8's template — these two tests go RED now and GREEN after Task 8; that's expected, note it in the Task 7 commit message.)

- [ ] **Step 2: Implement in `sprint_pulse/web/routers/members.py`**

`date` is already imported. Update `_table` to pass today's date (the template's default departure date) and update both add/list contexts:

```python
def _table(request: Request, session: Session, error: str = "") -> HTMLResponse:
    members = config_service.list_members(session)
    return templates.TemplateResponse(
        request,
        "partials/_members_table.html",
        {"members": members, "error": error, "today": date.today().isoformat()},
    )


@router.get("/members", response_class=HTMLResponse)
def members_page(request: Request, session: Session = Depends(get_session)):
    members = config_service.list_members(session)
    return templates.TemplateResponse(
        request,
        "members.html",
        {"members": members, "active": "/members", "today": date.today().isoformat()},
    )
```

Extend `add_member` with the optional join date:

```python
@router.post("/members", response_class=HTMLResponse)
def add_member(
    request: Request,
    name: str = Form(...),
    is_excluded: bool = Form(False),
    start_date: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        try:
            joined = date.fromisoformat(start_date) if start_date else None
        except ValueError:
            raise ValidationError("invalid join date", field="start_date")
        config_service.add_member(session, name, is_excluded=is_excluded, start_date=joined)
    except ValidationError as e:
        session.rollback()
        return _table(request, session, error=e.display())
    return _table(request, session)
```

Add the two new endpoints after `delete`:

```python
@router.post("/members/{member_id}/depart", response_class=HTMLResponse)
def depart(
    request: Request,
    member_id: int,
    end_date: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        try:
            when = date.fromisoformat(end_date) if end_date else date.today()
        except ValueError:
            raise ValidationError("invalid departure date", field="end_date")
        config_service.depart_member(session, member_id, when)
    except ValidationError as e:
        session.rollback()
        return _table(request, session, error=e.display())
    return _table(request, session)


@router.post("/members/{member_id}/rejoin", response_class=HTMLResponse)
def rejoin(request: Request, member_id: int, session: Session = Depends(get_session)):
    try:
        config_service.rejoin_member(session, member_id)
    except ValidationError as e:
        session.rollback()
        return _table(request, session, error=e.display())
    return _table(request, session)
```

`ValidationError` is already imported in this module.

- [ ] **Step 3: Run the suite**

Run: `python3 -m pytest tests/test_departed_members.py -v`
Expected: route tests still FAIL only on the "Former members" text assertions (template lands in Task 8); everything else PASSES. The service-level depart/rejoin happens correctly (verify the 200s).

- [ ] **Step 4: Commit**

```bash
git add sprint_pulse/web/routers/members.py tests/test_departed_members.py
git commit -m "feat(web): depart/rejoin routes, optional join date on add (UI in next commit)"
```

---

### Task 8: Templates — Former members section, Departed/Rejoin actions, banners

**Files:**
- Modify: `sprint_pulse/web/templates/partials/_members_table.html`
- Modify: `sprint_pulse/web/templates/members.html:9-23`
- Modify: `sprint_pulse/web/templates/member_detail.html:6`

- [ ] **Step 1: Rewrite `partials/_members_table.html`**

Replace the whole file with:

```html
{% if error %}<p class="error">{{ error }}</p>{% endif %}
{% set active_members = members | rejectattr("end_date") | list %}
{% set former_members = members | selectattr("end_date") | list %}
<table class="grid">
  <thead>
    <tr><th>Name</th><th>Role</th><th></th></tr>
  </thead>
  <tbody>
    {% for member in active_members %}
    <tr>
      <td><a class="link" href="/members/{{ member.id }}">{{ member.name }}</a></td>
      <td>
        {% if member.is_excluded %}<span class="pill excluded">Excluded</span>
        {% else %}<span class="muted">Capacity</span>{% endif %}
        {% if member.start_date %}<span class="muted" style="font-size:12px"> · joined {{ member.start_date }}</span>{% endif %}
      </td>
      <td style="text-align:right; white-space:nowrap">
        <button class="secondary"
                hx-post="/members/{{ member.id }}/toggle"
                hx-target="#members-table" hx-swap="innerHTML">
          {% if member.is_excluded %}Include{% else %}Exclude{% endif %}
        </button>
        <form style="display:inline-flex; gap:4px; align-items:center; margin:0"
              hx-post="/members/{{ member.id }}/depart"
              hx-target="#members-table" hx-swap="innerHTML"
              hx-confirm="Mark {{ member.name }} as departed? They stay in past sprints; time off after the chosen date will be removed.">
          <input type="date" name="end_date" value="{{ today }}" style="width:auto">
          <button class="secondary">Departed</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
<p class="muted" style="margin-top:10px">
  {{ active_members | length }} members · {{ active_members | selectattr("is_excluded") | list | length }} excluded from capacity
</p>

{% if former_members %}
<h2 style="margin-top:24px">Former members</h2>
<p class="muted" style="font-size:13px">Still shown in the sprints they were part of; not counted after their departure date.</p>
<table class="grid">
  <thead>
    <tr><th>Name</th><th>Tenure</th><th></th></tr>
  </thead>
  <tbody>
    {% for member in former_members %}
    <tr>
      <td><a class="link" href="/members/{{ member.id }}">{{ member.name }}</a></td>
      <td><span class="muted">{% if member.start_date %}{{ member.start_date }} – {% else %}until {% endif %}{{ member.end_date }}</span></td>
      <td style="text-align:right; white-space:nowrap">
        <button class="secondary"
                hx-post="/members/{{ member.id }}/rejoin"
                hx-target="#members-table" hx-swap="innerHTML">
          Rejoin
        </button>
        <button class="danger"
                hx-post="/members/{{ member.id }}/delete"
                hx-target="#members-table" hx-swap="innerHTML"
                hx-confirm="Permanently remove {{ member.name }} and ALL their history (time off, past sprint rows)? Use only for entries created by mistake.">
          Remove
        </button>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endif %}
```

(Note the hard **Remove** now lives only in the Former section — departing first is the normal path, exactly as designed.)

- [ ] **Step 2: Add the join-date field in `members.html`**

In the add form's `.row` div, insert between the name field and the exclude checkbox:

```html
      <div style="flex:1">
        <label for="start_date">Joined on <span class="muted">(optional)</span></label>
        <input type="date" id="start_date" name="start_date">
      </div>
```

- [ ] **Step 3: Add the former-member banner in `member_detail.html`**

Directly after the `<h1>{{ member.name }}</h1>` line:

```html
{% if member.end_date %}
<p><span class="pill excluded">Former member — left {{ member.end_date }}</span></p>
{% endif %}
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest`
Expected: all PASS — including Task 7's two route tests that were waiting on the "Former members" markup.

- [ ] **Step 5: Commit**

```bash
git add sprint_pulse/web/templates/partials/_members_table.html sprint_pulse/web/templates/members.html sprint_pulse/web/templates/member_detail.html
git commit -m "feat(ui): Former members section, depart/rejoin actions, join-date field"
```

---

### Task 9: Docs + manual verification

**Files:**
- Modify: `CLAUDE.md` (Constraints section)
- Modify: `.claude/skills/maintain-time-off-report/SKILL.md` (Removing / archiving section)

- [ ] **Step 1: Update `CLAUDE.md`**

In "Constraints worth remembering", replace nothing — append one bullet:

```markdown
- Members have optional tenure dates (`start_date`/`end_date`). A sprint shows and
  counts only members whose tenure overlaps it, with capacity prorated for
  mid-sprint joins/leaves. "Departed" (Team page) preserves history; hard delete
  is only for mistaken entries.
```

- [ ] **Step 2: Update the skill**

In `.claude/skills/maintain-time-off-report/SKILL.md`, replace the bullet
"To stop counting someone, remove them on the Team page (their time-off entries are cleaned up too)." with:

```markdown
- When someone **leaves the team**, use **Departed** on the Team page (pick the
  last day; defaults to today). They keep their rows in past sprints; time off
  after the date is removed and they stop counting toward later capacity.
  **Rejoin** (Former members section) reverses it. **Remove** is destructive and
  only for entries created by mistake. New hires can get a **Joined on** date so
  they don't appear in older sprints.
```

- [ ] **Step 3: Manual smoke test**

```bash
make dev
```

In the browser (http://localhost:8765): add a member with a join date, mark another as Departed mid-sprint, confirm (a) the Former members section, (b) gray cells after their departure day on the dashboard, (c) availability % changed for that sprint only, (d) Rejoin restores them.

- [ ] **Step 4: Full suite + commit**

```bash
python3 -m pytest
git add CLAUDE.md .claude/skills/maintain-time-off-report/SKILL.md
git commit -m "docs: document member tenure / departed workflow"
```
