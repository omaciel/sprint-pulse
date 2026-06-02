# YAML Data Refactor — Design

**Date:** 2026-05-14
**Status:** Approved
**Author:** Og Maciel (with Claude)

## 1. Context & Motivation

The sprint-pulse generator currently mixes data and code:

- **Hardcoded in `build_report.py`:** `RELEASE_EVENTS`, `SPRINT_NOTES`, `ROSTER`, `ORCHESTRATION`, `NAME_ALIASES`, `WORKING_DAYS_PER_SPRINT`, `JIRA_SITE`, `BOARD`.
- **In `data/time-off.md`:** sprint sections with absence tables, in a custom markdown schema.

Adding a new sprint or shifting a release date requires editing Python source and counting working-day column indices by hand. The goal is to externalize all data into YAML so non-developers (or future-Claude) can update the dashboard without touching code.

## 2. File Layout & Schemas

### 2.1 Directory structure

```
data/
  config.yaml              # team + integration config (rarely changes)
  sprints/
    2026-16.yaml           # one file per sprint
    2026-18.yaml
    2026-20.yaml
    2026-22.yaml
    2026-24.yaml
    2026-26.yaml
    archive/               # archived sprints (ignored by the generator)
      2025-50.yaml
```

### 2.2 `data/config.yaml`

```yaml
working_days_per_sprint: 10

jira:
  site: example.atlassian.net
  board: "1234"

# Display order for heatmap rows (top to bottom)
roster:
  - Alice Anderson
  - Bruno Costa
  - Mei Lin
  - Hassan Ibrahim
  - Elena Fischer
  - Frank Garcia
  - Grace Hughes
  - Ines Jensen
  - Dmitri Egorov
  - Carol Diaz
  - Jack Kelly

# Excluded from Wisdom availability (gray cells, 0 capacity contribution)
orchestration:
  - Grace Hughes
  - Hassan Ibrahim

# Free-text alias → canonical roster name
name_aliases:
  Alyce Anderson: Alice Anderson
  Carole Diaz: Carol Diaz
  Dima Egorov: Dmitri Egorov
  Gracie Hughes: Grace Hughes
```

### 2.3 `data/sprints/2026-NN.yaml`

```yaml
id: 2026-16
start: 2026-04-16
end: 2026-04-29

events:
  - {date: 2026-04-17, kind: gono, title: Go/No-Go deadline 4PM EST}
  - {date: 2026-04-22, kind: ga,   title: AAP 2.7 GA release}
  - {date: 2026-04-22, kind: test, title: Testathon Day 1}
  - {date: 2026-04-23, kind: test, title: Testathon Day 2}

time_off:
  - associate: Alice Anderson
    days: [2026-04-24]
    notes: PTO
  - associate: Carol Diaz
    days: [2026-04-24]
    notes: PTO
  - associate: Dmitri Egorov
    days: [2026-04-27, 2026-04-28, 2026-04-29]
    notes: PTO
```

### 2.4 Vocabulary

- **Event kinds (closed set):** `tags`, `gono`, `ga`, `freeze`, `test`. Anything else fails validation.
- **Type inference for time-off** is unchanged from the current markdown logic and runs on the YAML `notes` field:
  - Contains `company` → company holiday (purple `C`)
  - Contains `partial` → partial availability (yellow `~`)
  - Contains `tentative` → tentative (yellow striped `?`)
  - Contains a holiday keyword (`holiday`, `Memorial Day`, `Pentecost`, `Liberation`, etc.) → holiday (blue `H`)
  - Otherwise → PTO (red `P`)
- **`__all__` shorthand** for company-wide entries:
  ```yaml
  - associate: __all__
    days: [2026-05-22]
    notes: Company holiday
  ```
  Expands to one entry per roster member at load time.
- **Sprint header bullets** are auto-derived from `events` — no separate `notes` field. Format: `<title> — <Mmm DD>` per event, in event order.
- **Archiving** = move the sprint file to `data/sprints/archive/`. The generator ignores anything under `archive/`. No marker comments needed.

## 3. Validation & Error Handling

The generator loads all YAML files at startup, validates everything strictly, and fails fast with a clear error message on the first problem. No partial renders.

### 3.1 Per-sprint-file checks

| Check | Failure message example |
| --- | --- |
| Filename matches `id` | `sprints/2026-16.yaml: id "2026-17" does not match filename` |
| `start` / `end` are valid ISO dates, `end >= start` | `sprints/2026-16.yaml: end (2026-04-15) is before start (2026-04-16)` |
| Sprint length is 14 days | Warning (not error) if `end - start + 1 ≠ 14`. Supports irregular sprints if ever needed. |
| No duplicate sprint ids across files | `Duplicate sprint id 2026-16 in 2026-16.yaml and 2026-16-copy.yaml` |

### 3.2 Event checks

| Check | Failure message example |
| --- | --- |
| `kind` ∈ {tags, gono, ga, freeze, test} | `event 0: unknown kind "release" (expected tags/gono/ga/freeze/test)` |
| `date` is a working day (Mon–Fri) | `event 0: date 2026-04-18 is a Saturday` |
| `date` falls within `[start, end]` | `event 0: date 2026-05-01 is outside sprint range Apr 16–Apr 29` |
| `title` non-empty | `event 0: missing title` |

### 3.3 Time-off checks

| Check | Failure message example |
| --- | --- |
| `associate` is in roster OR is `__all__` | `time_off 2: unknown associate "Alice Andersen" (typo? did you mean "Alice Anderson"?)` (Levenshtein-based suggestion) |
| Each day in `days` is a working day | `time_off 2: 2026-04-25 is a Saturday` |
| Each day falls within `[start, end]` | `time_off 2: 2026-05-01 is outside sprint range` |
| `days` is non-empty | `time_off 2: empty days list` |

