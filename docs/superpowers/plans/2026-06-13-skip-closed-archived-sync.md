# Skip Closed/Archived Sprints During Sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `refresh_all` skip archived sprints and sprints already cached as closed, so they aren't re-fetched from Jira every run, and report what was skipped.

**Architecture:** A single guard at the top of the per-row loop in `sprint_pulse/services/refresh.py` (`continue` when `row.archived` or `row.jira_state == "closed"`), a `skipped` counter, and reworked last-run status messages that use `eligible = total − skipped`. Behavior is uniform for manual and scheduled runs. Plus documentation in the refresh skill and CLAUDE.md.

**Tech Stack:** Python, SQLModel/SQLite, pytest.

**Conventions:** Run tests with `make test` (project venv); lint with `make lint`. Commit after each task. Spec: `docs/superpowers/specs/2026-06-13-skip-closed-archived-sync-design.md`.

**Fixture facts (verified):** `tests/test_scheduler.py`'s `engine` fixture imports `valid_dir`, which yields exactly two sprints, `2026-16` and `2026-18` (the `archive/` subdir is skipped by the loader). Both import with `jira_state` defaulting to `"future"`, so the existing `test_run_now_updates_cache` (single run, asserts `updated == 2`) stays green — nothing is cached as closed on a fresh import.

---

### Task 1: Skip archived/closed sprints in `refresh_all` + reporting

**Files:**
- Modify: `sprint_pulse/services/refresh.py:18-88` (`refresh_all`)
- Test: `tests/test_scheduler.py` (append)

- [ ] **Step 1: Add a recording fake client and the failing tests**

Append to `tests/test_scheduler.py` (the file already imports `m`, `session_scope`, `jira_service`, `SchedulerManager`):

```python
class RecordingClient:
    """Fake Jira client that records which sprint ids it fetched metrics for."""

    def __init__(self):
        self.fetched: list[int] = []

    def fetch_sprints(self):
        return {
            "My Team 2026-16": {"id": 100, "state": "active"},
            "My Team 2026-18": {"id": 101, "state": "closed"},
        }

    def fetch_metrics(self, sprint_id):
        self.fetched.append(sprint_id)
        return {"done_n": 5, "tot_n": 68, "done_sp": 11, "tot_sp": 153}


def test_refresh_skips_closed_sprint(engine, monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(jira_service, "make_client", lambda s: client)
    with session_scope(engine) as s:
        row = s.get(m.Sprint, "2026-18")
        row.jira_state = "closed"
        row.done_n = 99  # sentinel that must survive the refresh
        s.add(row)
    result = SchedulerManager(engine).run_now()
    assert 101 not in client.fetched          # closed sprint never fetched
    assert 100 in client.fetched              # active sprint still fetched
    assert result["status"] == "ok"
    with session_scope(engine) as s:
        assert s.get(m.Sprint, "2026-18").done_n == 99  # cached numbers kept


def test_refresh_skips_archived_sprint(engine, monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(jira_service, "make_client", lambda s: client)
    with session_scope(engine) as s:
        row = s.get(m.Sprint, "2026-16")
        row.archived = True
        s.add(row)
    SchedulerManager(engine).run_now()
    assert 100 not in client.fetched          # archived sprint never fetched


def test_refresh_all_skipped_reports_ok(engine, monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(jira_service, "make_client", lambda s: client)
    with session_scope(engine) as s:
        c = s.get(m.Sprint, "2026-16")
        c.jira_state = "closed"
        s.add(c)
        a = s.get(m.Sprint, "2026-18")
        a.archived = True
        s.add(a)
    result = SchedulerManager(engine).run_now()
    assert result["status"] == "ok"
    assert client.fetched == []               # zero Jira metric calls
    assert "skipped" in result["log"]


def test_refresh_log_mentions_skipped_count(engine, monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(jira_service, "make_client", lambda s: client)
    with session_scope(engine) as s:
        row = s.get(m.Sprint, "2026-18")
        row.jira_state = "closed"
        s.add(row)
    result = SchedulerManager(engine).run_now()
    assert result["updated"] == 1             # only 2026-16 updated
    assert "1 closed/archived skipped" in result["log"]
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `make test 2>&1 | tail -20` (or target the file via the venv: `.venv/bin/python -m pytest tests/test_scheduler.py -v`)
Expected: the four new tests FAIL — closed/archived sprints are currently fetched, `client.fetched` contains the ids, and the log has no "skipped" text.

- [ ] **Step 3: Implement the skip guard + reporting**

Replace the body of `refresh_all` from the `prefix = ...` line through the end of the function (`sprint_pulse/services/refresh.py:41-88`) with:

```python
    prefix = settings.team_name or "My Team"
    by_jira_id = {info["id"]: info for info in jira_sprints.values()}
    rows = list(session.exec(select(m.Sprint)).all())
    updated = 0
    matched = 0
    skipped = 0
    metric_failures = 0
    for row in rows:
        # Archived sprints are off the dashboard and closed sprints have final
        # numbers — skip both (before any Jira call) so we don't re-fetch
        # unchanging data every run. "closed" is judged from our cached state:
        # the run that first sees a sprint close still captures it once.
        if row.archived or row.jira_state == "closed":
            skipped += 1
            continue
        # Prefer the stored Jira numeric id; fall back to the "{team} {id}" name
        # for sprints imported before that was tracked (e.g. YAML-migrated).
        info = None
        if row.jira_sprint_id is not None:
            info = by_jira_id.get(row.jira_sprint_id)
        if info is None:
            info = jira_sprints.get(f"{prefix} {row.label or row.id}")
        if not info:
            continue
        matched += 1
        try:
            metrics = client.fetch_metrics(info["id"])
        except JiraUnavailable:
            # Leave cached state + metrics untouched so we don't show a stale
            # state next to fresh numbers (or vice versa); count it as a failure.
            metric_failures += 1
            continue
        row.jira_state = info["state"]
        row.done_n = metrics["done_n"]
        row.tot_n = metrics["tot_n"]
        row.done_sp = metrics["done_sp"]
        row.tot_sp = metrics["tot_sp"]
        row.last_refreshed = now
        updated += 1
        session.add(row)

    eligible = len(rows) - skipped
    settings.last_run = now
    if eligible == 0:
        settings.last_status = "ok"
        if skipped:
            settings.last_log = (
                f"No active sprints to sync ({skipped} closed/archived skipped)."
            )
        else:
            settings.last_log = "No sprints to sync."
    elif matched == 0:
        settings.last_status = "ok"
        settings.last_log = "No matching Jira sprints — nothing to update."
    elif metric_failures:
        settings.last_status = "error"
        settings.last_log = (
            f"Updated {updated}/{eligible} sprints; "
            f"{metric_failures} metric fetch(es) failed (stale numbers kept)."
        )
    else:
        settings.last_status = "ok"
        skip_note = f" ({skipped} closed/archived skipped)" if skipped else ""
        settings.last_log = f"Updated {updated}/{eligible} sprints{skip_note}."
    session.add(settings)
    return {"status": settings.last_status, "updated": updated, "log": settings.last_log}
