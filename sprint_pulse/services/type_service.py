"""CRUD + seeding for EventType / AbsenceType. Block deletion while a type is
still referenced by Event.kind / MemberDayOff.type."""
from __future__ import annotations

from sqlmodel import Session, select

from sprint_pulse.db import models as m
from sprint_pulse.errors import ValidationError
from sprint_pulse.sprints import slugify
from sprint_pulse.types_defaults import (
    PALETTE, DEFAULT_EVENT_TYPES, DEFAULT_ABSENCE_TYPES,
)


def list_event_types(session: Session) -> list[m.EventType]:
    return list(session.exec(select(m.EventType).order_by(m.EventType.sort_order, m.EventType.key)).all())


def list_absence_types(session: Session) -> list[m.AbsenceType]:
    return list(session.exec(select(m.AbsenceType).order_by(m.AbsenceType.sort_order, m.AbsenceType.key)).all())


def event_type_keys(session: Session) -> set[str]:
    return {t.key for t in list_event_types(session)}


def absence_type_keys(session: Session) -> set[str]:
    return {t.key for t in list_absence_types(session)}


def _validate(label: str, abbreviation: str, color: str) -> tuple[str, str, str, str]:
    label = (label or "").strip()
    if not label:
        raise ValidationError("type label is required", field="label")
    key = slugify(label)
    if not key:
        raise ValidationError(f'label "{label}" has no usable letters/numbers', field="label")
    abbreviation = (abbreviation or "").strip()
    if not (1 <= len(abbreviation) <= 2):
        raise ValidationError("abbreviation must be 1-2 characters", field="abbreviation")
    if color not in PALETTE:
        raise ValidationError("color must be chosen from the palette", field="color")
    return key, label, abbreviation, color


def _next_order(rows) -> int:
    return (max((r.sort_order for r in rows), default=-1)) + 1


def create_event_type(session, label, abbreviation, color):
    key, label, abbreviation, color = _validate(label, abbreviation, color)
    if session.get(m.EventType, key):
        raise ValidationError(f'an event type "{key}" already exists', field="label")
    row = m.EventType(key=key, label=label, abbreviation=abbreviation, color=color,
                      sort_order=_next_order(list_event_types(session)))
    session.add(row); session.flush(); return row


def create_absence_type(session, label, abbreviation, color):
    key, label, abbreviation, color = _validate(label, abbreviation, color)
    if session.get(m.AbsenceType, key):
        raise ValidationError(f'an absence type "{key}" already exists', field="label")
    row = m.AbsenceType(key=key, label=label, abbreviation=abbreviation, color=color,
                        sort_order=_next_order(list_absence_types(session)))
    session.add(row); session.flush(); return row


def update_event_type(session, key, label, abbreviation, color):
    row = session.get(m.EventType, key)
    if row is None:
        raise ValidationError(f'no event type "{key}"')
    _, row.label, row.abbreviation, row.color = _validate(label, abbreviation, color)
    session.add(row); return row


def update_absence_type(session, key, label, abbreviation, color):
    row = session.get(m.AbsenceType, key)
    if row is None:
        raise ValidationError(f'no absence type "{key}"')
    _, row.label, row.abbreviation, row.color = _validate(label, abbreviation, color)
    session.add(row); return row


def delete_event_type(session, key):
    n = len(session.exec(select(m.Event).where(m.Event.kind == key)).all())
    if n:
        raise ValidationError(f'cannot delete: {n} event(s) still use "{key}"', field="key")
    row = session.get(m.EventType, key)
    if row is not None:
        session.delete(row)


def delete_absence_type(session, key):
    n = len(session.exec(select(m.MemberDayOff).where(m.MemberDayOff.type == key)).all())
    if n:
        raise ValidationError(f'cannot delete: {n} absence(s) still use "{key}"', field="key")
    row = session.get(m.AbsenceType, key)
    if row is not None:
        session.delete(row)


def seed_default_types(session: Session) -> None:
    """Seed defaults only into an EMPTY table (so a user-deleted default stays gone)."""
    if not session.exec(select(m.EventType)).first():
        for t in DEFAULT_EVENT_TYPES:
            session.add(m.EventType(**t))
    if not session.exec(select(m.AbsenceType)).first():
        for t in DEFAULT_ABSENCE_TYPES:
            session.add(m.AbsenceType(**t))
