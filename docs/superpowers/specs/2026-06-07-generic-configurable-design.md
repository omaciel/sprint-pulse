# Make Sprint Pulse generic & configurable

**Date:** 2026-06-07
**Status:** approved (design)

## Problem

Sprint Pulse is hard-coded to one operator's context (the "Wisdom" AAP team) and
to two fixed vocabularies:

1. The default team name is `"Wisdom"` and the release row/legend is labelled
   `"AAP release"` — both bake one team's identity into the tool.
2. **Event kinds** (`tags/gono/ga/freeze/test`) and **absence types**
   (`pto/holiday/company/partial/tentative`) are closed tuples whose letters,
   colors, CSS, legend text, validators, and (for absences) keyword inference and
   priority are hard-coded across `render.py`, `sprints.py`,
   `services/time_off_service.py`, and `db/engine.py`. A user cannot add,
   rename, recolor, or remove a type.
3. The word **"orchestration"** (for teammates excluded from capacity) is jargon;
   a clearer, generic word is wanted.

## Goals

- Generic defaults so anyone can use the tool unmodified.
- User-managed (CRUD) event types and absence types with a sensible default set.
- Clearer terminology for capacity-excluded members.

## Decisions (locked during brainstorming, 2026-06-07)

- Excluded-member term: **"Excluded"** (from capacity).
- Type colors: a **fixed palette** (pick from curated swatches).
- Deleting a type that is **in use**: **blocked** with a clear count message.
- The `"AAP release"` label becomes a fixed generic **"Releases"**.
- Default team name becomes a generic **"My Team"**.
- The single shared "events" row model is kept (all event types render as letters
  in one row).
- **No general-purpose DB rename migration.** Code uses `is_excluded` directly;
  the operator's existing DB is migrated once as the final implementation step
  (this is a single-user tool today).

## Non-goals

- Per-type "counts as a day out" weighting — every absence type counts as one day
  out, as today. (Capacity exclusion is handled separately, per-member.)
- Adopting Alembic. The schema changes here are additive (new tables) plus one
  one-time operator-DB rename; the existing hand-rolled approach suffices.
- Preserving the `"tentative"` diagonal-stripe pattern — with a solid-color
  palette it becomes a solid color (accepted minor visual change).

---

## Part A — De-personalize branding (Parts 1 + 3)

**Default team name → `"My Team"`.** Replace the `"Wisdom"` literal as a *default*
in: `db/models.py` (`Settings.team_name`), `db/engine.py` (`_ADDED_COLUMNS`
default), `config.py` (dataclass default + YAML fallback),
`services/config_service.py` (hydration + update fallbacks),
`services/jira_service.py` + `services/mock_jira.py` (mock default),
`services/refresh.py` + `services/sprint_service.py` (Jira prefix fallback),
`web/routers/config_page.py` + `web/routers/setup.py` (form defaults), and
templates `config.html`, `setup/wizard.html`. Existing stored values are
untouched (only the default for new installs changes).

**`"AAP release"` → `"Releases"`.** In `render.py` the legend group label
(`:163`) and the release-row name cell (`:242`) become `"Releases"`. Sample event
titles using `"AAP 2.7 GA release"` become a neutral `"2.7 GA release"`
(fixtures, snapshots, tests).

---

## Part B — Rename "orchestration" → "Excluded" (Part 4)

**Code (clean, no back-compat shim):**

- DB column `TeamMember.is_orchestration` → `is_excluded` (model edited directly).
- `Config.orchestration` (set) → `Config.excluded`; `Config.effective` keeps its
  meaning (roster minus excluded). YAML validation message updated.
- YAML key `orchestration:` → `excluded:` (no old-key fallback).
- `services/config_service.py`: `toggle_orchestration` → `toggle_excluded`;
  `add_member(..., is_orchestration=...)` → `is_excluded`; the build that derives
  the set from members.
- `migrate.py`: `is_excluded=name in cfg.excluded`; counts key `excluded`.
- Renderer: CSS class `external` → `excluded` (swatch, `td.excluded`,
  `tr.excluded-row`); `_render_cell` and the summary use `cfg.excluded`; legend
  text "On Orchestration (not counted)" → "Excluded (not counted)".
- Routers/forms: form field `is_orchestration` → `is_excluded`.
- Templates: all user-facing strings → "Excluded from capacity"; toggle button
  "Make orchestration"/"Make capacity" → "Exclude"/"Include"; pill
  "Orchestration" → "Excluded"; subtitles on `members.html`, `setup/team.html`,
  `member_detail.html`, `partials/_members_table.html`,
  `partials/_setup_members.html`.

