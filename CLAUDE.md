# sprint-pulse — Claude Code context

Sprint Pulse is a team availability dashboard. It is a **FastAPI + SQLite** app that
reuses the original domain core (validation, Jira client, HTML renderer) and runs two
ways from one codebase: a **desktop app** (pywebview window) and a **containerized web
app** (browser). It pulls live Jira metrics on a schedule and renders an availability
heatmap. 100% Python — no Rust/Node.

## Architecture

- **`sprint_pulse/db/`** — SQLModel models + engine (`Settings`, `TeamMember`,
  `NameAlias`, `Sprint`, `Event`, `TimeOff`, `TimeOffDay`). SQLite is the source of truth.
- **`sprint_pulse/services/`** — validated reads/writes; hydrate the frozen `Config`/
  `Sprint` dataclasses so the renderer is reused unchanged. `secrets.py` (token store),
  `refresh.py` (Jira pipeline), `jira_service.py`.
- **`sprint_pulse/web/`** — FastAPI app (`app.py` factory), Jinja2 + HTMX templates,
  routers (`dashboard`, `setup`, `members`, `sprints`, `config_page`, `scheduler`),
  and the APScheduler wrapper (`scheduler.py`).
- **`sprint_pulse/desktop.py`** — pywebview shell (runs the app in a thread, opens a window).
- **`sprint_pulse/{config,sprints,jira,render}.py`** — the original domain core, reused.
- **`migrate_yaml_to_sqlite.py`** + **`examples/*.yaml`** — a one-time YAML→SQLite
  importer and fictional sample data. (Real operator data lives outside the repo.)
- **`Containerfile`** — browser deployment. **`packaging/sprint_pulse.spec`** — desktop bundle.

## Default workflow

Data is edited through the app (UI or HTTP API), not by hand-editing files:

1. Run the app: `make dev` (browser) or `make dev-desktop` (native window).
2. Add/change time off, events, sprints, or team members via the relevant page
   (Sprints / Team), or POST to the matching route.
3. Refresh Jira metrics via **Schedule → Run now** (or `POST /scheduler/run`).
4. The dashboard re-renders from the DB — no file to regenerate, no browser tab to nudge.

For structural changes, edit `sprint_pulse/` and run `make test`.

## Skills

Two project-scoped skills live in `.claude/skills/` — invoke via the `Skill` tool before responding:

- **maintain-time-off-report** — data model, type inference, event vocabulary, validation
  rules, and how to edit team/sprints/time-off through the app.
- **refresh-sprint-metrics** — refreshing Jira metrics via the scheduler.

## Constraints worth remembering

- **SQLite is the source of truth.** YAML (`examples/`, or your own dir) is import-only;
  editing it has no effect on a running install. Don't hand-edit generated output.
- Members flagged as **Orchestration** (toggled on the Team page, or the `orchestration:`
  list when importing YAML) render gray (`external`) regardless of PTO/holiday and are
  excluded from capacity.
- The `notes` field on a time-off entry drives cell color via keyword matching; empty notes
  default to PTO. Split multi-type absences into separate entries.
- Release events use a closed-vocabulary `kind` (`tags`/`gono`/`ga`/`freeze`/`test`); sprint
  header bullets derive from event titles.
- Jira sprint state (closed/active/future) and metrics are fetched by the refresh pipeline
  and cached on the sprint row; the dashboard renders from that cache.
- Validation (service layer) is strict: unique sprint ids, dates must be working days inside
  `[start, end]`, unknown associates fail with a Levenshtein suggestion.
- The Jira API token is never stored in the DB — keyring (desktop) or `JIRA_API_TOKEN` env
  (container); the DB holds only a `token_ref`.
- Members have optional tenure dates (`start_date`/`end_date`). A sprint shows and
  counts only members whose tenure overlaps it, with capacity prorated for
  mid-sprint joins/leaves. "Departed" (Team page) preserves history; hard delete
  is only for mistaken entries.

## When asked about availability math

Capacity is computed **per sprint** from the members whose tenure overlaps it:
each effective (non-orchestration) member contributes `working_days_per_sprint`
when their tenure covers the whole sprint, else their in-tenure working-day
count (mid-sprint join/departure prorates). With no tenure dates this reduces to
the classic `(len(roster) − len(orchestration)) × working_days_per_sprint`.
Days Out = sum of absent cells from the effective (non-orchestration) members.
Availability = `(Capacity − Days Out) / Capacity × 100`, one decimal (n/a when capacity is 0).
