"""Sprint loader: data/sprints/*.yaml -> list[Sprint]."""
from __future__ import annotations

import re
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import date, timedelta
from difflib import get_close_matches
from pathlib import Path
from typing import Any

import yaml

from sprint_pulse.config import Config


def slugify(label: str) -> str:
    """Canonical URL/JS-safe slug from a free-form label: 'June 2026' -> 'june-2026'.

    This is the single source of truth for slug derivation, shared by the DB
    service layer (``sprint_service.slugify_label`` delegates here) and the YAML
    import path. Accented Latin characters are folded to ASCII ('Été' -> 'ete');
    other non-ASCII characters are dropped. Runs of unsafe chars collapse to one
    hyphen; leading/trailing hyphens are stripped.
    """
    ascii_label = (
        unicodedata.normalize("NFKD", label)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9._-]+", "-", ascii_label.strip().lower()).strip("-")


HOLIDAY_KEYWORDS = (
    "holiday", "memorial day", "labor day", "labour day", "pentecost",
    "liberation", "victoria", "independence", "patriots", "boxing day",
    "christmas", "easter", "thanksgiving", "ramadan", "diwali",
)

EVENT_KINDS = ("tags", "gono", "ga", "freeze", "test")


class SprintError(Exception):
    """Raised when a sprint YAML file fails validation."""


@dataclass(frozen=True)
class Event:
    date: date
    kind: str
    title: str


@dataclass(frozen=True)
class TimeOffEntry:
    associate: str
    days: tuple[date, ...]
    notes: str
    type: str  # pto | holiday | company | partial | tentative


@dataclass(frozen=True)
class Sprint:
    id: str
    start: date
    end: date
    events: tuple[Event, ...]
    time_off: tuple[TimeOffEntry, ...]
    label: str = ""