**Fresh installs:** `create_all` builds `teammember` with `is_excluded` — no
migration needed.

**Operator DB migration (final step, see Part D).** The existing DB has the old
column; it is renamed once, out of band.

---

## Part C — CRUD event & absence types (Part 2)

### Data model (new tables — additive)

Two tables, symmetric:

```
EventType:   key (PK, slug), label, abbreviation, color, sort_order
AbsenceType: key (PK, slug), label, abbreviation, color, sort_order
```

- `key` — CSS/JS-safe slug derived from `label` via the existing
  `sprint_pulse.sprints.slugify` (consistent with sprint slugs). Used as the CSS
  class and `Event.kind` / `MemberDayOff.type` value.
- `label` — free-form display name.
- `abbreviation` — 1–2 chars shown in calendar/release cells (e.g. "P", "~").
- `color` — a hex string, constrained to the fixed palette.
- `sort_order` — integer for legend/column ordering.

`Event.kind` and `MemberDayOff.type` stay as string columns holding a type `key`
(unchanged columns; existing values already match the seeded default keys).

### Fixed palette

A module constant (e.g. `sprint_pulse/types_defaults.py`):

```
PALETTE = [
    # includes every color used by the default seed below, plus extras
    "#fca5a5", "#ef4444", "#b45309", "#f59e0b", "#fcd34d",
    "#10b981", "#047857", "#3b82f6", "#93c5fd", "#1d4ed8",
    "#8b5cf6", "#7c3aed", "#c4b5fd", "#ec4899", "#14b8a6",
    "#6b7280", "#cbd5e1",
]
```

The exact list may be refined in implementation, but it MUST contain every color
the default seed uses (it does, above). Type color must be one of `PALETTE`.

### Default seed (preserves current look)

The same module defines the default sets, seeded into the tables when empty
(idempotent — only seeds an empty table, so a user who deletes a default keeps it
gone). Default keys/letters/colors match today's hard-coded values so existing
`Event.kind` / `MemberDayOff.type` rows render unchanged. Labels should match the
current legend text (read `render.py` to copy them exactly):

