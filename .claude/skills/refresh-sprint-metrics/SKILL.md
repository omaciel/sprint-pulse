---
name: refresh-sprint-metrics
description: Use when refreshing the team sprint report with current Jira data (tickets done/total, story points done/total). Sprint Pulse is now a web/desktop app backed by SQLite; metrics are refreshed via the in-app scheduler.
---

# Refresh Sprint Metrics

## Overview

Sprint Pulse is a FastAPI + SQLite app (desktop via pywebview, or browser via the
container). The refresh pipeline pulls live numbers from Jira's Greenhopper sprint
report API for every sprint, recomputes availability, and **caches the metrics on
the sprint rows in the database**. The dashboard then renders instantly from that
cache — there is no static HTML file to regenerate anymore.

## When to Use

- User asks to refresh / update / sync sprint metrics
- After a sprint closes — lock in final numbers
- Mid-sprint to see current burndown

## How to Refresh

**In the app (preferred):** open **Schedule** in the top nav and click **Refresh
metrics now**. The status pill shows `ok` / `error` and the last-run time. You can
also enable automatic refresh on an interval or cron there.

**Via the API:**
```bash
curl -X POST http://localhost:8765/scheduler/run
```

The scheduler runs the same pipeline (`sprint_pulse/services/refresh.py`): for each
sprint it resolves a Jira sprint by the stored Jira id (set on import) first, then
falls back to a `{team_name} {label}` name match; on a hit it fetches state + metrics
and writes `done_n`, `tot_n`, `done_sp`, `tot_sp`, and `jira_state` onto the sprint
row. Sprints that resolve to nothing are skipped silently, and "no matching sprints"
is reported as `ok` (nothing to update) — not an error. Jira is optional.

## Prerequisites

- Jira connection configured under **Settings** (site, board id, username) with the
  API token saved.
  - **Desktop:** token is stored in the OS keychain.
  - **Container:** token comes from the `JIRA_API_TOKEN` env var.
- A reachable Jira (VPN if required). On failure the status pill reads `error` with
  a message ("Could not reach Jira … On the VPN?").

## Troubleshooting

If the numbers don't match expectations, check that:
- The sprint is on the configured Scrum board (**Settings → Board id**).
- The sprint is linked to Jira — either imported from the board (so it stores the
  Jira id), or its name matches `{team_name} {label}` (e.g. `My Team 2026-18`).
  Unlinked sprints are skipped (not an error); re-import them to attach a Jira id.

## Related

- **maintain-time-off-report** — schema, cell vocabulary, and conventions for
  editing the team, sprints, events, and time off through the app.
