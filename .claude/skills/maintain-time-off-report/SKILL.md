---
name: maintain-time-off-report
description: Use when adding time off, adding sprints, managing the team roster, or otherwise updating Sprint Pulse. Sprint Pulse is now a web/desktop app backed by SQLite — edits happen through the UI or its HTTP API. This skill documents the data model, validation rules, and event vocabulary (all still enforced at the service layer).
---

# Maintain Sprint Pulse

## Overview

Sprint Pulse is a FastAPI + SQLite app. **SQLite is the source of truth** — the old
`data/*.yaml` files are now used only for the one-time import on first run. Edit data
through the UI (top nav: Dashboard / Sprints / Team / Settings / Schedule) or the HTTP
API. All the validation rules and vocabulary below are enforced in the service layer
(`sprint_pulse/services/`), exactly as the YAML loader used to enforce them.

| Area | Where |
| --- | --- |
| Team roster, orchestration | **Team** page (`/members`) |
| Sprints, events, time off | **Sprints** page (`/sprints`, `/sprints/{id}`) |
| App settings, Jira connection | **Settings** page (`/config`) |
| Metric refresh + scheduler | **Schedule** page (`/scheduler`) — see **refresh-sprint-metrics** |
| One-time YAML import | first-run wizard, or `python3 migrate_yaml_to_sqlite.py` |

## Running the app

```bash
make dev          # browser at http://localhost:8765
make dev-desktop  # native window (pywebview)
make container-run # browser, in a container
```

First run with an empty DB shows a setup wizard (app settings → Jira → team → optional
YAML import).

## Adding Time Off

On a sprint's detail page (`/sprints/{id}`), use the **Time off** form: pick the
associate (or "Everyone"), a **From**/**To** date range (expanded to working days),
and notes. Equivalent API call:

```bash
curl -X POST http://localhost:8765/sprints/2026-16/timeoff \
  -d associate="Alice Anderson" -d start=2026-04-24 -d end=2026-04-24 -d notes="PTO"
```

### Time-off vocabulary

- **associate** — a roster name, or `__all__` for company-wide (expands to one entry
  per member). Aliases configured on the Team page resolve to canonical names.
- **days** — working days (Mon–Fri) within the sprint's `[start, end]`.
- **notes** — free text; drives the cell color via type inference:
  - contains `company` → company holiday (purple `C`)
  - contains `partial` → partial availability (yellow `~`)
  - contains `tentative` → tentative (yellow striped `?`)
  - contains a holiday keyword (`holiday`, `Memorial Day`, `Pentecost`, `Liberation`,
    `Victoria`, `Independence`, `Easter`, …) → holiday (blue `H`)
  - otherwise → PTO (red `P`)

If an absence spans multiple types, add separate entries.

## Adding a Release Event

On the sprint detail page use the **Release events** form. `kind` is a closed
vocabulary:

| Kind | Letter | Meaning |
| --- | --- | --- |
| `tags` | T | Git tags due |
| `gono` | G | Go/No-Go deadline |
| `ga` | R | Target release / GA |
| `freeze` | F | Release freeze |
| `test` | X | Testathon |

Sprint header bullets are auto-derived from event titles + dates.

## Adding a Sprint

Two ways on the **Sprints** page:

- **Import from Jira** (preferred) — lists every sprint on the configured board
  (any name), suggests a short id (`2026-16`) you can edit, and imports the ones you
  tick; start/end dates come from Jira. Each imported sprint stores its Jira numeric
  id, so metrics refresh matches by id regardless of the board's naming. Sprints with
  no dates in Jira must be added manually.
- **Add manually** — enter an `id` label (e.g. `2026-28`; letters, numbers, `.`, `_`,
  `-`, no spaces) and start/end dates. Sprints are 14 calendar days (10 working days)
  by convention, and are ordered on the dashboard by their dates (not by id).

## Removing / archiving

- **Archive** a sprint from the Sprints page to drop it off the dashboard and summary
  while keeping it (it moves to an "Archived" section; one click to unarchive). This
  replaces the old `archive/` folder.
- **Delete** permanently removes a sprint and its events/time off.
- To stop counting someone, remove them on the Team page (their time-off entries are
  cleaned up too).

## Validation (enforced at the service layer)

- Sprint `id` is unique; `end >= start`.
- Event/time-off dates must be working days within `[start, end]`.
- Event `kind` must be in the closed vocabulary above.
- Associates must be on the roster (or `__all__`); unknown names return a Levenshtein
  suggestion (e.g. `unknown associate "Alice Andersen" (typo? did you mean "Alice Anderson")`).
- Roster names are unique; orchestration members are a subset of the roster; alias
  targets must be existing members.

## Effective Team & Capacity

Set on the Team + Settings pages:

- **roster** — all members, in display order.
- **orchestration** — members excluded from availability (gray cells, 0 capacity).
- **working_days_per_sprint** — default 10 (Settings).
- **aliases** — alternate name → canonical member.

Capacity = `(len(roster) − len(orchestration)) × working_days_per_sprint`
Availability = `(Capacity − Days Out) / Capacity × 100`, one decimal.

## Common Mistakes

- **Editing the old `data/*.yaml`.** Those are import-only now; changes there won't
  appear. Edit through the app.
- **Empty notes for a regional holiday.** Leaves the cell as PTO — always include the
  holiday name (e.g. "Czech Republic holiday").
- **Mixing types in one entry.** Split into separate entries by type.
- **Non-working-day dates.** Weekends fail validation — only Mon–Fri.

## Related

- **refresh-sprint-metrics** — refreshing Jira metrics via the scheduler.
