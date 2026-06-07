# Make Jira optional & decouple sprint identity

**Date:** 2026-06-07
**Branch:** `feature/decouple-jira-optional`
**Status:** approved (design)

## Problem

Sprint Pulse is usable without Jira today (you can add members, sprints, events,
and time-off by hand or via YAML), but Jira assumptions still bleed through the
data model and UI in ways that make pure-manual / mixed use awkward:

1. **The sprint `id` is overloaded.** It is at once the DB primary key, the
   URL/JS-safe identifier (`/sprints/{id}`, `data-sprint`, `show('<id>')`), the
   human-facing label, *and* a fallback Jira-name matching key
   (`"{team_name} {id}"`). Because it must be URL/JS-safe, a natural label like
   `"June 2026"` (with a space) is rejected.
2. **Jira naming bleeds into display.** `render.py` builds each per-sprint header
   as `"{team_name} {id}"` and `Sprint.name` hardcodes `"Wisdom {id}"` — a Jira
   board-naming artifact shown to every user, Jira or not.
3. **Implicit Jira matching.** The refresh pipeline matches sprints to the board
   by the `"{team} {id}"` name prefix as a fallback, and reports an *error* when
   Jira is configured but nothing matches — even though "I have no Jira-linked
   sprints" is a legitimate state.

## Goals

- A sprint has a free-form **label** (e.g. `"June 2026"`) independent of its
  URL/JS-safe key.
- Jira linkage is **explicit and optional**. Unlinked sprints are first-class,
  fully manual. Choosing to use Jira never blocks manual entry.
- Refresh treats "no Jira-linked sprints" as a normal `ok` outcome, not an error.
- Remove hardcoded `"Wisdom"` / team-prefix coupling from sprint display.

## Non-goals (explicitly deferred)

- **Manual / imported tickets & story-points for unlinked sprints.** This is the
  user's planned *next* feature. This design only needs to not block it — and it
  doesn't: refresh writes metrics only to linked sprints, so manual metrics on
  unlinked sprints are never clobbered, and the metric columns already exist.
- Renaming the `Sprint` primary key from `id` to `slug` (cosmetic; a PK + FK
  rename is a much riskier migration for no functional gain).
- A per-sprint Jira-linking UI. Linking stays **import-only** via the existing
  `/sprints/import` flow.

## Design

### 1. Sprint identity: slug (key) vs label (display)

`m.Sprint.id` stays the primary key but becomes a pure **URL/JS-safe slug**,
auto-derived from a new free-form **label**.

- Add column `m.Sprint.label: str`.
- **Migration / backfill:** for existing rows, `label = id`. Existing ids are
  already valid slugs, so the visible result is unchanged.
- **On create:** the user (or YAML) supplies a label; the service slugifies it to
  produce the `id`. Reuse the existing `_slugify` helper in `sprint_service`
  (`re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")`, lowercased).
- **Slug is immutable:** derived once at creation; editing the label later does
  **not** change the slug (keeps `/sprints/{id}`, bookmarks, and `data-sprint`
  attributes stable).
- **Empty-slug guard:** if a label slugifies to an empty string (e.g. all
  punctuation), raise `ValidationError(field="label")`.
- **Collision:** if the derived slug already exists, raise `ValidationError`
  naming the conflicting label (reject rather than auto-suffix — a colliding slug
  means a duplicate label).
- **Validation move:** `_SPRINT_ID_RE` stops validating a user field and instead
  asserts the *derived* slug is well-formed (an internal invariant). The label
  itself is unconstrained beyond non-empty-after-strip.

### 2. Renderer & dataclass

- The frozen `Sprint` dataclass (`sprints.py`) gains a `label: str` field.
- `sprint_service._load` populates `label` from the row (falling back to `id` if
  somehow empty).
- `render.py`:
  - Visible text — per-sprint header and the summary table `<th>` column
    headers — uses `label`.
  - DOM/JS keys — `data-sprint`, `show('<id>')`, the section id map — keep using
    `id` (the slug).
  - Replace the `"{team_name} {id}"` header (line ~23) with just `label`.
