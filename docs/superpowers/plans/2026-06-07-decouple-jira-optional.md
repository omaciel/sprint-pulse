# Optional Jira & Decoupled Sprint Identity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let sprints carry a free-form display **label** (e.g. `"June 2026"`) that is separate from a URL/JS-safe **slug** key, make Jira metrics an optional convenience (implicit name-match + explicit override, silent skip, no error on zero matches), and stop hardcoding the team-name/Jira prefix into sprint display.

**Architecture:** `m.Sprint.id` stays the primary key but becomes a pure slug, auto-derived (lowercased, hyphenated) from a new `label` column. The frozen `Sprint` dataclass gains `label`; the renderer uses `label` for visible text and `id` for DOM keys. Refresh resolves each sprint's Jira id via `jira_sprint_id` first, then a `"{team} {label}"` name match, skipping silently otherwise. YAML `id:` becomes the label; the slug is derived.

**Tech Stack:** Python 3, FastAPI, SQLModel/SQLAlchemy, SQLite, Jinja2/HTMX, pytest. No Alembic (schema evolves via `db/engine.py` `_ADDED_COLUMNS` + `_ensure_columns`).

**Spec:** `docs/superpowers/specs/2026-06-07-decouple-jira-optional-design.md`

**Conventions:**
- Run the whole suite with `make test` (alias for `python -m pytest -v`). Run a single test with `python -m pytest tests/<file>::<test> -v`.
- In-memory DB for tests: `get_engine(":memory:")` then `create_db_and_tables(engine)`; mutate inside `with session_scope(engine) as s:`.
- `ValidationError` lives in `sprint_pulse.errors`; service validators raise it with `field=`.
- Commit after each task (TDD: failing test → implement → green → commit).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `sprint_pulse/db/models.py` | `Sprint.label` column | modify |
| `sprint_pulse/db/engine.py` | add+backfill `label` column | modify |
| `sprint_pulse/sprints.py` | `Sprint` dataclass `label`; drop `name` property | modify |
| `sprint_pulse/services/sprint_service.py` | `slugify_label`, `create_sprint(label)`, hydrate `label` | modify |
| `sprint_pulse/services/refresh.py` | resolve via id-then-label, silent skip, ok-on-zero | modify |
| `sprint_pulse/render.py` | `sprint_display` (label), summary labels, DOM uses slug | modify |
| `sprint_pulse/migrate.py` | YAML import sets `label`, derives slug | modify |
| `sprint_pulse/web/routers/sprints.py` | form takes `label`, redirect to derived slug | modify |
| `sprint_pulse/web/templates/sprints.html` | label field + label display | modify |
| `sprint_pulse/web/templates/sprint_detail.html` | show label | modify |
| `tests/test_services.py` | label/slug behavior | modify |
| `tests/test_review_fixes.py` | accept spaces; refresh ok-on-zero | modify |
| `tests/test_render.py` | label header, no "Wisdom" prefix | modify |
| `tests/test_sprints.py` | drop filename-mismatch test; label loader | modify |
| `tests/test_sprint_import.py` | "forty two" now imports as `forty-two` | modify |
| `tests/test_scheduler.py` | name-match still works (unchanged behavior) | verify |

---

## Task 1: Add `label` column to the Sprint model + migration backfill