- Event types: `tags`(T,#1d4ed8), `gono`(G,#b45309), `ga`(R,#047857),
  `freeze`(F,#6b7280), `test`(X,#7c3aed).
- Absence types: `pto`(P,#fca5a5), `holiday`(H,#93c5fd), `company`(C,#c4b5fd),
  `partial`(~,#fcd34d), `tentative`(?, a solid palette color, e.g. #cbd5e1).

All of the above colors are present in `PALETTE`, so the seed validates. Confirm
the exact default labels (legend text) and letters by reading `render.py`'s
current `KIND_LETTERS`/`TYPE_LETTERS`/legend before seeding.

### Services

- New `services/type_service.py` (CRUD for both tables): `list_event_types`,
  `list_absence_types`, `create_*`, `rename_*`/`update_*` (label/abbr/color),
  `delete_*` (blocked when in use — counts `Event`/`MemberDayOff` rows by key),
  validation (label required → non-empty slug; slug uniqueness; color ∈ PALETTE;
  abbreviation 1–2 chars). Reuse the sprint slug/label validation idiom.
- `seed_default_types(session)` — idempotent, called from `create_db_and_tables`.
- Validators move DB-ward: `sprint_service.add_event` validates `kind` against
  `EventType` keys in the DB; `time_off_service.set_days` validates `type` against
  `AbsenceType` keys in the DB (replacing the `VALID_TYPES` tuple check).

### Config hydration + renderer (data-driven)

- `Config` gains `event_types` and `absence_types` — tuples of small frozen
  records (`key, label, abbreviation, color, sort_order`).
  `config_service.build_config_from_db` populates them.
- `render.py` stops hard-coding `KIND_LETTERS`, `TYPE_LETTERS`, `TYPE_TITLES` and
  the per-type CSS/legend. Instead it **generates**, from the Config type lists:
  - the per-type CSS rules (`td.<key>`, `.swatch.<key>`, `td.release.<key>`,
    color vars) — injected into the `<style>` block;
  - the letter map (`key → abbreviation`) for cells;
  - the legend entries (label + swatch), ordered by `sort_order`.
- Cell/render lookups use `key` (already CSS-safe) for the class and the type
  record for the letter/label/title. A record missing from the map (shouldn't
  happen post-seed) falls back to a neutral class/letter so a stray key never
  crashes the renderer.

### YAML import

- The pure loader (`sprints.py`) validates event kinds and infers absence types
  against the **default seed keys** (a shared constant), since YAML import targets
  the default vocabulary. `infer_type` (keyword→key) stays for convenience and
  maps to default keys. Custom types are added via the UI after import.
- `_validate_event` / `event_kind_error` use the default-key set rather than the
  old `EVENT_KINDS` tuple (renamed/repointed to the shared constant).

### Management UI

Two CRUD sections — "Event Types" and "Absence Types" — on a settings surface
(extend the Config page, or a dedicated `/types` page; implementer's choice
following existing router/template patterns). Each lists current types (swatch +
label + abbreviation) with add / edit (label, abbreviation, palette color) /
delete. Delete is blocked while in use, showing the usage count. Forms post to a
`types` router; errors re-render with a message via the existing `ValidationError`
→ `e.display()` pattern.

---

## Part D — Operator DB migration (final step)

After all code + sample-data changes land and the suite is green, migrate the
operator's existing database **once**:

1. Resolve the live DB path via `sprint_pulse.db.engine.default_db_path()`
   (honors `SPRINT_PULSE_DB` / XDG / macOS native).
2. **Back it up** (copy to `<db>.bak-YYYYMMDD`).
3. `ALTER TABLE teammember RENAME COLUMN is_orchestration TO is_excluded;`
   (SQLite ≥ 3.25; verify the column exists first to stay idempotent).
4. Boot the app once (or call `create_db_and_tables`) so the new `EventType` /
   `AbsenceType` tables are created and seeded; existing `kind`/`type` values map
   to the seeded defaults automatically.
5. Verify: app starts, dashboard renders, members show the "Excluded" pill where
   they previously showed "Orchestration", types appear in the legend.

This is a one-time operator action, not shipped migration code.

---

## Data flow

```
labels/colors (UI or default seed)
  EventType/AbsenceType rows ──► build_config_from_db ──► Config.event_types/absence_types (frozen)
                                                          │
  Event.kind / MemberDayOff.type (= a type key) ─────────┘
                                                          ▼
                                   render.py: generate CSS + letters + legend from the type lists
                                              cells use key (CSS class) + record (letter/label/title)

excluded members:  TeamMember.is_excluded ──► Config.excluded ──► renderer gray rows, capacity math
```

## Error handling

| Situation | Behavior |
|---|---|
| Type label blank / slugifies empty | `ValidationError(field="label")` |
| Duplicate type key (slug) | `ValidationError` naming the conflict |
| Color not in PALETTE | `ValidationError(field="color")` |
| Abbreviation empty or >2 chars | `ValidationError(field="abbreviation")` |
| Delete type still in use | refused; message with usage count |
| Event/absence references a missing key (shouldn't occur) | renderer falls back to neutral class/letter |
| YAML event kind / inferred absence type not in default set | `SprintError` (loader), as today |

## Testing

- **Branding:** default team name is "My Team" (fresh DB); existing value
  preserved; "Releases" appears (not "AAP release"); no "AAP"/"Wisdom" literals
  leak into rendered output for a generic config.
- **Excluded rename:** model has `is_excluded`; `Config.excluded` populated;
  renderer gray rows + capacity math unchanged; `toggle_excluded` flips it; UI
  strings say "Excluded"; YAML `excluded:` key imports.
- **Type CRUD:** create (label→slug key), rename/recolor/abbr edit, color∈palette
  enforced, duplicate-slug rejected, delete-blocked-while-in-use (with count),
  delete-allowed-when-unused.
- **Seed:** defaults seeded on empty tables, idempotent (no dupes on re-run; a
  deleted default stays gone); default keys/letters/colors match prior look.
- **Renderer data-driven:** CSS/letters/legend generated from Config type lists;
  a custom type renders with its palette color + abbreviation; snapshot updated.
- **Validators:** `add_event`/`set_days` accept DB-defined types incl. a custom
  one; reject unknown keys.
- **YAML import:** existing example data imports against default keys; `infer_type`
  still maps notes→default keys.
- **Operator migration (Part D):** a script/checklisted run; verified manually
  (not a shipped test), but include a unit test that `create_db_and_tables` on a
  DB whose `teammember` already has `is_excluded` is a no-op and seeds types.

## Migration / schema notes

- New tables via `SQLModel.metadata.create_all` (additive). `seed_default_types`
  wired into `create_db_and_tables` after table creation, before returning;
  idempotent (seeds only empty tables).
- No `_ADDED_COLUMNS` entries needed (no new columns on existing tables; the
  `is_excluded` rename is handled out-of-band per Part D for the operator DB, and
  via `create_all` for fresh installs).
- Phased plan: **A (branding) → B (excluded rename) → C (CRUD types) → D
  (operator DB migration)**, each phase green before the next.
