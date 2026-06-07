"""Sprint/event/time-off reads + validated mutators over the DB.

Validation reuses the shared field validators in ``sprint_pulse.sprints``
(``working_day_error``, ``event_kind_error``) so the DB path enforces exactly
the same rules the YAML loader always did.
"""
from __future__ import annotations

import re
import warnings
from datetime import date

from sqlmodel import Session, select

from sprint_pulse.config import Config
from sprint_pulse.db import models as m
from sprint_pulse.errors import ValidationError
from sprint_pulse.jira import JiraUnavailable
from sprint_pulse.services import config_service, jira_service, time_off_service
from sprint_pulse.sprints import (
    Event,
    Sprint,
    event_kind_error,
    working_day_error,
)


def sort_key(sprint) -> tuple:
    """Chronological order key: (start, end, id). Works for Sprint dataclasses
    and m.Sprint rows alike, so sprint ordering no longer depends on the id's
    format."""
    return (sprint.start, sprint.end, sprint.id)


def _group(items, key):
    out: dict = {}
    for item in items:
        out.setdefault(key(item), []).append(item)
    return out


def _load(session: Session, cfg: Config | None):
    """Bulk-load everything for the dashboard in a fixed number of queries
    (no per-sprint / per-entry N+1). Returns (sprints_sorted, rows_by_id)."""
    if cfg is None:
        cfg = config_service.build_config_from_db(session)
    member_name = {member.id: member.name for member in config_service.list_members(session)}

    rows = list(session.exec(select(m.Sprint)).all())
    events_by_sprint = _group(session.exec(select(m.Event)).all(), lambda e: e.sprint_id)
    dayoff_rows = list(session.exec(select(m.MemberDayOff)).all())

    sprints: list[Sprint] = []
    for row in rows:
        events = tuple(
            Event(date=e.date, kind=e.kind, title=e.title)
            for e in sorted(events_by_sprint.get(row.id, []), key=lambda e: e.date)
        )
        time_off = tuple(
            time_off_service.entries_for_sprints(dayoff_rows, member_name, row.start, row.end)
        )
        sprints.append(
            Sprint(id=row.id, start=row.start, end=row.end, events=events, time_off=time_off)
        )
    sprints.sort(key=sort_key)
    return sprints, {row.id: row for row in rows}


def build_sprints_from_db(session: Session, cfg: Config | None = None) -> list[Sprint]:
    """Hydrate frozen :class:`Sprint` dataclasses (for the renderer)."""
    sprints, _ = _load(session, cfg)
    return sprints


def build_dashboard_data(
    session: Session, cfg: Config | None = None
) -> list[tuple[Sprint, dict, str]]:
    """``(sprint, jira_metrics, jira_state)`` tuples for ``render_full_html``.

    Metrics come straight from the cached columns on the Sprint row (refreshed
    by the scheduler), so the dashboard renders with no live Jira call.
    """
    sprints, rows = _load(session, cfg)
    out: list[tuple[Sprint, dict, str]] = []
    for sp in sprints:
        row = rows[sp.id]
        if row.archived:  # archived sprints drop off the dashboard
            continue
        metrics = {
            "done_n": row.done_n,
            "tot_n": row.tot_n,
            "done_sp": row.done_sp,
            "tot_sp": row.tot_sp,
        }
        out.append((sp, metrics, row.jira_state))
    return out


# --- Sprint CRUD ------------------------------------------------------------

# Sprints are now ordered by date, so the id is just a stable, human label. It
# still must be URL- and JS-safe (it appears in /sprints/{id}, data-sprint
# attributes, and a show('<id>') call): letters/digits to start, then
# letters/digits/dot/underscore/hyphen. No spaces, quotes, or slashes.
_SPRINT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def slugify_label(label: str) -> str:
    """URL/JS-safe slug from a free-form label: 'June 2026' -> 'june-2026'.
    Lowercased; runs of non-[A-Za-z0-9._-] collapse to a single hyphen."""
    return re.sub(r"[^a-z0-9._-]+", "-", label.strip().lower()).strip("-")


def create_sprint(session: Session, label: str, start: date, end: date) -> m.Sprint:
    label = (label or "").strip()
    if not label:
        raise ValidationError("sprint label is required", field="label")
    slug = slugify_label(label)
    if not slug or not _SPRINT_ID_RE.match(slug):
        raise ValidationError(
            f'sprint label "{label}" has no usable letters/numbers for an id',
            field="label",
        )
    if end < start:
        raise ValidationError(
            f"end ({end.isoformat()}) is before start ({start.isoformat()})", field="end"
        )
    if session.get(m.Sprint, slug):
        raise ValidationError(
            f'a sprint with id "{slug}" already exists (label "{label}")', field="label"
        )
    if (end - start).days + 1 != 14:
        warnings.warn(
            f"sprint {slug}: length is {(end - start).days + 1} days (expected 14)",
            stacklevel=2,
        )
    sprint = m.Sprint(id=slug, label=label, start=start, end=end)
    session.add(sprint)
    session.flush()
    return sprint


def _get_sprint(session: Session, sprint_id: str) -> m.Sprint:
    sprint = session.get(m.Sprint, sprint_id)
    if sprint is None:
        raise ValidationError(f'no sprint "{sprint_id}"')
    return sprint


def delete_sprint(session: Session, sprint_id: str) -> None:
    sprint = _get_sprint(session, sprint_id)
    for event in session.exec(select(m.Event).where(m.Event.sprint_id == sprint_id)).all():
        session.delete(event)
    session.delete(sprint)