def working_days(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def infer_type(notes: str) -> str:
    n = notes.lower().strip()
    if "company" in n:
        return "company"
    if "partial" in n:
        return "partial"
    if "tentative" in n:
        return "tentative"
    if any(kw in n for kw in HOLIDAY_KEYWORDS):
        return "holiday"
    return "pto"


_ALL = "__all__"
_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _suggest(name: str, roster: list[str]) -> str:
    matches = get_close_matches(name, roster, n=1, cutoff=0.6)
    return f' (typo? did you mean "{matches[0]}")' if matches else ""


# --- Shared, pure field validators -----------------------------------------
# These are the single source of validation truth: both the YAML loader (below)
# and the DB service layer (sprint_pulse.services.sprint_service) call them, so
# the two paths can never drift. Each returns an error message, or None if OK.

def weekday_error(d: date) -> str | None:
    """Why ``d`` is not a Mon–Fri working day (or None)."""
    if d.weekday() >= 5:
        return f"{d.isoformat()} is a {_WEEKDAY_NAMES[d.weekday()]}"
    return None


def working_day_error(d: date, start: date, end: date) -> str | None:
    """Why ``d`` is not a valid working day inside ``[start, end]`` (or None)."""
    err = weekday_error(d)
    if err:
        return err
    if not (start <= d <= end):
        return (
            f"{d.isoformat()} is outside sprint range "
            f"{start.isoformat()}..{end.isoformat()}"
        )
    return None


def event_kind_error(kind: str) -> str | None:
    if kind not in EVENT_KINDS:
        return f'unknown kind "{kind}" (expected {"/".join(EVENT_KINDS)})'
    return None


def _validate_event(prefix: str, idx: int, raw: dict[str, Any], start: date, end: date) -> Event:
    d = raw.get("date")
    if not isinstance(d, date):
        raise SprintError(f"{prefix}: event {idx}: date must be a YAML date, got {d!r}")
    day_err = working_day_error(d, start, end)
    if day_err:
        raise SprintError(f"{prefix}: event {idx}: date {day_err}")
    kind = raw.get("kind")
    kind_err = event_kind_error(kind)
    if kind_err:
        raise SprintError(f"{prefix}: event {idx}: {kind_err}")
    title = raw.get("title", "")
    if not isinstance(title, str) or not title.strip():
        raise SprintError(f"{prefix}: event {idx}: missing title")
    return Event(date=d, kind=kind, title=title)


def _validate_time_off(
    prefix: str,
    idx: int,
    raw: dict[str, Any],
    start: date,
    end: date,
    cfg: Config,
) -> list[TimeOffEntry]:
    associate = raw.get("associate")
    if not isinstance(associate, str) or not associate:
        raise SprintError(f"{prefix}: time_off {idx}: missing associate")
    if associate != _ALL and associate not in cfg.roster:
        raise SprintError(
            f'{prefix}: time_off {idx}: unknown associate "{associate}"'
            f"{_suggest(associate, cfg.roster)}"
        )
    days_raw = raw.get("days") or []
    if not isinstance(days_raw, list) or not days_raw:
        raise SprintError(f"{prefix}: time_off {idx}: empty days list")
    days: list[date] = []
    for d in days_raw:
        if not isinstance(d, date):
            raise SprintError(f"{prefix}: time_off {idx}: day must be a YAML date, got {d!r}")
        day_err = working_day_error(d, start, end)
        if day_err:
            raise SprintError(f"{prefix}: time_off {idx}: {day_err}")
        days.append(d)
    notes = raw.get("notes") or ""
    type_ = infer_type(notes)
    if associate == _ALL:
        return [
            TimeOffEntry(associate=name, days=tuple(days), notes=notes, type=type_)
            for name in cfg.roster
        ]
    return [TimeOffEntry(associate=associate, days=tuple(days), notes=notes, type=type_)]


def load_sprint_file(path: Path | str, cfg: Config) -> Sprint:
    path = Path(path)
    prefix = f"sprints/{path.name}"
    with path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    sid = raw.get("id")
    if not isinstance(sid, str) or not sid:
        raise SprintError(f"{prefix}: id must be a non-empty string")

    start = raw.get("start")
    end = raw.get("end")
    if not isinstance(start, date):
        raise SprintError(f"{prefix}: start must be a YAML date")
    if not isinstance(end, date):
        raise SprintError(f"{prefix}: end must be a YAML date")
    if end < start:
        raise SprintError(
            f"{prefix}: end ({end.isoformat()}) is before start ({start.isoformat()})"
        )

    if (end - start).days + 1 != 14:
        warnings.warn(
            f"{prefix}: sprint length is {(end - start).days + 1} days (expected 14)",
            stacklevel=2,
        )

    events = tuple(
        _validate_event(prefix, i, e or {}, start, end)
        for i, e in enumerate(raw.get("events") or [])
    )

    time_off: list[TimeOffEntry] = []
    for i, t in enumerate(raw.get("time_off") or []):
        time_off.extend(_validate_time_off(prefix, i, t or {}, start, end, cfg))

    return Sprint(id=sid, start=start, end=end, events=events, time_off=tuple(time_off))


def _check_duplicate_ids(pairs: list[tuple[str, str]]) -> None:
    """pairs: list of (filename, id). Raises if any id appears twice."""
    seen: dict[str, str] = {}
    for fname, sid in pairs:
        if sid in seen:
            raise SprintError(f"Duplicate sprint id {sid} in {seen[sid]} and {fname}")
        seen[sid] = fname


def _check_id_matches_filename(path: Path, sid: str) -> None:
    """Raises if the sprint file's id field doesn't match its filename stem."""
    if sid != path.stem:
        raise SprintError(f'sprints/{path.name}: id "{sid}" does not match filename')


def load_sprints(directory: Path | str, cfg: Config) -> list[Sprint]:
    directory = Path(directory)
    files = sorted(p for p in directory.glob("*.yaml") if p.is_file())
    sprints: list[Sprint] = []
    for p in files:
        sprint = load_sprint_file(p, cfg)
        _check_id_matches_filename(p, sprint.id)
        sprints.append(sprint)
    _check_duplicate_ids([(p.name, s.id) for p, s in zip(files, sprints)])
    return sorted(sprints, key=lambda s: (s.start, s.end, s.id))
