# Skip closed/archived sprints during metrics sync — design

**Date:** 2026-06-13
**Status:** Approved (brainstorming session)

## Problem

The metrics refresh pipeline (`sprint_pulse/services/refresh.py:refresh_all`) walks
**every** sprint row each run and fetches live metrics from Jira for each one. Sprints
that are **archived** (dropped off the dashboard) or **closed** in Jira have final,
unchanging numbers, yet they're re-fetched on every scheduled and manual run — wasted
Jira API calls and slower syncs for data that will never change.

## Goal

During synchronization, do not re-fetch sprints that are archived or already closed.
They keep their last cached metrics; only future/active sprints are synced.

## Decisions (from brainstorming)

- **"Closed" is judged from our cached `jira_state`**, not a live re-check. The refresh
  that *first* observes a sprint close (cache still active/future) runs once, captures
  the final numbers, and writes `jira_state="closed"`. Every run after that skips it and
  makes **zero** Jira calls for it. This is the entire savings.
- **Uniform behavior**: manual "Refresh metrics now" and scheduled/automatic runs both
  skip closed/archived. No second code path. Correcting a closed sprint's numbers, if
  ever needed, is done by unarchiving (or the sprint reopening in Jira and the operator
  forcing a state change) — not by a special refresh mode.

## Approach (chosen: explicit guard in the loop)

Alternatives considered: a SQL `WHERE` filter (leanest diff, but skipped sprints vanish
silently with no count to report and muddier "nothing to sync" messaging) and a shared
`eligible_sprints()` helper (no second caller today — YAGNI). **Explicit guard** keeps
the skip intent readable and lets the status pill report what was skipped.

### Behavior

In `refresh_all`, still load all sprint rows, but at the top of the per-row loop
`continue` when the row is archived or already closed — before any Jira matching or
metric fetch:

```python
if row.archived or row.jira_state == "closed":
    skipped += 1
    continue
```

Future/active sprints sync exactly as today.

### Reporting

Track `skipped`; `eligible = len(rows) - skipped`. The last-run status/log on `Settings`
becomes:

- `eligible == 0` → status `ok`, log `"No active sprints to sync."`, with
  `" (N closed/archived skipped)"` appended when `N > 0`.
- `eligible > 0` and `matched == 0` → status `ok`,
  `"No matching Jira sprints — nothing to update."` (unchanged).
- metric fetch failures → status `error`,
  `"Updated X/{eligible} sprints; F metric fetch(es) failed (stale numbers kept)."`
- otherwise → status `ok`, `"Updated X/{eligible} sprints"` with
  `" (Z closed/archived skipped)"` appended when `Z > 0`.

The returned summary dict keeps its shape (`status`, `updated`, `log`).

## Documentation (required)

The skip behavior must be written down where operators and future contributors look:

- **`.claude/skills/refresh-sprint-metrics/SKILL.md`** — note in the "How to Refresh"
  section that archived and already-closed sprints are skipped (their cached final
  numbers are kept), and that this applies to both manual and scheduled runs.
- **`CLAUDE.md`** — extend the existing Jira/refresh constraint bullet so the data model
  note records that the refresh pipeline skips archived/closed sprints.

## Testing

New tests in `tests/test_scheduler.py` (the existing home for refresh/run-now tests):

- A closed sprint (`jira_state="closed"`) is never passed to `fetch_metrics` and keeps
  its cached numbers.
- An archived sprint is never passed to `fetch_metrics`.
- An active/future sprint is still fetched and updated.
- All sprints closed/archived → status `ok`, log mentions the skipped count, zero
  `fetch_metrics` calls.
- The skipped count appears in the log on a normal partial run.

## Out of scope

- The Jira import-candidate list (`available_jira_sprints` / `import_jira_sprints`) — it
  lists Jira board sprints and has no "archived" concept.
- The dashboard renderer.