**Files:**
- Modify: `sprint_pulse/db/models.py:60-69`
- Modify: `sprint_pulse/db/engine.py:93-96` and `:148-157`
- Test: `tests/test_migration.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_migration.py` (top imports already include `pytest`; add what's missing):

```python
def test_label_column_backfills_from_id():
    """An existing sprint row with an empty label is backfilled label = id
    when create_db_and_tables runs again (idempotent upgrade path)."""
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.db import models as m
    from datetime import date

    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    # Simulate a pre-label row: insert with an empty label directly.
    with session_scope(engine) as s:
        s.add(m.Sprint(id="2026-16", start=date(2026, 4, 16), end=date(2026, 4, 29), label=""))
    # Re-run schema setup; backfill should populate the empty label.
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        assert s.get(m.Sprint, "2026-16").label == "2026-16"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_migration.py::test_label_column_backfills_from_id -v`
Expected: FAIL — `TypeError`/`AttributeError` on unknown `label` (column/field does not exist yet).

- [ ] **Step 3: Add the model column**

In `sprint_pulse/db/models.py`, inside `class Sprint`, add `label` right after `id` (so the human label sits next to the slug key):

```python
class Sprint(SQLModel, table=True):
    # URL/JS-safe slug primary key (e.g. "june-2026"), auto-derived from `label`.
    id: str = Field(primary_key=True)
    # Free-form display label (e.g. "June 2026"). Backfilled to `id` on upgrade.
    label: str = ""
    start: date
    end: date
```

(Leave the rest of the class — `archived`, `jira_sprint_id`, cached metrics — unchanged.)

- [ ] **Step 4: Add the column migration + backfill in engine.py**

In `sprint_pulse/db/engine.py`, add `label` to `_ADDED_COLUMNS["sprint"]`:

```python
_ADDED_COLUMNS = {
    "settings": [("team_name", "VARCHAR DEFAULT 'Wisdom'")],
    "sprint": [
        ("archived", "BOOLEAN DEFAULT 0"),
        ("jira_sprint_id", "INTEGER"),
        ("label", "VARCHAR DEFAULT ''"),
    ],
}
```

Add a backfill helper after `_ensure_columns` (the `ALTER ... ADD COLUMN` only sets the literal default; it cannot copy from another column):

```python
def _backfill_sprint_labels(engine: Engine) -> None:
    """Populate Sprint.label from the id for rows created before label existed.
    Idempotent: once labels are set this UPDATE matches nothing."""
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE sprint SET label = id WHERE label IS NULL OR label = ''"
        )
```

Call it from `create_db_and_tables` after `_ensure_columns`:

```python
def create_db_and_tables(engine: Engine) -> None:
    with engine.connect() as conn:
        pre_existing = {row[0] for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    SQLModel.metadata.create_all(engine)
    _ensure_columns(engine)
    _backfill_sprint_labels(engine)
    _migrate_legacy_timeoff(engine, pre_existing=pre_existing)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_migration.py::test_label_column_backfills_from_id -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sprint_pulse/db/models.py sprint_pulse/db/engine.py tests/test_migration.py
git commit -m "feat(db): add Sprint.label column with id backfill"
```

---

## Task 2: Slugify labels + accept free-form labels in create_sprint

**Files:**
- Modify: `sprint_pulse/services/sprint_service.py:105-132` (and add `slugify_label`)
- Test: `tests/test_services.py`, `tests/test_review_fixes.py:61-71`, `tests/test_sprint_import.py:65-78`

**Note:** `create_sprint`'s first value is now a **label**, not a raw id. The parameter is renamed `label`. Existing positional callers like `create_sprint(s, "2026-16", ...)` still work — `"2026-16"` is both a valid label and slugifies to itself. A new dedicated `slugify_label` is added rather than reusing `_slugify`, because `_slugify` (used by import suggestions) must stay case-preserving (`test_sprint_import.py:54` expects `"Sprint-Forty-Two"`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_services.py` (it already imports `sprint_service as spsvc`, `session_scope`, `engine` fixture, `date`, `ValidationError`, `m`; add any missing import):

```python
def test_create_sprint_accepts_free_form_label(engine):
    from sprint_pulse.services import sprint_service as spsvc
    with session_scope(engine) as s:
        row = spsvc.create_sprint(s, "June 2026", date(2026, 6, 1), date(2026, 6, 12))
        assert row.id == "june-2026"
        assert row.label == "June 2026"
        assert s.get(m.Sprint, "june-2026") is not None


def test_create_sprint_rejects_label_that_slugifies_empty(engine):
    from sprint_pulse.services import sprint_service as spsvc
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            spsvc.create_sprint(s, "!!!", date(2026, 6, 1), date(2026, 6, 12))


def test_create_sprint_rejects_duplicate_slug(engine):
    from sprint_pulse.services import sprint_service as spsvc
    with session_scope(engine) as s:
        spsvc.create_sprint(s, "June 2026", date(2026, 6, 1), date(2026, 6, 12))
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            spsvc.create_sprint(s, "june 2026", date(2026, 6, 15), date(2026, 6, 26))
```

(If `pytest` is not yet imported in `test_services.py`, add `import pytest` at the top.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_services.py::test_create_sprint_accepts_free_form_label tests/test_services.py::test_create_sprint_rejects_label_that_slugifies_empty tests/test_services.py::test_create_sprint_rejects_duplicate_slug -v`
Expected: FAIL — the first asserts `row.id == "june-2026"` but current code stores the raw string (and the regex rejects the space).

- [ ] **Step 3: Add `slugify_label` and rewrite `create_sprint`**

In `sprint_pulse/services/sprint_service.py`, add a module-level helper near `_SPRINT_ID_RE` (line ~105):

```python
def slugify_label(label: str) -> str:
    """URL/JS-safe slug from a free-form label: 'June 2026' -> 'june-2026'.
    Lowercased; runs of non-[A-Za-z0-9._-] collapse to a single hyphen."""
    return re.sub(r"[^a-z0-9._-]+", "-", label.strip().lower()).strip("-")
```

Replace `create_sprint` (lines 108-132) with:

```python
def create_sprint(session: Session, label: str, start: date, end: date) -> m.Sprint:
    label = (label or "").strip()
    if not label:
        raise ValidationError("sprint label is required", field="label")
    slug = slugify_label(label)
    if not slug or not _SPRINT_ID_RE.match(slug):
        raise ValidationError(
            f'sprint label "{label}" has no usable letters/numbers for an id',
            field="label",
        )
    if end < start:
        raise ValidationError(
            f"end ({end.isoformat()}) is before start ({start.isoformat()})", field="end"
        )
    if session.get(m.Sprint, slug):
        raise ValidationError(
            f'a sprint with id "{slug}" already exists (label "{label}")', field="label"
        )
    if (end - start).days + 1 != 14:
        warnings.warn(
            f"sprint {slug}: length is {(end - start).days + 1} days (expected 14)",
            stacklevel=2,
        )
    sprint = m.Sprint(id=slug, label=label, start=start, end=end)
    session.add(sprint)
    session.flush()
    return sprint
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python -m pytest tests/test_services.py::test_create_sprint_accepts_free_form_label tests/test_services.py::test_create_sprint_rejects_label_that_slugifies_empty tests/test_services.py::test_create_sprint_rejects_duplicate_slug -v`
Expected: PASS.

- [ ] **Step 5: Update the existing tests that encoded the old "reject spaces" behavior**

In `tests/test_review_fixes.py`, replace `test_create_sprint_rejects_unsafe_id` (lines 61-71) with a test of the new slugifying behavior:

```python
def test_create_sprint_slugifies_unsafe_labels():
    """Labels need not be URL-safe; the service derives a safe slug id."""
    from sprint_pulse.db.engine import create_db_and_tables
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        row = spsvc.create_sprint(s, "Q1 sprint", date(2026, 4, 16), date(2026, 4, 29))
        assert row.id == "q1-sprint"
        assert row.label == "Q1 sprint"
    with session_scope(engine) as s:
        row = spsvc.create_sprint(s, "a/b", date(2026, 5, 14), date(2026, 5, 27))
        assert row.id == "a-b"
```

In `tests/test_sprint_import.py`, update `test_import_jira_sprints` (around lines 65-80): the chosen value `"forty two"` is now a valid label that imports as slug `"forty-two"` (it is no longer skipped). Read the current assertions and change them to:

```python
        result = spsvc.import_jira_sprints(
            s, [(2, "2026-20"), (3, "2026-28"), (5, "forty two")]
        )
    # 2026-28 (jira id 3) still skipped: it has no start/end (not importable).
    # "forty two" now imports as the slug "forty-two".
    assert set(result["skipped"]) == {"2026-28"}
    with session_scope(eng) as s:
        row = s.get(m.Sprint, "2026-20")
        assert row.jira_sprint_id == 2
        assert s.get(m.Sprint, "forty-two") is not None
```

(Adjust the variable names — `eng`/`s` — to match the surrounding test; read it first. The key changes: drop `"forty two"` from the expected `skipped` set and assert the `forty-two` row exists.)

- [ ] **Step 6: Run the affected files to verify green**

Run: `python -m pytest tests/test_services.py tests/test_review_fixes.py::test_create_sprint_slugifies_unsafe_labels tests/test_sprint_import.py -v`
Expected: PASS. (If `test_import_jira_sprints` still fails, re-read its real body and align the assertions with the new behavior described above.)

- [ ] **Step 7: Commit**

```bash
git add sprint_pulse/services/sprint_service.py tests/test_services.py tests/test_review_fixes.py tests/test_sprint_import.py
git commit -m "feat(sprints): accept free-form labels, derive slug id"
```

---

## Task 3: Hydrate `label` into the dataclass and render it

**Files:**
- Modify: `sprint_pulse/sprints.py:44-54` (dataclass + drop `name` property)
- Modify: `sprint_pulse/services/sprint_service.py:53-64` (`_load` hydration)
- Modify: `sprint_pulse/render.py:21-23, 329, 343-389, 405-451`
- Test: `tests/test_render.py:28-52`

- [ ] **Step 1: Write/adjust the failing renderer test**

In `tests/test_render.py`, update `_minimal_sprint` to carry a label and rewrite the header assertion. Replace lines 28-52 region:

```python
def _minimal_sprint() -> Sprint:
    return Sprint(
        id="2026-16",
        label="June 2026",
        start=date(2026, 4, 16),
        end=date(2026, 4, 29),
        events=(
            Event(date=date(2026, 4, 17), kind="gono", title="Go/No-Go deadline 4PM EST"),
            Event(date=date(2026, 4, 22), kind="ga", title="AAP 2.7 GA release"),
        ),
        time_off=(
            TimeOffEntry(
                associate="Alice Anderson",
                days=(date(2026, 4, 24),),
                notes="PTO",
                type="pto",
            ),
        ),
    )


def test_render_sprint_includes_label_and_dates(cfg: Config) -> None:
    sprint = _minimal_sprint()
    html, _ = render_sprint(sprint, cfg, metrics={"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}, state="future")
    assert "June 2026" in html        # the label shows
    assert "Wisdom 2026-16" not in html  # no team/Jira prefix anymore
    assert "Apr 16" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_render.py::test_render_sprint_includes_label_and_dates -v`
Expected: FAIL — `Sprint.__init__` has no `label` (dataclass not updated), or header still renders `"Wisdom 2026-16"`.

- [ ] **Step 3: Add `label` to the dataclass and drop the `name` property**

In `sprint_pulse/sprints.py`, update the frozen dataclass (lines 44-54). Add `label` with a default and remove the `name` property (it is unused — grep confirms no consumer):

```python
@dataclass(frozen=True)
class Sprint:
    id: str
    start: date
    end: date
    events: tuple[Event, ...]
    time_off: tuple[TimeOffEntry, ...]
    label: str = ""
```

(`label` is last with a default so the existing positional constructors keep working. Delete the `name` property and its `@property` line entirely.)

- [ ] **Step 4: Hydrate `label` in the service**

In `sprint_pulse/services/sprint_service.py`, in `_load` (the `sprints.append(Sprint(...))` near line 62-64), pass the label from the row:

```python
        sprints.append(
            Sprint(
                id=row.id,
                label=row.label or row.id,
                start=row.start,
                end=row.end,
                events=events,
                time_off=time_off,
            )
        )
```

- [ ] **Step 5: Update the renderer to use label for display, slug for DOM**

In `sprint_pulse/render.py`:

Replace `team_display` (lines 21-23) with a label-based display helper:

```python
def sprint_display(sprint: Sprint) -> str:
    """The sprint's display name — the free-form label (falls back to the id)."""
    return sprint.label or sprint.id
```

Update the two call sites that referenced `team_display(cfg, sprint)`:
- Line ~329: `<h2>{esc(sprint_display(sprint))}</h2>`
- Line ~447: `<span class="nav-name">{esc(sprint_display(sprint))}</span>`

(Remove the now-unused `cfg` argument at these sites; `cfg.team_name` still titles the page elsewhere — leave those untouched.)

Change `render_summary` so its column headers show labels while order/data stay keyed by slug. Update its signature and the header line:

```python
def render_summary(
    cfg: Config,
    per_sprint_days_out: list[dict[str, int]],
    sprint_labels: list[str],
) -> str:
```

and replace the `head_cells` line (was `for sid in sprint_ids`):

```python
    head_cells = "".join(f"<th>{esc(label)}</th>" for label in sprint_labels)
```

(Also rename the now-unused `sprint_totals = [0] * len(sprint_ids)` to `len(sprint_labels)`.)

In `render_full_html`, the `data-sprint` attributes, `sprint_html_by_id`, `days_out_by_sprint`, and `default_sid` all keep using `sprint.id` (the slug — these are DOM/JS keys). Only the summary call changes to pass labels:

```python
    summary_html = render_summary(
        cfg,
        [days_out_by_sprint[s.id] for s, _, _ in sprints_asc],
        [s.label or s.id for s, _, _ in sprints_asc],
    ).replace(
```

- [ ] **Step 6: Run the renderer test + full render file**

Run: `python -m pytest tests/test_render.py -v`
Expected: PASS. (Snapshot tests, if any reference the old "Wisdom <id>" header, are addressed in Task 7's full-suite pass — note any snapshot diffs here.)

- [ ] **Step 7: Commit**

```bash
git add sprint_pulse/sprints.py sprint_pulse/services/sprint_service.py sprint_pulse/render.py tests/test_render.py
git commit -m "feat(render): show sprint label, keep slug as DOM key"
```

---

## Task 4: Refresh — resolve by id then label, silent skip, ok on zero

**Files:**
- Modify: `sprint_pulse/services/refresh.py:47-89`
- Test: `tests/test_review_fixes.py:114-136`, `tests/test_scheduler.py` (verify)

- [ ] **Step 1: Update the failing/old refresh tests to the new contract**

In `tests/test_review_fixes.py`:

Keep `test_refresh_uses_configured_prefix` as-is — name-match still works, so it should still pass (verify in Step 5).

Rewrite `test_refresh_zero_match_reports_error` (lines 129-136) to assert the new ok-on-zero behavior, and rename it:

```python
def test_refresh_zero_match_is_ok_not_error(seeded_engine, monkeypatch):
    from sprint_pulse.services import refresh
    # Default prefix "Wisdom" but board returns names that match nothing.
    monkeypatch.setattr(jira_service, "make_client", lambda s: _FakeClient(["WIS 2026-16"]))
    with session_scope(seeded_engine) as s:
        result = refresh.refresh_all(s)
    assert result["status"] == "ok"
    assert result["updated"] == 0
    assert "matching" in result["log"].lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_review_fixes.py::test_refresh_zero_match_is_ok_not_error -v`
Expected: FAIL — current code returns `status == "error"` when nothing matches.

- [ ] **Step 3: Update the matching + status logic in refresh.py**

In `sprint_pulse/services/refresh.py`, the per-row resolution (lines 47-72) already does id-first then name-fallback; change the fallback key from `row.id` to `row.label or row.id`:

```python
        info = None
        if row.jira_sprint_id is not None:
            info = by_jira_id.get(row.jira_sprint_id)
        if info is None:
            info = jira_sprints.get(f"{prefix} {row.label or row.id}")
        if not info:
            continue
        matched += 1
```

Replace the status block (lines 74-90) so zero matches is `ok`, not error:

```python
    settings.last_run = now
    if rows and matched == 0:
        settings.last_status = "ok"
        settings.last_log = "No matching Jira sprints — nothing to update."
    elif metric_failures:
        settings.last_status = "error"
        settings.last_log = (
            f"Updated {updated}/{len(rows)} sprints; "
            f"{metric_failures} metric fetch(es) failed (stale numbers kept)."
        )
    else:
        settings.last_status = "ok"
        settings.last_log = f"Updated {updated}/{len(rows)} sprints."
    session.add(settings)
    return {"status": settings.last_status, "updated": updated, "log": settings.last_log}
```

(The "Jira not configured", `JiraUnavailable`, and metric-failure paths above are unchanged — they remain errors.)

- [ ] **Step 4: Run the rewritten test**

Run: `python -m pytest tests/test_review_fixes.py::test_refresh_zero_match_is_ok_not_error -v`
Expected: PASS.

- [ ] **Step 5: Verify the unchanged-behavior refresh tests still pass**

Run: `python -m pytest tests/test_scheduler.py tests/test_review_fixes.py::test_refresh_uses_configured_prefix -v`
Expected: PASS — `test_run_now_updates_cache` (`updated == 2` via name match), `test_run_now_without_jira_sets_error`, `test_run_now_unreachable_mentions_vpn`, and `test_refresh_uses_configured_prefix` all still hold (label == id for YAML rows, so the name key is unchanged).

- [ ] **Step 6: Commit**

```bash
git add sprint_pulse/services/refresh.py tests/test_review_fixes.py
git commit -m "feat(refresh): match by label, skip silently, ok on zero matches"
```

---

## Task 5: YAML import — `id:` becomes the label, derive the slug

**Files:**
- Modify: `sprint_pulse/migrate.py:83-92`
- Modify: `sprint_pulse/sprints.py:213-237` (drop filename↔id check, dedupe on slug)
- Test: `tests/test_sprints.py:167-182`, `tests/test_migration.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_migration.py` a test that a YAML sprint whose `id` contains a space imports with a derived slug and the label preserved. Create a tmp YAML so the test is self-contained:

```python
def test_yaml_import_derives_slug_from_label(tmp_path):
    """YAML `id:` is treated as the label; the slug is derived."""
    from sprint_pulse.db.engine import get_engine, session_scope
    from sprint_pulse.db import models as m
    from sprint_pulse.migrate import import_yaml
    import textwrap

    cfg_yaml = tmp_path / "config.yaml"
    cfg_yaml.write_text(textwrap.dedent("""\
        working_days_per_sprint: 10
        team: Wisdom
        jira: {site: x, board: "1"}
        associates: [Alice Anderson]
        orchestration: []
    """))
    sprints_dir = tmp_path / "sprints"
    sprints_dir.mkdir()
    (sprints_dir / "june.yaml").write_text(textwrap.dedent("""\
        id: June 2026
        start: 2026-06-01
        end: 2026-06-12
        events: []
        time_off: []
    """))

    engine = get_engine(":memory:")
    import_yaml(engine, cfg_yaml, sprints_dir)
    with session_scope(engine) as s:
        row = s.get(m.Sprint, "june-2026")
        assert row is not None
        assert row.label == "June 2026"
```

**Before writing this test, read `examples/config.yaml` / `tests/fixtures/valid/config.yaml`** to confirm the exact config key names (`team` vs `team_name`, `associates` vs `roster`, etc.) and mirror them — `load_config` is strict. Adjust the `cfg_yaml` body to match.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_migration.py::test_yaml_import_derives_slug_from_label -v`
Expected: FAIL — the loader raises `SprintError` (id↔filename mismatch: `id "June 2026" does not match filename "june"`), and/or the row is stored under `id="June 2026"` rather than the slug.

- [ ] **Step 3: Make the loader treat `id` as a label and stop requiring filename match**

In `sprint_pulse/sprints.py`:

In `load_sprints` (lines 228-237), remove the `_check_id_matches_filename(p, sprint.id)` call. Change the duplicate detection to run on derived slugs. Import or reference `slugify_label` — but `sprints.py` must not import from the service layer (the service imports from `sprints.py`). So add a local slug function in `sprints.py` and have the service's `slugify_label` delegate to it to keep one source of truth:

In `sprints.py`, add near the top (after imports):

```python
def slugify(label: str) -> str:
    """URL/JS-safe slug from a free-form label: 'June 2026' -> 'june-2026'."""
    import re
    return re.sub(r"[^a-z0-9._-]+", "-", label.strip().lower()).strip("-")
```

Then in Task 2's `sprint_service.slugify_label`, change it to delegate (do this now if not already): `return _sprints.slugify(label)` where `_sprints` is `sprint_pulse.sprints` (the service already imports from it). Update `sprint_service` import to expose it; verify Task 2 tests still pass after this refactor.

Update `load_sprints`:

```python
def load_sprints(directory: Path | str, cfg: Config) -> list[Sprint]:
    directory = Path(directory)
    files = sorted(p for p in directory.glob("*.yaml") if p.is_file())
    sprints: list[Sprint] = []
    for p in files:
        sprints.append(load_sprint_file(p, cfg))
    _check_duplicate_slugs([(p.name, slugify(s.id)) for p, s in zip(files, sprints)])
    return sorted(sprints, key=lambda s: (s.start, s.end, s.id))
```

Rename `_check_duplicate_ids` to `_check_duplicate_slugs` (lines 213-218), keeping the same logic but a slug-aware message:

```python
def _check_duplicate_slugs(pairs: list[tuple[str, str]]) -> None:
    """pairs: list of (filename, slug). Raises if any slug appears twice."""
    seen: dict[str, str] = {}
    for fname, slug in pairs:
        if slug in seen:
            raise SprintError(f"Duplicate sprint slug {slug} in {seen[slug]} and {fname}")
        seen[slug] = fname
```

Delete `_check_id_matches_filename` (lines 222-225) — no remaining caller.

**Note on the loaded dataclass `label`:** `load_sprint_file` returns `Sprint(id=sid, ...)` with no label. Set the label to the raw `sid` and the dataclass `id` can stay as the raw value here (the *DB* slug is derived at insert time in Task 5 Step 4). Update `load_sprint_file`'s return (line 210):

```python
    return Sprint(id=sid, label=sid, start=start, end=end, events=events, time_off=tuple(time_off))
```

- [ ] **Step 4: Derive the slug when inserting in migrate.py**

In `sprint_pulse/migrate.py`, the loop at lines 83-92 inserts `m.Sprint(id=sprint.id, ...)` and child `m.Event(sprint_id=sprint.id, ...)`. Derive the slug once and use it for both the row id and the event FK:

```python
        from sprint_pulse.sprints import slugify
        for sprint in sprints:
            slug = slugify(sprint.id)
            session.add(m.Sprint(id=slug, label=sprint.id, start=sprint.start, end=sprint.end))
            for ev in sprint.events:
                session.add(
                    m.Event(sprint_id=slug, date=ev.date, kind=ev.kind, title=ev.title)
                )
            # time_off rows are keyed by member/date, not sprint — unchanged.
```

(Move the `from sprint_pulse.sprints import slugify` import to the top of `migrate.py` with the other imports rather than inside the loop.)

- [ ] **Step 5: Update the loader tests that encoded the dropped checks**

In `tests/test_sprints.py`:
- Delete `test_id_mismatch_raises_via_directory` (lines 167-173) — the filename↔id rule is gone.
- Update `test_duplicate_sprint_id_raises` (lines 176-182) to call the renamed helper and match the new message:

```python
def test_duplicate_sprint_slug_raises(cfg: Config) -> None:
    from sprint_pulse.sprints import _check_duplicate_slugs
    with pytest.raises(SprintError, match="Duplicate sprint slug 2026-16"):
        _check_duplicate_slugs([("a.yaml", "2026-16"), ("b.yaml", "2026-16")])
```

- [ ] **Step 6: Run the affected tests**

Run: `python -m pytest tests/test_sprints.py tests/test_migration.py -v`
Expected: PASS. (If `load_config` rejected the tmp `config.yaml`, fix its keys to match the real fixture and re-run.)

- [ ] **Step 7: Commit**

```bash
git add sprint_pulse/sprints.py sprint_pulse/migrate.py tests/test_sprints.py tests/test_migration.py
git commit -m "feat(yaml): treat sprint id as label, derive slug on import"
```

---

## Task 6: Web UI — label field on create, label in listings

**Files:**
- Modify: `sprint_pulse/web/routers/sprints.py:38-53`
- Modify: `sprint_pulse/web/templates/sprints.html:10, 50-51`
- Modify: `sprint_pulse/web/templates/sprint_detail.html:2, 5`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing API test**

Add to `tests/test_api.py` (it already uses `TestClient`/`create_app` patterns — mirror an existing POST test). Read an existing sprint-creating test first for the client fixture shape, then add:

```python
def test_create_sprint_via_form_uses_label():
    from fastapi.testclient import TestClient
    from sprint_pulse.web.app import create_app
    client = TestClient(create_app(":memory:"))
    # Seed a member so we're past setup (mirror existing tests if they do this differently).
    r = client.post(
        "/sprints",
        data={"label": "June 2026", "start": "2026-06-01", "end": "2026-06-12"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/sprints/june-2026"
```

**Read `tests/test_api.py` first** to copy its exact app/client setup (some tests seed members or use a shared fixture). Align the new test with that pattern.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_api.py::test_create_sprint_via_form_uses_label -v`
Expected: FAIL — the route expects form field `sprint_id`, not `label`, so it 422s or redirects to the wrong location.

- [ ] **Step 3: Update the create route**

In `sprint_pulse/web/routers/sprints.py`, change the POST `/sprints` handler (lines 38-53) to accept `label` and redirect to the derived slug:

```python
@router.post("/sprints", response_class=HTMLResponse)
def create_sprint(
    request: Request,
    label: str = Form(...),
    start: date = Form(...),
    end: date = Form(...),
    session: Session = Depends(get_session),
):
    try:
        row = sprint_service.create_sprint(session, label, start, end)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(
            request, "sprints.html", _list_context(session, error=e.display())
        )
    return RedirectResponse(f"/sprints/{row.id}", status_code=303)
```

- [ ] **Step 4: Update the templates**

In `sprint_pulse/web/templates/sprints.html`:
- Line 10 — show the label as the link text, keep the slug in the href:
  `<td><a class="link" href="/sprints/{{ s.id }}">{{ s.label or s.id }}</a></td>`
- Lines 50-51 — relabel the form field to `label`:
  ```html
          <label for="label">Sprint name</label>
          <input type="text" id="label" name="label" placeholder="June 2026" required>
  ```

In `sprint_pulse/web/templates/sprint_detail.html`:
- Line 2 — `{% block title %}{{ sprint.label or sprint.id }} · Sprint Pulse{% endblock %}`
- Line 5 — `<h1>Sprint {{ sprint.label or sprint.id }}</h1>`

- [ ] **Step 5: Run the API test + full API file**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS. (If other API tests posted `sprint_id`, update those data dicts to `label` — they exercise the same route.)

- [ ] **Step 6: Commit**

```bash
git add sprint_pulse/web/routers/sprints.py sprint_pulse/web/templates/sprints.html sprint_pulse/web/templates/sprint_detail.html tests/test_api.py
git commit -m "feat(web): sprint create form takes a label; show labels in UI"
```

---

## Task 7: Full-suite green + snapshot reconciliation + manual smoke

**Files:**
- Possibly: `tests/snapshots/*` (if rendered HTML snapshots embed the old "Wisdom <id>" header)
- Test: entire suite

- [ ] **Step 1: Run the whole suite**

Run: `make test`
Expected: collect failures. Likely remaining failures: snapshot tests in `tests/test_*` that compare full rendered HTML containing the old `"Wisdom 2026-16"` headers, and any test still posting `sprint_id`.

- [ ] **Step 2: Inspect each failure and fix at the source**

For snapshot mismatches: confirm the diff is exactly the header change (label instead of `"<team> <id>"`) and column headers now showing labels. If the snapshot is intentionally regenerated, update the snapshot file; **read the diff first** to be sure no unintended change crept in. Document in the commit which snapshots changed and why.

For any other `sprint_id`-keyed form posts or assertions: switch them to `label`/slug as appropriate (mirroring Task 6).

- [ ] **Step 3: Re-run until green**

Run: `make test`
Expected: PASS (all tests).

- [ ] **Step 4: Manual smoke test (browser)**

Run: `make dev` (or `SPRINT_PULSE_DEMO=1 make dev` for offline Jira). In the browser (use `http://localhost:8765`, not `0.0.0.0`):
1. Create a sprint named `June 2026` on the Sprints page → it should appear as "June 2026" and live at `/sprints/june-2026`.
2. Open the dashboard → the sprint header and nav show "June 2026", with no "Wisdom" prefix; clicking the nav still switches sprints (slug DOM keys intact).
3. With Jira unconfigured (or demo), run Schedule → Run now → status is **ok** ("No matching Jira sprints…") rather than an error when nothing matches.

Record the observed results here.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "test: reconcile snapshots/tests for label-based sprint display"
```

---

## Self-review notes (author)

- **Spec coverage:** §1 identity → Tasks 1,2,5; §2 renderer/dataclass → Task 3; §3 refresh → Task 4; §4 YAML → Task 5; migration backfill → Task 1; web surface (not explicit in spec but required) → Task 6; non-goal (manual metrics) deliberately untouched — refresh only writes resolved rows, so unresolved rows keep any future manual metrics.
- **Cross-task consistency:** slug derivation has ONE source — `sprints.slugify` — with `sprint_service.slugify_label` delegating to it (Task 5 Step 3). `create_sprint`'s first arg is `label` everywhere. DOM keys are always `sprint.id` (slug); display is always `sprint.label or sprint.id`.
- **Known unknowns flagged for the implementer to verify against real files before writing tests:** the exact `config.yaml` key names for the tmp fixture (Task 5 Step 1), the `test_api.py` client/seed pattern (Task 6 Step 1), the precise body of `test_import_jira_sprints` (Task 2 Step 5), and whether any snapshot fixtures embed the old header (Task 7).
