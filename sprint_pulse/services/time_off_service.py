"""Member day-off CRUD + derivations.

Time-off lives on the member (one MemberDayOff row per working day), never on a
sprint. The dashboard reconstructs the existing frozen ``TimeOffEntry`` objects
from these rows (grouped per type+notes) so ``render.py`` is reused unchanged;
sprints derive their outage by date overlap.
"""
from __future__ import annotations

import calendar as _cal
from collections.abc import Iterable, Sequence
from datetime import date

from sqlmodel import Session, select

from sprint_pulse.db import models as m
from sprint_pulse.errors import ValidationError
from sprint_pulse.render import TYPE_LETTERS
from sprint_pulse.sprints import TimeOffEntry, weekday_error

VALID_TYPES = ("pto", "holiday", "company", "partial", "tentative")
# Type precedence for resolving a (member, day) that carried two types in source
# data — higher wins. Used by the YAML import path (migrate.py); the unique
# (member_id, date) constraint means live data never has a conflict.
TYPE_PRIORITY = {"company": 4, "holiday": 3, "pto": 2, "partial": 1, "tentative": 0}


def _require_member(session: Session, member_id: int) -> m.TeamMember:
    member = session.get(m.TeamMember, member_id)
    if member is None:
        raise ValidationError(f"no team member with id {member_id}")
    return member


def set_days(session: Session, member_id: int, dates: Iterable[date], type_: str, notes: str = "") -> None:
    """Upsert one MemberDayOff per date (replacing type/notes if present)."""
    _require_member(session, member_id)
    if type_ not in VALID_TYPES:
        raise ValidationError(
            f'unknown type "{type_}" (expected {"/".join(VALID_TYPES)})', field="type"
        )
    dates = list(dates)
    if not dates:
        raise ValidationError("at least one day is required", field="days")
    for d in dates:
        err = weekday_error(d)
        if err:
            raise ValidationError(err, field="days")
    for d in dates:
        row = session.exec(
            select(m.MemberDayOff).where(
                m.MemberDayOff.member_id == member_id, m.MemberDayOff.date == d
            )
        ).first()
        if row is None:
            session.add(m.MemberDayOff(member_id=member_id, date=d, type=type_, notes=notes or ""))
        else:
            row.type = type_
            row.notes = notes or ""
            session.add(row)


def clear_days(session: Session, member_id: int, dates: Iterable[date]) -> None:
    _require_member(session, member_id)
    for d in dates:
        row = session.exec(
            select(m.MemberDayOff).where(
                m.MemberDayOff.member_id == member_id, m.MemberDayOff.date == d
            )
        ).first()
        if row is not None:
            session.delete(row)


def member_calendar(session: Session, member_id: int, year: int, month: int) -> dict:
    """{date: (type, notes)} for the given member + month."""
    lo = date(year, month, 1)
    hi = date(year, month, _cal.monthrange(year, month)[1])
    rows = session.exec(
        select(m.MemberDayOff).where(
            m.MemberDayOff.member_id == member_id,
            m.MemberDayOff.date >= lo,
            m.MemberDayOff.date <= hi,
        )
    ).all()
    return {r.date: (r.type, r.notes) for r in rows}


def _entries_from_rows(rows: Sequence[m.MemberDayOff], member_name: dict[int, str]) -> list[TimeOffEntry]:
    """Group MemberDayOff rows into TimeOffEntry objects per (member, type, notes)."""
    by_kind: dict[tuple, list[date]] = {}
    for r in rows:
        if r.member_id not in member_name:
            continue
        by_kind.setdefault((r.member_id, r.type, r.notes), []).append(r.date)
    out: list[TimeOffEntry] = []
    for (mid, type_, notes), days in by_kind.items():
        out.append(
            TimeOffEntry(
                associate=member_name[mid], days=tuple(sorted(days)), notes=notes, type=type_
            )
        )
    return out


def outage_entries(session: Session, start: date, end: date, member_name: dict) -> list[TimeOffEntry]:
    """TimeOffEntry list for all members whose days fall in [start, end]."""
    rows = session.exec(
        select(m.MemberDayOff).where(
            m.MemberDayOff.date >= start, m.MemberDayOff.date <= end
        )
    ).all()
    return _entries_from_rows(rows, member_name)


def entries_for_sprints(rows, member_name: dict, start: date, end: date) -> list[TimeOffEntry]:
    """In-memory variant used by the bulk dashboard load (rows already fetched)."""
    in_range = [r for r in rows if start <= r.date <= end]
    return _entries_from_rows(in_range, member_name)


def build_month_grid(year: int, month: int, day_map: dict) -> list[list[dict]]:
    """Weeks (Mon-first) of cell dicts for the calendar template."""
    weeks: list[list[dict]] = []
    for week in _cal.Calendar(firstweekday=0).monthdatescalendar(year, month):
        cells: list[dict] = []
        for d in week:
            type_, notes = day_map.get(d, ("", ""))
            cells.append({
                "date": d,
                "day": d.day,
                "in_month": d.month == month,
                "weekend": d.weekday() >= 5,
                "type": type_,
                "notes": notes,
                "letter": TYPE_LETTERS.get(type_, ""),
            })
        weeks.append(cells)
    return weeks
