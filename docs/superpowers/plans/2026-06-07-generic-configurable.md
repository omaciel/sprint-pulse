# Generic & Configurable Sprint Pulse — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Sprint Pulse generic (no baked-in team/AAP identity), let users manage event & absence types (CRUD) with a seeded default set on a fixed Tableau-10 palette, and rename "orchestration" → "Excluded".

**Architecture:** Phased. (A) swap hard-coded `"Wisdom"`/`"AAP release"` defaults for generic ones. (B) rename the capacity-exclusion concept end-to-end (`is_excluded`). (C) introduce `EventType`/`AbsenceType` tables seeded from a shared defaults module, make the renderer generate per-type CSS/letters/legend from `Config`, add a `/types` CRUD page, and move validation DB-ward. (D) one-time migration of the operator's real DB.

**Tech Stack:** Python 3, FastAPI, SQLModel/SQLite, Jinja2/HTMX, pytest. No Alembic — schema evolves in `db/engine.py` (`create_all` + seed); the operator-DB column rename is a one-off scripted step (Part D).

**Spec:** `docs/superpowers/specs/2026-06-07-generic-configurable-design.md`

**Conventions:**
- Run a single test: `.venv/bin/python -m pytest tests/<file>::<test> -v` (use `.venv/bin/python`; `python` is not on PATH). Full suite: `.venv/bin/python -m pytest -q`.
- In-memory DB for tests: `get_engine(":memory:")` then `create_db_and_tables(engine)`; mutate inside `with session_scope(engine) as s:`.
- `ValidationError` is in `sprint_pulse.errors`; raise with `field=`. `e.display()` renders it for templates.
- Slug helper: `from sprint_pulse.sprints import slugify` (lowercases, NFKD-folds, collapses to `-`).
- TDD per task: failing test → verify red → implement → verify green → commit.

---

## File Structure

| File | Responsibility | Phase |
|---|---|---|
| `sprint_pulse/db/models.py` | `TeamMember.is_excluded`; new `EventType`/`AbsenceType` tables | B, C |
| `sprint_pulse/config.py` | `Config.excluded`; `Config.event_types`/`absence_types`; generic default | A, B, C |
| `sprint_pulse/types_defaults.py` (new) | `PALETTE`, `DEFAULT_EVENT_TYPES`, `DEFAULT_ABSENCE_TYPES`, key sets | C |
| `sprint_pulse/services/type_service.py` (new) | CRUD + `seed_default_types` for both type tables | C |
| `sprint_pulse/db/engine.py` | call `seed_default_types`; generic default literal | A, C |
| `sprint_pulse/services/config_service.py` | hydrate `excluded` + type lists; `toggle_excluded`; generic defaults | A, B, C |
| `sprint_pulse/services/time_off_service.py` | validate `type` against DB absence types | C |
| `sprint_pulse/services/sprint_service.py` | validate `kind` against DB event types; generic prefix default | A, C |
| `sprint_pulse/sprints.py` | event/absence validation vs default-key sets; YAML key | B, C |
| `sprint_pulse/render.py` | generic labels; data-driven CSS/letters/legend; `excluded` class | A, B, C |
| `sprint_pulse/migrate.py` | `excluded` key; generic default | A, B |
| `sprint_pulse/web/routers/types.py` (new) | `/types` page + mutation endpoints | C |
| `sprint_pulse/web/routers/{members,setup,config_page}.py` | `is_excluded` form field; generic defaults | A, B |
| `sprint_pulse/web/app.py` | register `types` router | C |
| `sprint_pulse/web/nav.py` | add Types nav link | C |
| `sprint_pulse/web/templates/*` | "Excluded" strings; `/types` templates; nav link | B, C |
| `tests/*`, `examples/*.yaml`, `tests/fixtures/*` | rename + generic sample data + new tests | A–C |
| `scripts/migrate_excluded.py` (new, one-off) | operator-DB column rename | D |

---

# PHASE A — De-personalize branding

## Task A1: Generic default team name

**Files:** `sprint_pulse/db/models.py`, `sprint_pulse/db/engine.py`, `sprint_pulse/config.py`, `sprint_pulse/services/config_service.py`, `sprint_pulse/services/jira_service.py`, `sprint_pulse/services/mock_jira.py`, `sprint_pulse/services/refresh.py`, `sprint_pulse/services/sprint_service.py`, `sprint_pulse/web/routers/config_page.py`, `sprint_pulse/web/routers/setup.py`, `sprint_pulse/web/templates/config.html`, `sprint_pulse/web/templates/setup/wizard.html` — Test: `tests/test_config.py` or `tests/test_services.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_services.py` (it has the `engine` fixture, `session_scope`, `config_service as cfgsvc`):

```python
def test_default_team_name_is_generic(engine):
    from sprint_pulse.services import config_service as cfgsvc
    with session_scope(engine) as s:
        settings = cfgsvc.get_settings(s)
        assert settings.team_name == "My Team"
```

- [ ] **Step 2: Verify it fails**

Run: `.venv/bin/python -m pytest tests/test_services.py::test_default_team_name_is_generic -v`
Expected: FAIL (default is "Wisdom").

- [ ] **Step 3: Replace every `"Wisdom"` *default* with `"My Team"`**

Read each file and replace the `"Wisdom"` literal with `"My Team"` at these locations (keep surrounding code identical):
- `db/models.py` — `team_name: str = "My Team"`
- `db/engine.py` — `_ADDED_COLUMNS["settings"]`: `("team_name", "VARCHAR DEFAULT 'My Team'")`
- `config.py` — dataclass default and the YAML fallback `raw.get("team_name") or "My Team"`
- `services/config_service.py` — hydration fallback `settings.team_name or "My Team"` and update fallback `(team_name or "").strip() or "My Team"`
- `services/jira_service.py` — `MockJiraClient(settings.team_name or "My Team")`
- `services/mock_jira.py` — the `__init__` default param
- `services/refresh.py` — `prefix = settings.team_name or "My Team"`
- `services/sprint_service.py` — `prefix = (... team_name or "My Team") + " "`
- `web/routers/config_page.py` — `team_name: str = Form("My Team")`
- `web/routers/setup.py` — `team_name: str = Form("My Team")`
- `web/templates/config.html` — placeholder text → `My Team`
- `web/templates/setup/wizard.html` — the value/help-text example → `My Team`