- Remove the `Sprint.name` property (`"Wisdom {id}"`); confirm no remaining
  consumers (grep `\.name` on `Sprint`). `cfg.team_name` still titles the page;
  it simply stops prefixing every sprint.

### 3. Jira becomes explicit-link-only

In `services/refresh.py`:

- Match **only** on `row.jira_sprint_id`. Delete the
  `jira_sprints.get(f"{prefix} {row.id}")` name-prefix fallback (line ~54).
- Skip any sprint with `jira_sprint_id is None` (unlinked = manual).
- Status logic:
  - If there are **no linked sprints at all**, return `status="ok"` with a log
    like `"No Jira-linked sprints to update."` (was an error).
  - Keep the genuine error paths: Jira not configured, can't reach the board, or
    a linked sprint's metric fetch failed (stale numbers kept).
- `available_jira_sprints` / `import_jira_sprints` are unaffected except that the
  `suggested_id` it offers is now a *label suggestion* (still slugified on
  import). The import path continues to set `jira_sprint_id`.

### 4. YAML import

In `migrate.py` and the `sprints.py` loader:

- The YAML `id:` field is treated as the **label**; the slug is derived the same
  way as the UI path.
- Drop `_check_id_matches_filename` — the filename no longer needs to equal the
  label/slug.
- Duplicate detection (`_check_duplicate_ids`) runs on **derived slugs**, and the
  error message names the conflicting labels/files.
- One field only (label). An explicit separate `label:` key is YAGNI for now.

## Data flow

```
create/edit (UI or YAML)
  label (free-form)  ──slugify──►  id (slug, PK, immutable)
                     └─store───►  label (display)

dashboard render
  id     ──►  data-sprint / show()        (DOM keys)
  label  ──►  headers / column <th>       (display)

refresh (only when jira_sprint_id set)
  jira_sprint_id ──► board metrics ──► cached columns on row
  unlinked rows: untouched (preserves future manual metrics)
```

## Error handling

| Situation | Behavior |
|---|---|
| Label blank / slugifies to empty | `ValidationError(field="label")` |
| Derived slug already exists | `ValidationError` naming the conflicting label |
| Jira not configured | refresh `status="error"` (unchanged) |
| Jira configured, no linked sprints | refresh `status="ok"`, "nothing to update" |
| Jira configured, can't reach board | refresh `status="error"` (unchanged) |
| Linked sprint metric fetch fails | counted as failure, stale numbers kept (unchanged) |
| YAML duplicate slugs | `SprintError` naming both labels/files |

## Testing

- **slugify/label:** label→slug derivation, lowercasing, punctuation collapse,
  empty-slug rejection, immutability of slug across label edits, collision
  rejection with a clear message.
- **create_sprint:** accepts `"June 2026"`, stores label verbatim, id `"june-2026"`.
- **renderer:** labels appear in headers/`<th>`; `data-sprint`/`show()` use slugs;
  no `"Wisdom"`/team prefix on sprint headers.
- **refresh:** unlinked sprints skipped & untouched; zero-linked → `ok`; linked
  sprint updates as before; metric-failure path still errors.
- **YAML import:** label with spaces imports; filename≠label allowed; duplicate
  slugs rejected; existing example data still imports cleanly.
- **migration:** existing DB rows backfill `label = id`; dashboard unchanged for
  pre-existing data.

## Migration notes

The project has no Alembic; `db/engine.py` evolves schema via the
`_ADDED_COLUMNS` dict + `_ensure_columns` (idempotent `ALTER TABLE ... ADD
COLUMN`), called from `create_db_and_tables`.

- Add `("label", "VARCHAR DEFAULT ''")` to `_ADDED_COLUMNS["sprint"]`.
- `_ensure_columns` only adds the column with its literal default; it does **not**
  copy from another column. So add a one-time **backfill** step (idempotent):
  `UPDATE sprint SET label = id WHERE label IS NULL OR label = ''`, run after the
  ALTER. Place it alongside the existing migration helpers in `engine.py` (it is
  naturally idempotent — once labels are set it matches nothing).
- No PK/FK changes, so `Event.sprint_id` and all existing references are intact.
