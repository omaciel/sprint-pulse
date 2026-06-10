# Departed members with preserved history — design

**Date:** 2026-06-10
**Status:** Approved (brainstorming session)

## Problem

Team composition changes over time. Today the only way to stop counting someone is
the Team page's hard delete, which cascades away their aliases and all
`MemberDayOff` rows, and — because the dashboard renders every sprint against the
*current* global roster — erases them from past sprints entirely. Past availability
percentages also silently recompute whenever the roster changes size.

## Goals

- A member who leaves stays visible, with their time off, in every sprint that
  overlapped their tenure — and in no sprint after it.
- Past sprints' capacity and availability numbers stay historically accurate: they
  count exactly the people who were on the team during that sprint, prorated for
  mid-sprint joins/leaves.
- New hires do not appear in (or inflate the capacity of) sprints that ended before
  they joined.
- Hard delete remains available for genuine mistakes (typo entries, test data).
- Existing installs upgrade with zero backfill and identical numbers.

## Non-goals

- Tracking multiple tenure stints per person (leave → rejoin with a gap). Rejoin
  simply clears the end date.
- Any change to Jira metrics refresh, the Types system, or sprint archiving.

## Approach (chosen: tenure dates)

Alternatives considered: a bare "departed" flag (no date → cannot scope which
sprints the person belongs to; fails the accuracy goal) and per-sprint roster
snapshots (audit-proof but heavyweight, awkward retroactive correction, duplicates
what tenure dates derive). **Tenure dates** won: minimal schema, accurate by
construction, no backfill.

### Data model

`TeamMember` gains two nullable columns, added via the existing startup-migration
helper in `sprint_pulse/db/engine.py` (`ALTER TABLE ADD COLUMN` path):

- `start_date: date | None` — `NULL` = member since before recorded history.
- `end_date: date | None` — `NULL` = still on the team.

**Tenure rule.** Member M belongs to sprint S iff
`(M.start_date IS NULL OR M.start_date <= S.end) AND
 (M.end_date IS NULL OR M.end_date >= S.start)`.

### Services & capacity

- `sprint_service._load` computes a **per-sprint roster and excluded set** with the
  tenure rule and hands the renderer a per-sprint
  `dataclasses.replace(cfg, roster=…, excluded=…, tenures=…, capacity_override=…)`.
- `Config` (frozen dataclass, `sprint_pulse/config.py`) gains two optional fields:
  - `tenures: Mapping[str, tuple[date | None, date | None]]` — populated only for
    members that have tenure dates.
  - `capacity_override: int | None` — when set, the `capacity` property returns it.
- **Prorated capacity per sprint** = for each effective (non-excluded) member
  overlapping the sprint, the number of working days inside both the sprint and the
  member's tenure, summed. Full-tenure members contribute
  `working_days_per_sprint`, so a dateless roster reproduces today's numbers
  exactly.
- New service functions in `config_service`:
  - `depart_member(session, member_id, end_date)` — validates
    `end_date >= start_date` when both set, deletes `MemberDayOff` rows dated after
    `end_date`, sets the column.
  - `rejoin_member(session, member_id)` — clears `end_date`; only valid for
    departed members.
- `remove_member` (hard delete + cascade) is unchanged.
- Aliases of former members are **kept** — they still resolve historical names.
- Days Out needs no change: post-departure time off is deleted, and validation
  prevents new out-of-tenure entries, so absent-day sums stay within tenure.

### Rendering

One deliberate, focused extension to the otherwise-reused render core:
`_render_cell` in `sprint_pulse/render.py` renders a member's out-of-tenure days
(per `cfg.tenures`) as inert gray cells — same visual family as Orchestration
rows — so the heatmap visibly explains a prorated capacity. No other renderer
changes; availability strings already read `cfg.capacity`.

### UX

- **Team page** splits into **Active roster** and **Former members** (mirrors the
  Sprints page's Archived section). Active rows gain a **"Departed…"** action
  revealing a date input defaulting to today; the confirmation states the side
  effect: *"Time off after \<date\> will be removed."* Former rows show tenure
  ("until 2026-05-30"), **Rejoin**, and the hard **Delete** with its destructive
  confirmation.
- **Add-member form** gains optional **"Joined on"** (blank = always been here).
- **Member calendar** still opens for former members with a banner
  ("Former member — left 2026-05-30"); marking days outside tenure is rejected
  with a clear validation message.
- **Dashboard:** former members appear only in overlapping sprints; mid-sprint
  joins/leaves show gray out-of-tenure cells.

### Routes

- `POST /members/{id}/depart` (form field `end_date`, default today).
- `POST /members/{id}/rejoin`.
- `POST /members` accepts optional `start_date`.
- Existing toggle/delete/timeoff routes unchanged (timeoff gains tenure
  validation in the service layer).

## Validation

- `end_date >= start_date` when both set.
- Time-off dates must be working days, inside the sprint-agnostic member tenure
  (new), in addition to existing rules.
- Rejoin rejected for members who are not departed.

## Testing

- Tenure-overlap rule: all four null/set combinations, boundary dates.
- Prorated capacity: mid-sprint leave, mid-sprint join, leave on sprint boundary,
  dateless roster regression (numbers identical to today).
- `depart_member`: time-off trimming, validation errors; `rejoin_member` guards.
- Rendering: out-of-tenure gray cells; departed member present in old sprint,
  absent from later sprint.
- Migration: pre-existing DB gains both columns idempotently.
