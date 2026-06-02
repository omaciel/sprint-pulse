# Individual-level time-off with a calendar — design

**Date:** 2026-06-02
**Status:** Approved

## Context

Today time-off is managed at the **sprint** level. Each absence (`TimeOff` row)
is anchored to *both* a `sprint_id` and a `member_id`, and its days must fall
inside that sprint's `[start, end]` window. To see or edit someone's outage you
open a sprint and use its time-off form; there is no per-member view.

We want to manage availability at the **individual** level: open a member's page,
see a calendar of their availability, and add/update absences intuitively. Since
sprints already carry start/end dates, a sprint's team outage can be **derived**
from date overlap rather than stored against the sprint. Editing a sprint then
focuses on its **dates and events** (tags / go-no-go / GA / freeze / test).

## Decisions (from brainstorming)

- **Anchor time-off to the member only**, not the sprint. Sprints derive outage
  from date overlap.
- **Date validation relaxes to weekday-only** (Mon–Fri); a day need not fall in
  any sprint. Absences outside every sprint window are still recorded and shown
  on the member's calendar; they appear on the dashboard once a sprint covers
  them.
- **Holidays stay per-member** (one absence per member, bulk-created) — no new
  team-wide Holiday entity (avoids capacity/rendering scope creep).
- **One record per (member, day)** — flatten `TimeOff` + `TimeOffDay` into a
  single `MemberDayOff` table. Clicking a day creates/clears exactly one row.
- **Type is explicit** (chosen from a UI palette); keyword inference
  (`infer_type`) is retained only for the YAML import path.
- **Calendar layout:** one large month grid, navigated month-by-month.
- **Member page extras:** year/quarter days-off stat, orchestration toggle,
  upcoming-absences list.
- **Sprint detail page:** editable start/end dates, events CRUD, and a
  read-only derived "who's out this sprint" list. Time-off editing removed.
- **Add the ability to edit a sprint's dates** (new capability).

## Data model

New table replacing `TimeOff` + `TimeOffDay`:

```
MemberDayOff
  id:        int  PK
  member_id: int  FK -> TeamMember.id, indexed
  date:      date
  type:      str  # pto | holiday | company | partial | tentative
  notes:     str = ""
  UNIQUE(member_id, date)
```

- Drop `TimeOff`, `TimeOffDay`, and the `sprint_id` anchor.
- **Migration:** a one-off step that runs at engine init (alongside the existing
  `create_all`) — if the legacy `TimeOff`/`TimeOffDay` tables exist, flatten
  their rows into `MemberDayOff` (deduping on `(member_id, date)`), then drop the
  old tables. On a type conflict keep the higher-priority type
  (`company > holiday > pto > partial > tentative`) and the first non-empty note.
  Idempotent: a no-op once the legacy tables are gone.
- `Sprint`, `Event`, `TeamMember`, `NameAlias`, `Settings` are unchanged.

## Services (`sprint_pulse/services/`)

New `time_off_service.py`:

- `set_days(session, member, dates, type, notes)` — upsert one row per day
  (replaces type/notes if the day already exists).
- `clear_days(session, member, dates)` — delete those rows.
- `member_calendar(session, member, month)` → `{date: (type, notes)}` for a month.
- `sprint_outage(session, sprint)` → derived entries where
  `sprint.start <= date <= sprint.end`.

Validation relaxes to **weekday-only**: reuse a trimmed `working_day_error`
(weekday check without the sprint-window clause). Unknown-associate resolution
(Levenshtein suggestion) and orchestration carve-out are preserved.

**Renderer reuse:** dashboard hydration reconstructs the existing frozen
`TimeOffEntry(associate, days, type, notes)` objects by grouping a member's
`MemberDayOff` rows per `(type, notes)`, so `render.py` and the
capacity/availability math are reused unchanged. Outage is gathered by **date
overlap**, not `sprint_id`. Existing dashboard snapshot tests should stay green.

## Web layer (`sprint_pulse/web/`)

- **Team roster** (`members.html`): each member name links to `/members/{id}`.
- **Member page** `GET /members/{id}` → `member_detail.html`, with a
  `partials/_calendar.html` HTMX partial. Month nav via `?month=YYYY-MM`.
  - `POST /members/{id}/timeoff` — set day(s) to type+notes (single click, or a
    From/To range quick-add). Returns the re-rendered calendar partial.
  - `POST /members/{id}/timeoff/clear` — clear day(s). Returns the partial.
  - Sidebar: days-off stat (year/quarter), orchestration toggle (reuses existing
    toggle service), upcoming-absences list.
  - A small isolated `static/calendar.js` (the app's first custom JS) tracks the
    selected palette type and posts day clicks via HTMX `hx-vals`. MVP:
    click-to-paint single days + range quick-add. Drag-to-paint is a documented
    follow-up, not in this scope.
- **Sprint detail** (`sprint_detail.html`):
  - Remove the time-off form and the `POST /sprints/{id}/timeoff[...]` routes.
  - Add `POST /sprints/{id}/dates` (edit start/end, validates `end >= start`).
  - Add a read-only derived outage list via `sprint_outage`.
  - Events CRUD unchanged.

## Testing

- **Service tests:** `set/clear` idempotency, `UNIQUE(member, date)` upsert
  behavior, weekday-only validation, `sprint_outage` date-overlap including
  absences outside any sprint window, migration dedup/conflict resolution.
- **Web tests (httpx):** member page renders; paint and clear round-trip through
  the calendar partial; sprint date-edit re-derives the outage list; roster names
  link to member pages; old time-off routes are gone.
- **Snapshot tests:** existing dashboard HTML snapshots remain green for
  equivalent data (renderer output unchanged).

## Out of scope

- Team-wide Holiday entity.
- Drag-to-paint range selection (click + range quick-add only for MVP).
- Any change to Jira metrics refresh, scheduler, or capacity formula.
