# Sprint Pulse ⚡

[![tests](https://github.com/omaciel/sprint-pulse/actions/workflows/test.yml/badge.svg)](https://github.com/omaciel/sprint-pulse/actions/workflows/test.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A team availability dashboard you can **install**. Sprint Pulse combines team
time-off tracking, live Jira sprint metrics (tickets done/total, story points
done/total), and release-calendar events into a single availability heatmap.

It's a **FastAPI + SQLite** app that runs three ways from one codebase:

- **Desktop app** — a native window (pywebview) on macOS and Linux. 100% Python.
- **Local web app** — the same app in your browser (great for development).
- **Containerized web app** — browse to it from anywhere; data on a volume.

First run walks you through a setup wizard (settings → import sprints → team), or
you can import existing `data/*.yaml` in one click. Metrics refresh on a schedule
you control.

## What it shows

- Sprint navigator with state badges (active / future / closed)
- One sprint heatmap at a time — team members × working days
- Cell vocabulary: PTO, regional holidays, company holidays, partial availability,
  tentative, and "on Orchestration" carve-outs
- Release-event row (git tags, Go/No-Go, GA, freeze, testathon)
- Per-sprint availability % and a per-associate summary

Time off is managed **per person**: open **Team → a name** for that member's
availability **calendar** — pick a type (PTO / holiday / company / partial /
tentative) and click weekdays to mark or clear them. Sprints derive their own
"who's out" list automatically from those dates, so editing a sprint is just its
dates and release events.

## Requirements

- **Python 3.13+**
- Dependencies declared in `pyproject.toml` and locked in `uv.lock` (FastAPI,
  SQLModel, Jinja2, APScheduler, pywebview, …), managed with
  [uv](https://docs.astral.sh/uv/). The desktop shell + packaging deps live in
  the optional `desktop` extra; Linux desktop also needs the **WebKitGTK** system
  package (`gir1.2-webkit2-4.1` / `webkit2gtk`). The container path needs neither.
- A Jira API token with read access to your Scrum board (for live metrics).

## Setup

`uv sync` creates the `.venv` and installs dependencies from the lockfile:

```bash
uv sync --extra desktop   # runtime + desktop + dev deps (use `make install-dev`)
```

> The `make` targets **auto-detect `.venv/`** — if it exists they use
> `.venv/bin/python` automatically, so you don't have to activate it. Override
> with `make <target> PYTHON=/path/to/python` if you keep the venv elsewhere.
> `make install` installs runtime + desktop only; `make install-dev` adds the
> test/lint tooling.

## Ways to run

### 1. Desktop app (native window)

```bash
make dev-desktop
```

Opens a native window (WebKit). Uses your local database (see *Where your data
lives*). The Jira token is stored in your OS keychain.

### 2. Local web app (browser)

```bash
make dev                      # http://localhost:8765  (auto-reloads on edits)
```

Change the port with `PORT=9000 make dev`.

### 3. Containerized web app (browser)

```bash
make container-build          # build the image (podman)
make container-run            # run it; http://localhost:8765

# …or run it directly with podman or docker:
podman run -p 8765:8765 -v sprint-pulse-data:/data \
  -e JIRA_USERNAME=you@example.com -e JIRA_API_TOKEN=xxxx sprint-pulse
docker  run -p 8765:8765 -v sprint-pulse-data:/data \
  -e JIRA_USERNAME=you@example.com -e JIRA_API_TOKEN=xxxx sprint-pulse
```

The DB lives on the `/data` volume and survives restarts. In the container the
Jira token comes from `JIRA_API_TOKEN` (the DB only ever stores a reference, never
the token). Override the published port with `PORT=9000 make container-run`.

### 4. Run the server directly (advanced)

The web app is a standard ASGI module — handy for a custom host/port/DB:

```bash
SPRINT_PULSE_HOST=0.0.0.0 SPRINT_PULSE_PORT=9000 \
SPRINT_PULSE_DB=/path/to/my.db \
python -m sprint_pulse.web
```

### 5. Demo mode — no live Jira needed

Try the whole app offline with fictional example data and a **mocked Jira**:

```bash
make demo            # browser at http://localhost:8765  (fresh throwaway DB)
make demo-desktop    # same, in the native window
```

This starts a fresh `.demo.db`, points the wizard's YAML import at `examples/`,
and sets `SPRINT_PULSE_DEMO=1` so the Jira features use canned data instead of a
real instance. From the wizard you can:

- **Import manually** — "Import from YAML" loads the example team + sprints.
- **Import automatically** — "Import from Jira" lists mock board sprints to pick
  from, and "Test connection" / "Refresh metrics now" return mock data.

No credentials or VPN required. Delete `.demo.db` to start over (`make demo`
does this for you each run).

### 6. Build a distributable desktop app

```bash
make build-desktop            # PyInstaller bundle
# → dist/SprintPulse.app (macOS) / dist/SprintPulse/ (Linux)
```

On first launch the bundle shows the setup wizard and writes to the same default
database location as the dev app.

## Where your data lives

Everything — your roster, sprints, time off, **and** configuration (team name,
working days, Jira site/board/username, scheduler settings) — lives in a single
**SQLite file**. The Jira API token is *not* in it (keychain on desktop,
`JIRA_API_TOKEN` in the container).

**Resolution order** (first match wins):

1. **`SPRINT_PULSE_DB`** — an exact path you set. Always wins.
   ```bash
   SPRINT_PULSE_DB=/path/to/team.db make dev
   ```
2. **`XDG_DATA_HOME`** — if set, uses `$XDG_DATA_HOME/sprint-pulse/sprint-pulse.db`
   (honored on every OS, including macOS).
3. **Otherwise, search then create** — look for an existing DB in the XDG default
   first, then the OS-native location, and use whichever exists. If neither
   exists, create one at the XDG-default path:

   | OS | XDG-default (checked first) | OS-native (checked next) |
   |----|------------------------------|--------------------------|
   | macOS | `~/.local/share/sprint-pulse/sprint-pulse.db` | `~/Library/Application Support/sprint-pulse/sprint-pulse.db` |
   | Linux | `~/.local/share/sprint-pulse/sprint-pulse.db` | (same as XDG-default) |
   | Windows | `~/.local/share/sprint-pulse/sprint-pulse.db` | `%APPDATA%\sprint-pulse\sprint-pulse.db` |
   | Container | `/data/sprint-pulse.db` (set via `SPRINT_PULSE_DB`) | — |

Symlinks are followed, so you can keep the real file anywhere (e.g. in a dotfiles
repo) and symlink it into the location above.

**See the resolved path any time:**

```bash
make db-path
# → /Users/you/.local/share/sprint-pulse/sprint-pulse.db
```

## Importing existing YAML

Have a `config.yaml` + `sprints/*.yaml` directory (the bundled `examples/`, or your
own)? Import it once:

```bash
python migrate_yaml_to_sqlite.py --data examples            # import the samples
python migrate_yaml_to_sqlite.py --data /path/to/mine       # your own dir
python migrate_yaml_to_sqlite.py --data examples --db /tmp/x.db   # to a specific DB
python migrate_yaml_to_sqlite.py --data examples --force    # overwrite a populated DB
# …or click "Import from YAML" in the first-run wizard (set SPRINT_PULSE_SEED_DIR)
```

After import, SQLite is the source of truth — the YAML is no longer edited. Your own
team data is yours to keep outside the repo; only the fictional `examples/` ship here.

## Environment variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `SPRINT_PULSE_DB` | all | Exact path to the SQLite file (highest priority). |
| `XDG_DATA_HOME` | all | If set, data lives under `$XDG_DATA_HOME/sprint-pulse/`. |
| `SPRINT_PULSE_HOST` | web/container | Bind address (default `127.0.0.1`; container sets `0.0.0.0`). |
| `SPRINT_PULSE_PORT` | web/container | Port (default `8765`). |
| `SPRINT_PULSE_HEADLESS` | container | `1` → use the env token backend, not the keychain. |
| `JIRA_USERNAME` | container/headless | Jira account email (desktop sets this in the UI). |
| `JIRA_API_TOKEN` | container/headless | Jira API token (desktop stores it in the keychain instead). |
| `JIRA_API_TOKEN_FILE` | container/headless | Path to a file containing the token (alternative to `JIRA_API_TOKEN`). |
| `SPRINT_PULSE_DEMO` | all | `1` → use mocked Jira data (no live instance/creds). See *Demo mode*. |
| `SPRINT_PULSE_SEED_DIR` | wizard | YAML dir for "Import from YAML" (default `data/`; demo uses `examples/`). |

## Layout

```
sprint-pulse/
├── sprint_pulse/
│   ├── config.py sprints.py jira.py render.py   # domain core (reused)
│   ├── db/          # SQLModel models + engine (DB path resolution)
│   ├── services/    # validated reads/writes, secrets, refresh pipeline
│   ├── web/         # FastAPI app, routers, Jinja2 + HTMX templates, scheduler
│   └── desktop.py   # pywebview shell
├── migrate_yaml_to_sqlite.py   # one-time YAML → SQLite import
├── Containerfile               # browser deployment
├── packaging/sprint_pulse.spec # desktop bundle (PyInstaller)
├── examples/                   # fictional sample data for demos (make demo)
├── tests/                      # pytest suite
└── .claude/skills/             # maintain-time-off-report, refresh-sprint-metrics
```

## Development

```bash
make test     # pytest
make lint     # ruff
make help     # list every target
```

## Working with Claude Code

Two project-scoped skills auto-load in `.claude/skills/`:

- **maintain-time-off-report** — data model, validation, and how to edit via the app
- **refresh-sprint-metrics** — refreshing Jira metrics via the scheduler

Describe what you want in plain language ("add PTO for Alice on May 7", "refresh the
metrics") and the matching skill kicks in.