def set_archived(session: Session, sprint_id: str, archived: bool) -> m.Sprint:
    sprint = _get_sprint(session, sprint_id)
    sprint.archived = archived
    session.add(sprint)
    return sprint


def set_sprint_dates(session: Session, sprint_id: str, start: date, end: date) -> m.Sprint:
    sprint = _get_sprint(session, sprint_id)
    if end < start:
        raise ValidationError(
            f"end ({end.isoformat()}) is before start ({start.isoformat()})", field="end"
        )
    if (end - start).days + 1 != 14:
        warnings.warn(
            f"sprint {sprint_id}: length is {(end - start).days + 1} days (expected 14)",
            stacklevel=2,
        )
    sprint.start = start
    sprint.end = end
    session.add(sprint)
    return sprint


# --- Import from Jira -------------------------------------------------------

# A YYYY-NN style id embedded anywhere in a Jira sprint name (preferred suggestion).
_ID_IN_NAME = re.compile(r"\d+-\d+")


def _slugify(name: str) -> str:
    """URL/JS-safe id from an arbitrary name: 'Sprint Forty Two' -> 'Sprint-Forty-Two'."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return slug


def _suggest_sprint_id(name: str, prefix: str) -> str:
    """Best-effort short id for a Jira sprint name.

    Prefer the team-prefix remainder, then an embedded YYYY-NN, then a slug of
    the whole name — so every sprint gets an editable, valid suggestion.
    """
    if name.startswith(prefix):
        rest = name[len(prefix):].strip()
        if _SPRINT_ID_RE.match(rest):
            return rest
    found = _ID_IN_NAME.search(name)
    if found:
        return found.group(0)
    return _slugify(name)


def available_jira_sprints(session: Session) -> tuple[list[dict] | None, str]:
    """List *every* sprint the board returns as an import candidate.

    Returns (candidates, error). Matching no longer depends on the name: each
    candidate carries the Jira numeric id (``jira_id``) which is stored on
    import and used for metrics. ``suggested_id`` is a best-effort short id the
    user can edit. Each candidate:
    {jira_id, name, state, start, end, suggested_id, already_imported, importable}.
    """
    client = jira_service.make_client(session)
    if client is None:
        return None, "Jira is not configured (Settings → site, board, username, token)."
    try:
        jira = client.fetch_sprints()
    except JiraUnavailable as e:
        return None, f"Could not reach Jira ({e}). On the VPN?"

    prefix = (config_service.get_settings(session).team_name or "Wisdom") + " "
    rows = session.exec(select(m.Sprint)).all()
    existing_ids = {row.id for row in rows}
    existing_jira_ids = {row.jira_sprint_id for row in rows if row.jira_sprint_id is not None}

    candidates: list[dict] = []
    for name, info in jira.items():
        suggested = _suggest_sprint_id(name, prefix)
        imported = info["id"] in existing_jira_ids or (bool(suggested) and suggested in existing_ids)
        candidates.append(
            {
                "jira_id": info["id"],
                "name": name,
                "state": info.get("state", ""),
                "start": info.get("start"),
                "end": info.get("end"),
                "suggested_id": suggested,
                "already_imported": imported,
                "importable": bool(info.get("start") and info.get("end")),
            }
        )
    # Newest first by start date (None last), then name.
    candidates.sort(key=lambda c: (c["start"] is not None, c["start"], c["name"]), reverse=True)
    return candidates, ""


def import_jira_sprints(session: Session, selections: list[tuple[int, str]]) -> dict:
    """Create Sprint rows from (jira_id, chosen_id) selections.

    Matching is by Jira numeric id, so the board's naming is irrelevant. Each
    chosen_id is validated by create_sprint; rows that already exist, lack Jira
    dates, or have a bad id are skipped. The Jira id + state are stored.
    """
    client = jira_service.make_client(session)
    if client is None:
        raise ValidationError("Jira is not configured.")
    by_jira_id = {info["id"]: info for info in client.fetch_sprints().values()}

    imported, skipped = 0, []
    for jira_id, chosen_id in selections:
        info = by_jira_id.get(jira_id)
        chosen_id = (chosen_id or "").strip()
        if not info or not (info.get("start") and info.get("end")):
            skipped.append(chosen_id or str(jira_id))
            continue
        try:
            # create_sprint validates the label / derives the slug id and checks
            # for dups before any write, so a failure here leaves earlier creates
            # in this transaction intact. It returns the created row (keyed by the
            # derived slug, which may differ from the chosen label).
            row = create_sprint(session, chosen_id, info["start"], info["end"])
        except ValidationError:
            skipped.append(chosen_id or str(jira_id))
            continue
        row.jira_sprint_id = jira_id
        row.jira_state = info.get("state", "future")
        session.add(row)
        imported += 1
    return {"imported": imported, "skipped": skipped}


# --- Event CRUD -------------------------------------------------------------

def add_event(session: Session, sprint_id: str, d: date, kind: str, title: str) -> m.Event:
    sprint = _get_sprint(session, sprint_id)
    day_err = working_day_error(d, sprint.start, sprint.end)
    if day_err:
        raise ValidationError(f"date {day_err}", field="date")
    kind_err = event_kind_error(kind)
    if kind_err:
        raise ValidationError(kind_err, field="kind")
    if not (title or "").strip():
        raise ValidationError("title is required", field="title")
    event = m.Event(sprint_id=sprint_id, date=d, kind=kind, title=title.strip())
    session.add(event)
    session.flush()
    return event


def delete_event(session: Session, event_id: int) -> None:
    event = session.get(m.Event, event_id)
    if event is None:
        raise ValidationError(f"no event with id {event_id}")
    session.delete(event)