### 3.4 Config checks

| Check | Failure message example |
| --- | --- |
| `orchestration` ⊆ `roster` | `config.yaml: orchestration member "X" not in roster` |
| `name_aliases` values ⊆ `roster` | `config.yaml: alias target "X" not in roster` |
| No duplicate names in `roster` | `config.yaml: duplicate roster entry "X"` |

### 3.5 Jira / network failures

Unchanged. Graceful fallback to zeros with a stderr warning when the Jira API is unreachable; report still renders with availability data.

## 4. Code Structure

Split the current monolithic `build_report.py` into a small package:

```
build_report.py                 # CLI entry point + orchestration (~100 lines)
sprint_pulse/
  __init__.py
  config.py                     # config.yaml loader + Config dataclass + validation
  sprints.py                    # sprint YAML loader + Sprint/Event/TimeOff dataclasses + validation
  jira.py                       # JiraClient class + retry/timeout
  render.py                     # HTML rendering (CSS, legend, sprint sections, summary)
```

Each module:
- Has one clear purpose
- Stays under ~250 lines
- Is testable in isolation
- Imports from `sprint_pulse.config` for shared types

**Dependency added:** `PyYAML`. Captured in a new `requirements.txt`.

## 5. Migration & Cutover

### 5.1 Approach

One-shot migration script + verification diff. The verification gate guarantees byte-identical (modulo whitespace) HTML output before we delete the old data sources.

### 5.2 Steps

1. Build the new code (Sections 2–4) on a feature branch.
2. Write a temporary `migrate.py` that reads the existing `data/time-off.md` + the constants in `build_report.py`, emits `data/config.yaml` and one `data/sprints/2026-NN.yaml` per sprint.
3. **Verification gate:** run both old and new generators with `--skip-jira`, diff the two `report.html` outputs. Must match before cutover.
4. Delete `data/time-off.md`, the constant blocks in `build_report.py`, and `migrate.py`.
5. Update the project skills (`maintain-time-off-report`, `refresh-sprint-metrics`) to document the YAML schema instead of the markdown schema.
6. Update `CLAUDE.md` and `README.md`.

### 5.3 Commit sequence

| # | Contents |
| --- | --- |
| 1 | Add `requirements.txt` with PyYAML |
| 2 | Add `sprint_pulse/` package skeleton (empty stubs) |
| 3 | Implement `sprint_pulse/config.py` + tests |
| 4 | Implement `sprint_pulse/sprints.py` + tests |
| 5 | Extract Jira logic into `sprint_pulse/jira.py` + tests |
| 6 | Extract rendering into `sprint_pulse/render.py` + tests |
| 7 | Wire `build_report.py` to use the new package (still reads markdown) |
| 8 | Add `migrate.py`, run it, commit generated YAML files |
| 9 | (verification gate — no commit; diff old vs. new HTML; must be empty before proceeding) |
| 10 | Delete markdown, hardcoded constants, `migrate.py` |
| 11 | Update skills + `CLAUDE.md` + `README.md` |

Each commit is small and reversible — the branch is bisectable if anything breaks.

## 6. Testing

### 6.1 Framework

- `pytest` for the runner
- `pytest-snapshot` (or equivalent) for HTML golden-file tests

Both pure-Python, no system deps. Captured in `requirements-dev.txt`.

### 6.2 Layout

```
tests/
  __init__.py
  conftest.py                   # shared fixtures
  test_config.py                # config.yaml loading + validation
  test_sprints.py               # sprint YAML + every validation rule
  test_render.py                # HTML rendering snapshot tests
  test_jira.py                  # JiraClient with mocked urlopen
  test_integration.py           # load real data/ files; assert no validation errors
  fixtures/
    valid/
      config.yaml
      sprint-minimal.yaml
      sprint-full.yaml          # events + time-off + __all__ row
    invalid/
      config-orch-not-in-roster.yaml
      sprint-event-outside-range.yaml
      sprint-unknown-kind.yaml
      sprint-unknown-associate.yaml
      sprint-saturday-event.yaml
      ...                        # one fixture per validation rule
    snapshots/                   # golden HTML output
```

### 6.3 Style

- **Validation tests** — parametrized: each invalid fixture loads and asserts the specific error substring.
- **Render tests** — feed a small fixed sprint into `render_sprint()` with stubbed Jira metrics; snapshot the HTML output.
- **Jira tests** — patch `urllib.request.urlopen`; verify retry, timeout, parsing.
- **Integration smoke test** — load every YAML file under `data/`, assert success. Catches real bad data the moment a YAML file is saved.

### 6.4 Coverage

Not enforced numerically. Standard: every validation rule has a test; render output has a snapshot. Untested rules don't really exist.

### 6.5 Running

`pytest` from the project root. Minimal `pyproject.toml` or `pytest.ini` to set test paths.

## 7. CI

Add a GitHub Actions workflow at `.github/workflows/test.yml` that:

- Triggers on `push` and `pull_request`
- Sets up Python 3.11+
- Installs `requirements.txt` + `requirements-dev.txt`
- Runs `pytest`

The workflow file is committed now and will start running once the user pushes the repo to GitHub. No effect locally until then.

## 8. Out of Scope

The following are deliberately **not** part of this refactor:

- Database backing for time-off data (file-based YAML is the goal).
- Multi-team support — config is single-team.
- Automated sprint creation from Jira (sprints are still defined by editing YAML).
- Web UI for editing data.
- Backwards compatibility with the markdown format after cutover. Step 5.2.4 deletes the markdown.
