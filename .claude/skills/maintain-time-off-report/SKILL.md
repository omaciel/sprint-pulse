---
name: maintain-time-off-report
description: Use when adding time off, adding sprints, managing the team roster, or otherwise updating Sprint Pulse. Sprint Pulse is now a web/desktop app backed by SQLite — edits happen through the UI or its HTTP API. This skill documents the data model, validation rules, and the (now user-configurable) event & absence types — all enforced at the service layer.
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
| Team roster, excluded members | **Team** page (`/members`) |
| A member's time off (calendar) | **Team → a name** (`/members/{id}`) |
| Sprints + release events | **Sprints** page (`/sprints`, `/sprints/{slug}`) |
| Event & absence **types** (CRUD) | **Types** page (`/types`) |
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

Time off is **per member**, set on that member's availability calendar: open
**Team → a name** (`/members/{id}`), pick an **absence type** from the dropdown,
then click weekdays (or use the **From**/**To** range) to mark or clear them.
Sprints derive their own "who's out" list automatically by date overlap — you don't
attach time off to a sprint.

```bash
# one day
curl -X POST http://localhost:8765/members/3/timeoff \
  -d date=2026-04-24 -d type=pto -d notes="PTO"
# a range (expanded to working days)
curl -X POST http://localhost:8765/members/3/timeoff \
  -d start=2026-04-24 -d end=2026-04-28 -d type=holiday -d notes="Easter"
```

### Absence types

`type` must be the **key** of an existing absence type. The defaults seeded on first
run (manage them on the **Types** page, `/types`):

| Key | Letter | Default meaning |
| --- | --- | --- |
| `pto` | P | PTO |
| `holiday` | H | Regional / national holiday |
| `company` | C | Company holiday |
| `partial` | ~ | Partial availability |
| `tentative` | ? | Tentative |

Add / rename / recolor (from a fixed palette) / delete absence types on **Types**.
Each type's **color** drives its cell on the dashboard and calendar; its
**abbreviation** is the letter shown in the cell. `notes` is free text (shown on
hover) and **does not** set the type — you pick the type explicitly. (Keyword
inference from notes still applies to the one-time **YAML import** only.)

## Adding a Release Event

On the sprint detail page use the **Release events** form. `kind` must be the **key**
of an existing **event type**. Defaults seeded on first run (manage on **Types**,
`/types`):

| Key | Letter | Default meaning |
| --- | --- | --- |
| `tags` | T | Git tags due |
| `gono` | G | Go/No-Go deadline |
| `ga` | R | Target release / GA |
| `freeze` | F | Release freeze |
| `test` | X | Testathon |

Add / rename / recolor / delete event types on **Types**. Sprint header bullets are
auto-derived from event titles + dates.

## Adding a Sprint

Two ways on the **Sprints** page:

- **Import from Jira** (when Jira is configured) — lists every sprint on the board
  (any name), suggests a short label you can edit, and imports the ones you tick;
  start/end dates come from Jira. Each imported sprint stores its Jira numeric id, so
  metrics refresh matches by id regardless of the board's naming. Sprints with no
  dates in Jira must be added manually. Jira is **optional** — the app is fully usable
  without it.
- **Add manually** — enter a free-form **name** (e.g. `June 2026` or `2026-28`); a
  URL-safe **slug id** is derived automatically (`june-2026`) and used in the URL.
  Set start/end dates. Sprints are 14 calendar days (10 working days) by convention
  and are ordered on the dashboard by their dates (not by id).

## Removing / archiving

- **Archive** a sprint from the Sprints page to drop it off the dashboard and summary
  while keeping it (it moves to an "Archived" section; one click to unarchive). This
  replaces the old `archive/` folder.
- **Delete** permanently removes a sprint and its events/time off.
- To stop counting someone, remove them on the Team page (their time-off entries are
  cleaned up too).

## Validation (enforced at the service layer)

- Sprint **slug id** (derived from the name) is unique; `end >= start`.
- Event/time-off dates must be working days within `[start, end]`.
- Event `kind` and time-off `type` must be existing types (see the **Types** page).
- Associates must be on the roster (or `__all__`); unknown names return a Levenshtein
  suggestion (e.g. `unknown associate "Alice Andersen" (typo? did you mean "Alice Anderson")`).
- Roster names are unique; **excluded** members are a subset of the roster; alias
  targets must be existing members.

## Effective Team & Capacity

Set on the Team + Settings pages:

- **roster** — all members, in display order.
- **excluded** — members who don't count toward capacity (shown gray). Toggle per
  member on the Team page (`is_excluded`).
- **working_days_per_sprint** — default 10 (Settings).
- **aliases** — alternate name → canonical member.

Capacity = `(len(roster) − len(excluded)) × working_days_per_sprint`
Availability = `(Capacity − Days Out) / Capacity × 100`, one decimal.

## Common Mistakes

- **Editing the old `data/*.yaml`.** Those are import-only now; changes there won't
  appear. Edit through the app.
- **Expecting notes to set the absence type.** In the app the **type** you pick (not
  the notes text) sets the color/letter — choose Holiday / Company / etc. explicitly.
  (Notes-keyword inference only applies to the one-time YAML import.)
- **Mixing types on one day.** A member has one absence type per day; pick the right one.
- **Non-working-day dates.** Weekends fail validation — only Mon–Fri.

## Related

- **refresh-sprint-metrics** — refreshing Jira metrics via the scheduler.