```

Also update the function docstring (`refresh.py:19-20`) to:

```python
    """Update cached Jira metrics for every sprint. Records last-run status on
    Settings. Archived sprints and sprints already cached as closed are skipped
    (their final numbers are kept); only future/active sprints are synced.
    Returns a small summary dict."""
```

- [ ] **Step 4: Run the suite**

Run: `make test 2>&1 | tail -5`
Expected: all pass — the four new tests plus the existing `test_run_now_updates_cache` (still `updated == 2`, since fresh-import sprints are cached `"future"`, not skipped).

- [ ] **Step 5: Lint**

Run: `make lint`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add sprint_pulse/services/refresh.py tests/test_scheduler.py
git commit -m "feat(refresh): skip archived/closed sprints during metrics sync

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Document the skip behavior

**Files:**
- Modify: `.claude/skills/refresh-sprint-metrics/SKILL.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the refresh skill**

In `.claude/skills/refresh-sprint-metrics/SKILL.md`, find the paragraph in "How to Refresh" that begins `The scheduler runs the same pipeline` and ends `Jira is optional.` Insert this sentence immediately before `Sprints that resolve to nothing are skipped silently`:

```markdown
Archived sprints and sprints already cached as **closed** are skipped before any
Jira call (their final numbers are kept), so only future/active sprints are
re-fetched — the same for manual *Refresh metrics now* and scheduled runs.
```

- [ ] **Step 2: Update CLAUDE.md**

In `CLAUDE.md`, in the "Constraints worth remembering" list, replace the bullet:

```markdown
- Jira sprint state (closed/active/future) and metrics are fetched by the refresh pipeline
  and cached on the sprint row; the dashboard renders from that cache.
```

with:

```markdown
- Jira sprint state (closed/active/future) and metrics are fetched by the refresh pipeline
  and cached on the sprint row; the dashboard renders from that cache. The refresh skips
  archived sprints and sprints already cached as closed (their final numbers are kept), so
  only future/active sprints are re-fetched — manual and scheduled runs alike.
```

- [ ] **Step 3: Sanity check the suite still passes**

Run: `make test 2>&1 | tail -3`
Expected: all pass (docs-only change; nothing should break).

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/refresh-sprint-metrics/SKILL.md CLAUDE.md
git commit -m "docs: note refresh skips archived/closed sprints

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