- [ ] **Step 4: Verify the test passes + full suite**

Run: `.venv/bin/python -m pytest tests/test_services.py::test_default_team_name_is_generic -v` → PASS
Run: `.venv/bin/python -m pytest -q` — note any failures that assert on "Wisdom" (some tests/snapshots may; fix those that are about the *default* — tests that explicitly set team_name="Wisdom"/"Galaxy" are fine and stay). For any test asserting the default was "Wisdom", update to "My Team".

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(branding): default team name is 'My Team'"
```

## Task A2: Replace hard-coded "AAP release" with "Releases"

**Files:** `sprint_pulse/render.py:163,242`, `tests/test_render.py`, `tests/fixtures/valid/sprint-full.yaml`, `tests/snapshots/test_render/test_render_sprint_snapshot/sprint-minimal.html` — Test: `tests/test_render.py`

- [ ] **Step 1: Update the failing test**

In `tests/test_render.py`, find any assertion referencing `"AAP release"` or `"AAP 2.7 GA release"`. Change the event title in the test fixture (the `Event(... title="AAP 2.7 GA release")`) to `"2.7 GA release"`, and update the corresponding assertion to expect `"2.7 GA release — Apr 22"`. Add an assertion that the release row label is now `"Releases"`:

```python
def test_render_sprint_release_row_labelled_releases(cfg: Config) -> None:
    sprint = _minimal_sprint()
    html, _ = render_sprint(sprint, cfg, metrics={"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}, state="future")
    assert ">Releases<" in html
    assert "AAP" not in html
```

- [ ] **Step 2: Verify it fails**

Run: `.venv/bin/python -m pytest tests/test_render.py::test_render_sprint_release_row_labelled_releases -v`
Expected: FAIL (row says "AAP release").

- [ ] **Step 3: Edit render.py**

- `render.py:242` — change `'<tr class="release-row"><td class="name">AAP release</td>'` to `'<tr class="release-row"><td class="name">Releases</td>'`.
- `render.py:163` (the LEGEND constant) — change `<span class="group-label">AAP release</span>` to `<span class="group-label">Releases</span>`.

(Note: the LEGEND constant is replaced wholesale in Phase C; for now just swap this label so Phase A is self-consistent.)

- [ ] **Step 4: Update sample data**

- `tests/fixtures/valid/sprint-full.yaml:7` — change `title: AAP 2.7 GA release` to `title: 2.7 GA release`.
- Update the snapshot: run `.venv/bin/python -m pytest tests/test_render.py --snapshot-update`, then READ `tests/snapshots/test_render/test_render_sprint_snapshot/sprint-minimal.html` to confirm the only diffs are `AAP release`→`Releases` and the title text. Report the diff.

- [ ] **Step 5: Verify suite green**

Run: `.venv/bin/python -m pytest -q` → all pass. Grep to confirm no stray "AAP" in shipped code/data: `grep -rn "AAP" sprint_pulse/ examples/ tests/ | grep -v docs` — should be empty (docs may mention it).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(branding): release row/legend labelled 'Releases', drop AAP"
```

---

# PHASE B — Rename "orchestration" → "Excluded"

## Task B1: DB model + Config dataclass

**Files:** `sprint_pulse/db/models.py:50`, `sprint_pulse/config.py:44,50-51,77-80` — Test: `tests/test_config.py`

- [ ] **Step 1: Write/adjust the failing test**

In `tests/test_config.py`, the assertion `assert cfg.orchestration == {...}` must become `cfg.excluded`. Update those (and `tests/test_services.py`, `tests/test_sprints.py`, `tests/test_review_fixes.py` fixtures that pass `orchestration=`). For TDD, first update ONE: in `tests/test_config.py` change `cfg.orchestration` → `cfg.excluded` and the YAML error test message `'orchestration member "Carol" not in roster'` → `'excluded member "Carol" not in roster'`.

- [ ] **Step 2: Verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL (`Config` has no `excluded`; message differs).

- [ ] **Step 3: Edit the model + dataclass**

- `db/models.py` — `TeamMember.is_orchestration: bool = False` → `is_excluded: bool = False`.
- `config.py` — field `orchestration: set[str]` → `excluded: set[str]`; the `effective` property body `[... if m not in self.orchestration]` → `self.excluded`; the YAML-load validation that checks membership and its error message `f'... orchestration member "{name}" not in roster'` → `excluded`. Also the YAML key read: change `raw.get("orchestration")` → `raw.get("excluded")`.

- [ ] **Step 4: Verify + update remaining dataclass consumers**

Run: `.venv/bin/python -m pytest tests/test_config.py -v` → PASS.
Then update the fixtures/asserts in `tests/test_services.py`, `tests/test_sprints.py`, `tests/test_review_fixes.py` that still pass `orchestration=` or assert `cfg.orchestration` → `excluded`. Run those files; fix until green. (Renderer/service still reference `.orchestration` — they're updated in B2/B3; the suite will have failures there until then, so scope this step's green check to test_config.py + test_sprints.py construction. If cross-file failures block, proceed to B2/B3 before the full-suite check.)

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor(excluded): rename Config.excluded + TeamMember.is_excluded"
```

## Task B2: Services + migrate + YAML

**Files:** `sprint_pulse/services/config_service.py:40,117,145-149`, `sprint_pulse/migrate.py:67,105`, `examples/config.yaml:20-22`, `tests/fixtures/**/config*.yaml`, `tests/test_migration.py`, `tests/test_demo.py` — Test: `tests/test_services.py`, `tests/test_migration.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_services.py`:

```python
def test_toggle_excluded_flips_flag(engine):
    from sprint_pulse.services import config_service as cfgsvc
    with session_scope(engine) as s:
        m1 = cfgsvc.add_member(s, "Alice Anderson")
        assert m1.is_excluded is False
        cfgsvc.toggle_excluded(s, m1.id)
    with session_scope(engine) as s:
        member = next(mm for mm in cfgsvc.list_members(s) if mm.name == "Alice Anderson")
        assert member.is_excluded is True
```

- [ ] **Step 2: Verify it fails**

Run: `.venv/bin/python -m pytest tests/test_services.py::test_toggle_excluded_flips_flag -v`
Expected: FAIL (`toggle_excluded` undefined).

- [ ] **Step 3: Edit services + migrate + YAML**

- `services/config_service.py`: build set `excluded = {m.name for m in members if m.is_excluded}`; rename `toggle_orchestration` → `toggle_excluded` (flip `member.is_excluded`); `add_member(..., is_orchestration=False)` → `is_excluded=False` and store on the model.
- `migrate.py`: `is_excluded=name in cfg.excluded`; counts dict key `"orchestration"` → `"excluded"`.
- `examples/config.yaml`: rename the `orchestration:` key → `excluded:`.
- `tests/fixtures/**` any `config*.yaml` with `orchestration:` → `excluded:` (grep: `grep -rln "orchestration" tests/fixtures examples`).
- `tests/test_migration.py` + `tests/test_demo.py`: counts `["orchestration"]` → `["excluded"]`; the test name `test_orchestration_flags_persist` → `test_excluded_flags_persist`; query `m.TeamMember.is_orchestration` → `is_excluded`.

- [ ] **Step 4: Verify**

Run: `.venv/bin/python -m pytest tests/test_services.py tests/test_migration.py tests/test_demo.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor(excluded): services, migrate, and YAML key use 'excluded'"
```

## Task B3: Renderer + routers + templates

**Files:** `sprint_pulse/render.py` (`external` class → `excluded`, `cfg.orchestration` → `cfg.excluded`, legend text), `sprint_pulse/web/routers/members.py:39,43,53`, `sprint_pulse/web/routers/setup.py:112`, templates `members.html`, `setup/team.html`, `member_detail.html`, `partials/_members_table.html`, `partials/_setup_members.html` — Test: `tests/test_render.py`, `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_render.py`, the tests `test_render_sprint_orchestration_marked_external` / `test_render_sprint_days_out_excludes_orchestration` use `cfg.orchestration`. Add/replace with:

```python
def test_render_sprint_excluded_marked_and_uncounted(cfg: Config) -> None:
    # cfg fixture marks Grace Hughes & Hassan Ibrahim as excluded
    sprint = _minimal_sprint()
    html, days_out = render_sprint(sprint, cfg, metrics={"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}, state="future")
    assert 'class="excluded"' in html or 'excluded-row' in html
    assert "Orchestration" not in html
```

(Also update the `cfg` fixture in test_render.py if it constructs Config with `orchestration=` → `excluded=`.)

- [ ] **Step 2: Verify it fails**

Run: `.venv/bin/python -m pytest tests/test_render.py -v`
Expected: FAIL (`Config(orchestration=...)` invalid or "Orchestration" still present).

- [ ] **Step 3: Edit renderer**

In `render.py`:
- CSS: `.swatch.external` → `.swatch.excluded`; `td.external` → `td.excluded`; `tr.external-row td.name` → `tr.excluded-row td.name`. (These move into generated CSS in Phase C, but rename now for consistency.)
- `_render_cell`: `if person in cfg.orchestration:` → `cfg.excluded`; the no-entry return `'<td class="external" title="On Orchestration"></td>'` → `'<td class="excluded" title="Excluded from capacity"></td>'`.
- `render_sprint`: `if person not in cfg.orchestration` / `in cfg.orchestration` → `cfg.excluded`.
- `render_summary`: `p not in cfg.orchestration` / `in cfg.orchestration` → `cfg.excluded`; the row class `external-row` → `excluded-row` (search `tr_class = ' class="external-row"'`).
- LEGEND constant: `On Orchestration (not counted)` → `Excluded (not counted)` and swatch class `external` → `excluded`.

- [ ] **Step 4: Edit routers + templates**

- `web/routers/members.py`: form field `is_orchestration: bool = Form(False)` → `is_excluded`; `add_member(..., is_orchestration=...)` → `is_excluded=...`; `toggle_orchestration` call → `toggle_excluded`; docstring wording.
- `web/routers/setup.py`: form field `is_orchestration` → `is_excluded`; pass to `add_member`.
- Templates — replace user-facing strings and form fields:
  - `members.html`: subtitle "Members on Orchestration are always shown gray and excluded from capacity." → "Excluded members are shown gray and don't count toward capacity."; checkbox `name="is_orchestration"` + label "Orchestration" → `name="is_excluded"` + "Exclude from capacity".
  - `partials/_members_table.html`: pill `is_orchestration` → `is_excluded`, text "Orchestration" → "Excluded"; toggle button "Make orchestration"/"Make capacity" → "Exclude"/"Include"; summary `selectattr("is_orchestration")` → `is_excluded`, "on orchestration (excluded from capacity)" → "excluded from capacity".
  - `member_detail.html`: heading "Orchestration" → "Excluded from capacity"; checkbox `is_orchestration` → `is_excluded`.
  - `setup/team.html`: subtitle and checkbox `is_orchestration`/"Orchestration" → `is_excluded`/"Exclude from capacity".
  - `partials/_setup_members.html`: pill `is_orchestration` → `is_excluded`, "Orchestration" → "Excluded".

- [ ] **Step 5: Verify suite green + snapshot**

Run: `.venv/bin/python -m pytest -q`. Update the render snapshot if the `external`→`excluded` class/legend text changed it: `.venv/bin/python -m pytest tests/test_render.py --snapshot-update`, then READ the snapshot to confirm only class-name/label diffs. Grep no leftovers: `grep -rin "orchestration" sprint_pulse/ examples/ tests/ | grep -v docs` → empty.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "refactor(excluded): renderer, routers, templates use 'Excluded'"
```

---

# PHASE C — CRUD event & absence types

## Task C1: Defaults module (palette + seed sets)

**Files:** Create `sprint_pulse/types_defaults.py` — Test: `tests/test_types.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_types.py`:

```python
from sprint_pulse.types_defaults import (
    PALETTE, DEFAULT_EVENT_TYPES, DEFAULT_ABSENCE_TYPES,
    DEFAULT_EVENT_KEYS, DEFAULT_ABSENCE_KEYS,
)


def test_defaults_use_palette_colors():
    for t in DEFAULT_EVENT_TYPES + DEFAULT_ABSENCE_TYPES:
        assert t["color"] in PALETTE, f'{t["key"]} color {t["color"]} not in palette'


def test_default_keys_match_legacy_values():
    assert DEFAULT_EVENT_KEYS == {"tags", "gono", "ga", "freeze", "test"}
    assert DEFAULT_ABSENCE_KEYS == {"pto", "holiday", "company", "partial", "tentative"}


def test_defaults_have_required_fields():
    for t in DEFAULT_EVENT_TYPES + DEFAULT_ABSENCE_TYPES:
        assert set(t) == {"key", "label", "abbreviation", "color", "sort_order"}
        assert 1 <= len(t["abbreviation"]) <= 2
```

- [ ] **Step 2: Verify it fails**

Run: `.venv/bin/python -m pytest tests/test_types.py -v` → FAIL (module missing).

- [ ] **Step 3: Create the module**

`sprint_pulse/types_defaults.py`:

```python
"""Fixed color palette + the default event/absence type sets.

Single source of truth shared by the DB seed (services/type_service.seed_default_types),
the renderer, and the YAML loader's validation. Default keys/letters match the
pre-CRUD hard-coded vocabulary so existing Event.kind / MemberDayOff.type values
keep working; colors are the Tableau 10 categorical palette.
"""
from __future__ import annotations

PALETTE = [
    # Tableau 10 (one per default type)
    "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
    # extras for custom types
    "#A0CBE8", "#FFBE7D", "#8CD17D", "#D4A6C8",
]

DEFAULT_EVENT_TYPES = [
    {"key": "tags",   "label": "Git tags due",   "abbreviation": "T", "color": "#4E79A7", "sort_order": 0},
    {"key": "gono",   "label": "Go/No-Go",       "abbreviation": "G", "color": "#F28E2B", "sort_order": 1},
    {"key": "ga",     "label": "Target release", "abbreviation": "R", "color": "#59A14F", "sort_order": 2},
    {"key": "freeze", "label": "Release freeze",  "abbreviation": "F", "color": "#BAB0AC", "sort_order": 3},
    {"key": "test",   "label": "Testathon",      "abbreviation": "X", "color": "#B07AA1", "sort_order": 4},
]

DEFAULT_ABSENCE_TYPES = [
    {"key": "pto",       "label": "PTO",                     "abbreviation": "P", "color": "#E15759", "sort_order": 0},
    {"key": "holiday",   "label": "Regional / National holiday", "abbreviation": "H", "color": "#76B7B2", "sort_order": 1},
    {"key": "company",   "label": "Company holiday",         "abbreviation": "C", "color": "#9C755F", "sort_order": 2},
    {"key": "partial",   "label": "Partial availability",    "abbreviation": "~", "color": "#EDC948", "sort_order": 3},
    {"key": "tentative", "label": "Tentative",               "abbreviation": "?", "color": "#FF9DA7", "sort_order": 4},
]

DEFAULT_EVENT_KEYS = {t["key"] for t in DEFAULT_EVENT_TYPES}
DEFAULT_ABSENCE_KEYS = {t["key"] for t in DEFAULT_ABSENCE_TYPES}
```

(Labels above mirror the current LEGEND text — confirm against `render.py`'s LEGEND and tweak if they differ.)

- [ ] **Step 4: Verify it passes**

Run: `.venv/bin/python -m pytest tests/test_types.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add sprint_pulse/types_defaults.py tests/test_types.py
git commit -m "feat(types): defaults module with Tableau palette + seed sets"
```

## Task C2: DB tables + seed

**Files:** `sprint_pulse/db/models.py`, `sprint_pulse/services/type_service.py` (new), `sprint_pulse/db/engine.py` — Test: `tests/test_types.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_types.py`:

```python
def test_seed_creates_defaults_idempotently():
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc
    engine = get_engine(":memory:")
    create_db_and_tables(engine)  # should auto-seed
    with session_scope(engine) as s:
        assert {t.key for t in tsvc.list_event_types(s)} == DEFAULT_EVENT_KEYS
        assert {t.key for t in tsvc.list_absence_types(s)} == DEFAULT_ABSENCE_KEYS
    # re-running seed adds no duplicates
    with session_scope(engine) as s:
        tsvc.seed_default_types(s)
    with session_scope(engine) as s:
        assert len(tsvc.list_event_types(s)) == len(DEFAULT_EVENT_TYPES)


def test_seed_skips_when_user_deleted_a_default():
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        tsvc.delete_event_type(s, "test")  # unused -> allowed
    with session_scope(engine) as s:
        tsvc.seed_default_types(s)  # must NOT re-add 'test'
    with session_scope(engine) as s:
        assert "test" not in {t.key for t in tsvc.list_event_types(s)}
```

- [ ] **Step 2: Verify it fails**

Run: `.venv/bin/python -m pytest tests/test_types.py -v` → FAIL.

- [ ] **Step 3: Add the models**

In `db/models.py` add (mirroring the existing plain-column style — no Relationships):

```python
class EventType(SQLModel, table=True):
    key: str = Field(primary_key=True)            # slug, == Event.kind
    label: str = ""
    abbreviation: str = ""                         # 1-2 chars shown in cells
    color: str = ""                                # hex from PALETTE
    sort_order: int = 0


class AbsenceType(SQLModel, table=True):
    key: str = Field(primary_key=True)            # slug, == MemberDayOff.type
    label: str = ""
    abbreviation: str = ""
    color: str = ""
    sort_order: int = 0
```

- [ ] **Step 4: Create `services/type_service.py`**

```python
"""CRUD + seeding for EventType / AbsenceType. Block deletion while a type is
still referenced by Event.kind / MemberDayOff.type."""
from __future__ import annotations

from sqlmodel import Session, select

from sprint_pulse.db import models as m
from sprint_pulse.errors import ValidationError
from sprint_pulse.sprints import slugify
from sprint_pulse.types_defaults import (
    PALETTE, DEFAULT_EVENT_TYPES, DEFAULT_ABSENCE_TYPES,
)


def list_event_types(session: Session) -> list[m.EventType]:
    return list(session.exec(select(m.EventType).order_by(m.EventType.sort_order, m.EventType.key)).all())


def list_absence_types(session: Session) -> list[m.AbsenceType]:
    return list(session.exec(select(m.AbsenceType).order_by(m.AbsenceType.sort_order, m.AbsenceType.key)).all())


def event_type_keys(session: Session) -> set[str]:
    return {t.key for t in list_event_types(session)}


def absence_type_keys(session: Session) -> set[str]:
    return {t.key for t in list_absence_types(session)}


def _validate(label: str, abbreviation: str, color: str) -> tuple[str, str, str, str]:
    label = (label or "").strip()
    if not label:
        raise ValidationError("type label is required", field="label")
    key = slugify(label)
    if not key:
        raise ValidationError(f'label "{label}" has no usable letters/numbers', field="label")
    abbreviation = (abbreviation or "").strip()
    if not (1 <= len(abbreviation) <= 2):
        raise ValidationError("abbreviation must be 1-2 characters", field="abbreviation")
    if color not in PALETTE:
        raise ValidationError("color must be chosen from the palette", field="color")
    return key, label, abbreviation, color


def _next_order(rows) -> int:
    return (max((r.sort_order for r in rows), default=-1)) + 1


def create_event_type(session, label, abbreviation, color):
    key, label, abbreviation, color = _validate(label, abbreviation, color)
    if session.get(m.EventType, key):
        raise ValidationError(f'an event type "{key}" already exists', field="label")
    row = m.EventType(key=key, label=label, abbreviation=abbreviation, color=color,
                      sort_order=_next_order(list_event_types(session)))
    session.add(row); session.flush(); return row


def create_absence_type(session, label, abbreviation, color):
    key, label, abbreviation, color = _validate(label, abbreviation, color)
    if session.get(m.AbsenceType, key):
        raise ValidationError(f'an absence type "{key}" already exists', field="label")
    row = m.AbsenceType(key=key, label=label, abbreviation=abbreviation, color=color,
                        sort_order=_next_order(list_absence_types(session)))
    session.add(row); session.flush(); return row


def update_event_type(session, key, label, abbreviation, color):
    row = session.get(m.EventType, key)
    if row is None:
        raise ValidationError(f'no event type "{key}"')
    _, row.label, row.abbreviation, row.color = _validate(label, abbreviation, color)
    session.add(row); return row


def update_absence_type(session, key, label, abbreviation, color):
    row = session.get(m.AbsenceType, key)
    if row is None:
        raise ValidationError(f'no absence type "{key}"')
    _, row.label, row.abbreviation, row.color = _validate(label, abbreviation, color)
    session.add(row); return row


def delete_event_type(session, key):
    n = len(session.exec(select(m.Event).where(m.Event.kind == key)).all())
    if n:
        raise ValidationError(f'cannot delete: {n} event(s) still use "{key}"', field="key")
    row = session.get(m.EventType, key)
    if row is not None:
        session.delete(row)


def delete_absence_type(session, key):
    n = len(session.exec(select(m.MemberDayOff).where(m.MemberDayOff.type == key)).all())
    if n:
        raise ValidationError(f'cannot delete: {n} absence(s) still use "{key}"', field="key")
    row = session.get(m.AbsenceType, key)
    if row is not None:
        session.delete(row)


def seed_default_types(session: Session) -> None:
    """Seed defaults only into an EMPTY table (so a user-deleted default stays gone)."""
    if not session.exec(select(m.EventType)).first():
        for t in DEFAULT_EVENT_TYPES:
            session.add(m.EventType(**t))
    if not session.exec(select(m.AbsenceType)).first():
        for t in DEFAULT_ABSENCE_TYPES:
            session.add(m.AbsenceType(**t))
```

- [ ] **Step 5: Wire seed into `create_db_and_tables`**

In `db/engine.py`, after `_backfill_sprint_labels(engine)` (and the legacy timeoff migration), seed types. Add inside `create_db_and_tables`:

```python
    from sprint_pulse.services.type_service import seed_default_types
    with Session(engine) as s:
        seed_default_types(s)
        s.commit()
```

(Import `Session` from sqlmodel at top if not already imported — it is used elsewhere; verify.)

- [ ] **Step 6: Verify**

Run: `.venv/bin/python -m pytest tests/test_types.py -v` → PASS. Then `.venv/bin/python -m pytest -q` → no regressions.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat(types): EventType/AbsenceType tables, CRUD service, auto-seed"
```

## Task C3: Validate kind/type against the DB

**Files:** `sprint_pulse/services/sprint_service.py` (`add_event`), `sprint_pulse/services/time_off_service.py` (`set_days`), `sprint_pulse/sprints.py` (YAML validators vs default keys) — Test: `tests/test_types.py`, `tests/test_services.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_types.py`:

```python
def test_add_event_accepts_custom_type_rejects_unknown():
    from datetime import date
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc, sprint_service as spsvc
    from sprint_pulse.errors import ValidationError
    import pytest
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        spsvc.create_sprint(s, "2026-16", date(2026, 4, 16), date(2026, 4, 29))
        tsvc.create_event_type(s, "Webinar", "W", "#A0CBE8")
        spsvc.add_event(s, "2026-16", date(2026, 4, 17), "webinar", "Launch webinar")
        with pytest.raises(ValidationError):
            spsvc.add_event(s, "2026-16", date(2026, 4, 20), "nope", "bad")
```

- [ ] **Step 2: Verify it fails**

Run: `.venv/bin/python -m pytest tests/test_types.py::test_add_event_accepts_custom_type_rejects_unknown -v`
Expected: FAIL (`add_event` validates against the old `EVENT_KINDS` tuple, rejecting "webinar").

- [ ] **Step 3: Edit validators**

- `services/sprint_service.py` `add_event`: replace the `event_kind_error(kind)` check with a DB check:
  ```python
  from sprint_pulse.services import type_service
  if kind not in type_service.event_type_keys(session):
      raise ValidationError(
          f'unknown event type "{kind}"', field="kind"
      )
  ```
  (Remove the now-unused `event_kind_error` import in this module if no longer referenced.)
- `services/time_off_service.py` `set_days`: replace the `VALID_TYPES` membership check with:
  ```python
  from sprint_pulse.services import type_service
  if type_ not in type_service.absence_type_keys(session):
      raise ValidationError(f'unknown absence type "{type_}"', field="type")
  ```
  Keep `TYPE_PRIORITY` (still used by the legacy import path) — do NOT remove it.
- `sprints.py` (pure YAML loader, no DB): repoint `event_kind_error` and `infer_type`/validation to the DEFAULT key sets from `types_defaults` so YAML import validates against the default vocabulary. Specifically: `from sprint_pulse.types_defaults import DEFAULT_EVENT_KEYS` and change `event_kind_error` to check `kind not in DEFAULT_EVENT_KEYS`; keep `EVENT_KINDS` as an alias `EVENT_KINDS = tuple(sorted(DEFAULT_EVENT_KEYS))` if other code imports it (grep `EVENT_KINDS`). `infer_type` keeps returning default keys (unchanged).
- **Time-off calendar dropdown must list DB absence types** (so a custom type is selectable when entering time off). In `web/routers/members.py`, the context currently passes `"types": time_off_service.VALID_TYPES` (~line 101). Change it to pass the DB absence types, e.g. `"absence_types": type_service.list_absence_types(session)` (import `type_service`). Update the calendar template(s) that render the type selector (`partials/_calendar.html` and/or `partials/_calendar_edit.html`, and any `_calendar` context builder) to iterate the absence-type rows — `<option value="{{ t.key }}">{{ t.label }}</option>` — instead of the old `types` tuple. Read those templates to find the selector and the context key name; keep the POST field name (`type`) unchanged so `set_days` still receives a key. If `VALID_TYPES` has no remaining consumers after this, you may leave the constant (harmless) but do not rely on it.

- [ ] **Step 4: Verify**

Run: `.venv/bin/python -m pytest tests/test_types.py tests/test_services.py tests/test_sprints.py -v` → PASS. Then full suite `.venv/bin/python -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(types): validate event kind / absence type against the DB"
```

## Task C4: Config hydration + data-driven renderer

**Files:** `sprint_pulse/config.py` (add type fields), `sprint_pulse/services/config_service.py` (`build_config_from_db`), `sprint_pulse/render.py` (generate CSS/letters/legend) — Test: `tests/test_render.py`, `tests/test_types.py`

- [ ] **Step 1: Write the failing test**

**CRITICAL fixture update:** after this task the renderer reads cell letters/labels
from `cfg.absence_types`/`cfg.event_types`. The existing `cfg` fixture in
`tests/test_render.py` builds `Config(...)` directly WITHOUT type lists, so those
default to `()` and letters fall back to "?" — breaking existing letter/color
assertions. Update the `cfg` fixture to populate both lists with `TypeDef` objects
built from the defaults:

```python
# at top of tests/test_render.py
from sprint_pulse.config import Config, JiraConfig, TypeDef
from sprint_pulse.types_defaults import DEFAULT_EVENT_TYPES, DEFAULT_ABSENCE_TYPES

def _default_typedefs(rows):
    return tuple(TypeDef(**r) for r in rows)
```

and in the `cfg` fixture pass:
`event_types=_default_typedefs(DEFAULT_EVENT_TYPES), absence_types=_default_typedefs(DEFAULT_ABSENCE_TYPES)`.

Then add the meaningful full-html test below (the per-sprint render only emits
letters/cells; CSS + legend are produced by `render_full_html`):

Add to `tests/test_types.py` a full-html generation test:

```python
def test_full_html_css_is_data_driven():
    from datetime import date
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc, config_service as cfgsvc, sprint_service as spsvc
    from sprint_pulse.services.sprint_service import build_dashboard_data
    from sprint_pulse.render import render_full_html
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        cfgsvc.add_member(s, "Alice Anderson")
        spsvc.create_sprint(s, "2026-16", date(2026, 4, 16), date(2026, 4, 29))
        tsvc.create_absence_type(s, "Jury Duty", "J", "#A0CBE8")
        cfg = cfgsvc.build_config_from_db(s)
        data = build_dashboard_data(s, cfg)
    html = render_full_html(data, cfg)
    assert "#A0CBE8" in html          # custom type color injected into CSS
    assert "Jury Duty" in html        # custom type in legend
```

- [ ] **Step 2: Verify it fails**

Run: `.venv/bin/python -m pytest tests/test_types.py::test_full_html_css_is_data_driven -v`
Expected: FAIL (Config has no type fields; renderer CSS is static).

- [ ] **Step 3: Add type fields to Config + hydrate**

- `config.py`: add a small frozen record and two fields:
  ```python
  @dataclass(frozen=True)
  class TypeDef:
      key: str
      label: str
      abbreviation: str
      color: str
      sort_order: int = 0
  ```
  Add to `Config`: `event_types: tuple[TypeDef, ...] = ()` and `absence_types: tuple[TypeDef, ...] = ()` (defaults `()` so existing test constructors still work).
- `services/config_service.py` `build_config_from_db`: populate them from `type_service.list_event_types/list_absence_types`, mapping each row to `TypeDef(key, label, abbreviation, color, sort_order)`.

- [ ] **Step 4: Make the renderer data-driven**

In `render.py`:
- Add helpers:
  ```python
  def _text_on(bg_hex: str) -> str:
      """Readable black/white text for a hex background (per-channel luminance)."""
      h = bg_hex.lstrip("#")
      r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
      luma = (0.299 * r + 0.587 * g + 0.114 * b)
      return "#111827" if luma > 150 else "#ffffff"

  def _type_css(absence_types, event_types) -> str:
      rules = [".swatch.excluded { background: #e5e7eb; }",
               "td.excluded { background: #e5e7eb; }",
               "tr.excluded-row td.name { color: var(--muted); font-style: italic; }"]
      for t in absence_types:
          fg = _text_on(t.color)
          rules.append(f".swatch.{t.key} {{ background: {t.color}; }}")
          rules.append(f"td.{t.key} {{ background: {t.color}; color: {fg}; }}")
      for t in event_types:
          rules.append(f".swatch.{t.key} {{ background: {t.color}; }}")
          rules.append(f"td.release.{t.key} {{ background: {t.color}; color: {_text_on(t.color)}; }}")
      return "\n".join(rules)

  def _legend_html(absence_types, event_types) -> str:
      def items(types):
          return "\n".join(
              f'<div class="legend-item"><div class="swatch {t.key}"></div> '
              f'{esc(t.abbreviation)} — {esc(t.label)}</div>'
              for t in sorted(types, key=lambda t: t.sort_order)
          )
      return (
          '<div class="legend">'
          '<div class="legend-group"><span class="group-label">Time off</span>'
          + items(absence_types)
          + '<div class="legend-item"><div class="swatch excluded"></div> Excluded (not counted)</div>'
          + '</div><div class="legend-divider"></div>'
          '<div class="legend-group"><span class="group-label">Releases</span>'
          + items(event_types)
          + '</div></div>'
      )
  ```
- Remove the hard-coded per-type CSS lines from the `CSS` constant (the `--pto`… vars, `.swatch.pto/holiday/.../tags/...`, `td.pto/...`, `td.release.ga/...`, `td.external`, `tr.external-row`). Keep all non-type CSS. Remove the static `LEGEND` constant and the `TYPE_LETTERS`/`TYPE_TITLES`/`KIND_LETTERS` module dicts.
- In `_render_cell` and `render_sprint`'s release-row loop, build letter/label/color lookups from `cfg.absence_types`/`cfg.event_types`:
  ```python
  abbr = {t.key: t.abbreviation for t in cfg.absence_types}
  title = {t.key: t.label for t in cfg.absence_types}
  ```
  Use `abbr.get(cls, "?")` and `title.get(cls, cls)` (fallback for a stray key). For events: `ev_abbr = {t.key: t.abbreviation for t in cfg.event_types}`; `letter = ev_abbr.get(ev.kind, "•")`. Pass these maps into `_render_cell` (add params) or build inside it from `cfg` once per sprint — prefer building once in `render_sprint` and passing down to avoid rebuilding per cell.
- In `render_full_html`: build the dynamic style + legend and inject:
  ```python
  type_css = _type_css(cfg.absence_types, cfg.event_types)
  legend = _legend_html(cfg.absence_types, cfg.event_types)
  ```
  Change `<style>{CSS}</style>` → `<style>{CSS}\n{type_css}</style>` and replace the `{LEGEND}` interpolation with `{legend}`.

- [ ] **Step 5: Verify + snapshot**

Run: `.venv/bin/python -m pytest tests/test_types.py tests/test_render.py -v`. Update the snapshot (`--snapshot-update`) and READ it: confirm the rendered structure is intact and type cells now carry Tableau colors + correct letters; report the diff (colors changed, legend regenerated, `Releases` label). Then full suite `.venv/bin/python -m pytest -q`.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(types): data-driven renderer (generated CSS, letters, legend)"
```

## Task C5: `/types` CRUD page

**Files:** Create `sprint_pulse/web/routers/types.py`, create `sprint_pulse/web/templates/types.html` (+ a partial if needed), `sprint_pulse/web/app.py` (register router), `sprint_pulse/web/nav.py` + base template (nav link) — Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api.py`:

```python
def test_types_page_create_and_block_delete_in_use():
    from datetime import date
    from fastapi.testclient import TestClient
    from sprint_pulse.web.app import create_app
    from sprint_pulse.db.engine import session_scope
    client = TestClient(create_app(":memory:"))
    # page renders
    assert client.get("/types").status_code == 200
    # create an absence type
    r = client.post("/types/absence", data={"label": "Jury Duty", "abbreviation": "J", "color": "#A0CBE8"}, follow_redirects=False)
    assert r.status_code == 303
    # default 'pto' with no usage can be deleted; one in use cannot — simulate via a 200 + error
    # (use an event type still referenced)
    page = client.get("/types")
    assert "Jury Duty" in page.text
```

(Adapt to test_api.py's app/client conventions — read the file first.)

- [ ] **Step 2: Verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_types_page_create_and_block_delete_in_use -v` → FAIL (no `/types`).

- [ ] **Step 3: Create the router**

`sprint_pulse/web/routers/types.py`:

```python
"""Manage event & absence types (CRUD) on a dedicated /types page."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from sprint_pulse.errors import ValidationError
from sprint_pulse.services import type_service
from sprint_pulse.types_defaults import PALETTE
from sprint_pulse.web.deps import get_session, templates

router = APIRouter()


def _ctx(session: Session, *, error: str = "") -> dict:
    return {
        "active": "/types",
        "event_types": type_service.list_event_types(session),
        "absence_types": type_service.list_absence_types(session),
        "palette": PALETTE,
        "error": error,
    }


@router.get("/types", response_class=HTMLResponse)
def types_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "types.html", _ctx(session))


@router.post("/types/event", response_class=HTMLResponse)
def create_event(request: Request, label: str = Form(...), abbreviation: str = Form(...),
                 color: str = Form(...), session: Session = Depends(get_session)):
    try:
        type_service.create_event_type(session, label, abbreviation, color)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(request, "types.html", _ctx(session, error=e.display()))
    return RedirectResponse("/types", status_code=303)


@router.post("/types/absence", response_class=HTMLResponse)
def create_absence(request: Request, label: str = Form(...), abbreviation: str = Form(...),
                   color: str = Form(...), session: Session = Depends(get_session)):
    try:
        type_service.create_absence_type(session, label, abbreviation, color)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(request, "types.html", _ctx(session, error=e.display()))
    return RedirectResponse("/types", status_code=303)


@router.post("/types/event/{key}/update", response_class=HTMLResponse)
def update_event(request: Request, key: str, label: str = Form(...), abbreviation: str = Form(...),
                 color: str = Form(...), session: Session = Depends(get_session)):
    try:
        type_service.update_event_type(session, key, label, abbreviation, color)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(request, "types.html", _ctx(session, error=e.display()))
    return RedirectResponse("/types", status_code=303)


@router.post("/types/absence/{key}/update", response_class=HTMLResponse)
def update_absence(request: Request, key: str, label: str = Form(...), abbreviation: str = Form(...),
                   color: str = Form(...), session: Session = Depends(get_session)):
    try:
        type_service.update_absence_type(session, key, label, abbreviation, color)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(request, "types.html", _ctx(session, error=e.display()))
    return RedirectResponse("/types", status_code=303)


@router.post("/types/event/{key}/delete", response_class=HTMLResponse)
def delete_event(request: Request, key: str, session: Session = Depends(get_session)):
    try:
        type_service.delete_event_type(session, key)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(request, "types.html", _ctx(session, error=e.display()))
    return RedirectResponse("/types", status_code=303)


@router.post("/types/absence/{key}/delete", response_class=HTMLResponse)
def delete_absence(request: Request, key: str, session: Session = Depends(get_session)):
    try:
        type_service.delete_absence_type(session, key)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(request, "types.html", _ctx(session, error=e.display()))
    return RedirectResponse("/types", status_code=303)
```

- [ ] **Step 4: Create the template**

`sprint_pulse/web/templates/types.html` — extend `base.html` like the other pages (read `members.html` for the exact block structure: `{% extends %}`, the `{% block content %}`, error banner pattern). Render two sections, each listing types as rows with a swatch (`style="background:{{ t.color }}"`), label, abbreviation, an inline edit form (label/abbreviation text inputs, a `<select name="color">` of `{{ palette }}` options, submit to `/types/<kind>/{{ t.key }}/update`), and a delete form (submit to `.../delete`). Add a "new type" form per section posting to `/types/event` and `/types/absence`. Show `{{ error }}` if present. Keep markup consistent with `members.html`.

- [ ] **Step 5: Register router + nav link**

- `web/app.py`: import and `app.include_router(types.router)` alongside the others (read the file to match the include pattern).
- `web/nav.py` + base template: add a "Types" link to `/types` in the main nav (read `nav.py` to see how Sprints/Team/Config links are defined and mirror it; mark active when `active == "/types"`).

- [ ] **Step 6: Verify**

Run: `.venv/bin/python -m pytest tests/test_api.py -v` → PASS. Full suite `.venv/bin/python -m pytest -q`.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat(types): /types CRUD page + nav link"
```

## Task C6: Programmatic smoke + full green

**Files:** none (verification) — Test: full suite

- [ ] **Step 1: Full suite**

Run: `.venv/bin/python -m pytest -q` → all pass. If any snapshot still differs, inspect and update as in earlier tasks (report diffs).

- [ ] **Step 2: Smoke (offline)**

```bash
SPRINT_PULSE_DEMO=1 .venv/bin/python -c "
from fastapi.testclient import TestClient
from sprint_pulse.web.app import create_app
c = TestClient(create_app(':memory:'))
print('types page', c.get('/types').status_code)
r = c.post('/types/absence', data={'label':'Jury Duty','abbreviation':'J','color':'#A0CBE8'}, follow_redirects=False)
print('create absence', r.status_code)
from datetime import date
c.post('/sprints', data={'label':'June 2026','start':'2026-06-01','end':'2026-06-12'}, follow_redirects=False)
print('home', c.get('/').status_code)
"
```
Confirm: types page 200, create 303, home 200. Report output.

- [ ] **Step 3: Commit (if snapshots changed)**

```bash
git add -A && git commit -m "test: reconcile snapshots for data-driven types"
```

---

# PHASE D — Operator DB migration (one-time)

## Task D1: Migrate the operator's live database

**Files:** Create `scripts/migrate_excluded.py` (one-off helper) — no test (operates on the live DB)

- [ ] **Step 1: Write the helper**

`scripts/migrate_excluded.py`:

```python
"""One-time: rename teammember.is_orchestration -> is_excluded on the live DB,
back it up first, then create+seed the new type tables. Idempotent."""
from __future__ import annotations

import shutil
from sqlalchemy import text
from sprint_pulse.db.engine import default_db_path, get_engine, create_db_and_tables


def main() -> None:
    path = default_db_path()
    if not path.exists():
        print(f"No DB at {path}; nothing to migrate (a fresh DB will be created on first run).")
        return
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    print(f"Backed up {path} -> {backup}")

    engine = get_engine(path)
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(teammember)")}
        if "is_orchestration" in cols and "is_excluded" not in cols:
            conn.exec_driver_sql("ALTER TABLE teammember RENAME COLUMN is_orchestration TO is_excluded")
            print("Renamed is_orchestration -> is_excluded")
        elif "is_excluded" in cols:
            print("Column already renamed; skipping.")
        else:
            print("WARNING: teammember has neither column; check schema.")

    # Create + seed the new EventType/AbsenceType tables (idempotent).
    create_db_and_tables(engine)
    print("Ensured + seeded type tables. Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run awareness + run**

Confirm the live DB path first:
```bash
.venv/bin/python -c "from sprint_pulse.db.engine import default_db_path; print(default_db_path())"
```
Then run the migration:
```bash
.venv/bin/python scripts/migrate_excluded.py
```
Expected output: backup path, "Renamed is_orchestration -> is_excluded", "Ensured + seeded type tables. Done."

- [ ] **Step 3: Verify the live DB**

```bash
.venv/bin/python -c "
from sprint_pulse.db.engine import default_db_path, get_engine
e = get_engine(default_db_path())
with e.begin() as c:
    print('teammember cols:', {r[1] for r in c.exec_driver_sql('PRAGMA table_info(teammember)')})
    print('event types:', [r[0] for r in c.exec_driver_sql('SELECT key FROM eventtype')])
    print('absence types:', [r[0] for r in c.exec_driver_sql('SELECT key FROM absencetype')])
"
```
Confirm `is_excluded` present (no `is_orchestration`) and both type tables seeded.

- [ ] **Step 4: Boot smoke against the live DB**

```bash
.venv/bin/python -c "
from fastapi.testclient import TestClient
from sprint_pulse.web.app import create_app
c = TestClient(create_app())  # default live DB path
print('home', c.get('/').status_code, 'types', c.get('/types').status_code)
"
```
Confirm both 200 and report. If the app needs the VPN/Jira for `/`, the status should still be 200 (dashboard renders from cache).

- [ ] **Step 5: Commit the helper**

```bash
git add scripts/migrate_excluded.py
git commit -m "chore(migrate): one-off operator-DB is_excluded rename + type seed"
```

---

## Self-Review notes (author)

- **Spec coverage:** Part A → A1 (team name), A2 (AAP). Part B → B1 (model+dataclass), B2 (services/migrate/YAML), B3 (renderer/routers/templates). Part C → C1 (defaults), C2 (tables+seed), C3 (DB validation), C4 (hydration+renderer), C5 (/types page), C6 (smoke). Part D → D1 (operator DB). Tableau palette + contrast → C1/C4. Block-delete-while-in-use → C2/C5. Generic default preserved-existing-value → A1 (default only). Dedicated /types page → C5.
- **Cross-task consistency:** type record shape is `{key,label,abbreviation,color,sort_order}` everywhere (defaults dict, `TypeDef`, model columns, service). Validation is one `_validate` helper. Renderer uses `cfg.event_types`/`cfg.absence_types` (TypeDef tuples) and the type `key` as CSS class. `excluded` replaces `orchestration`/`external` consistently.
- **Known-deferred test churn:** snapshots are updated within the task that changes rendering (A2, B3, C4) — always inspect the diff before `--snapshot-update`.
- **Things the implementer must read before writing:** `tests/test_render.py` `cfg` fixture (extend with type lists), `test_api.py` client conventions, `members.html`/`base.html`/`nav.py` patterns for C5, and the exact current LEGEND labels for C1.
