"""One-time YAML -> SQLite import.

Reuses the existing strict loaders (:func:`load_config`, :func:`load_sprints`)
so every current validation rule runs during the import. The Jira API token is
NOT imported — it is set at first run via the secrets backend.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from sprint_pulse.config import load_config
from sprint_pulse.db import models as m
from sprint_pulse.db.engine import create_db_and_tables, session_scope
from sprint_pulse.services.time_off_service import TYPE_PRIORITY
from sprint_pulse.sprints import load_sprints


class MigrationError(Exception):
    """Raised when import is refused (e.g. DB already populated)."""


def _db_is_populated(session: Session) -> bool:
    return session.exec(select(m.TeamMember)).first() is not None


def import_yaml(
    engine: Engine,
    config_path: Path | str,
    sprints_dir: Path | str,
    *,
    force: bool = False,
) -> dict[str, int]:
    """Import config + sprint YAML into the DB. Returns row counts.

    Idempotent guard: refuses to run against a populated DB unless ``force``.
    """
    create_db_and_tables(engine)

    cfg = load_config(config_path)
    sprints = load_sprints(sprints_dir, cfg)

    with session_scope(engine) as session:
        if _db_is_populated(session):
            if not force:
                raise MigrationError(
                    "Database already contains team members. Re-run with force=True to overwrite."
                )
            _wipe(session)

        # Settings (singleton) — update in place if it already exists (the
        # scheduler may have created it at app startup), else insert.
        settings = session.get(m.Settings, 1) or m.Settings(id=1)
        settings.working_days_per_sprint = cfg.working_days_per_sprint
        settings.team_name = cfg.team_name
        settings.jira_site = cfg.jira.site
        settings.jira_board = cfg.jira.board
        session.add(settings)

        # Team members, preserving roster order.
        members: dict[str, m.TeamMember] = {}
        for order, name in enumerate(cfg.roster):
            member = m.TeamMember(
                name=name,
                is_orchestration=name in cfg.orchestration,
                sort_order=order,
            )
            session.add(member)
            members[name] = member
        session.flush()  # assign member ids for FKs below

        # Name aliases (source -> canonical member).
        for source, target in cfg.name_aliases.items():
            session.add(
                m.NameAlias(source=source, target_member_id=members[target].id)
            )

        # Sprints + events.
        n_events = 0
        day_off: dict[tuple, tuple[str, str]] = {}  # (member_id, date) -> (type, notes)
        for sprint in sprints:
            session.add(m.Sprint(id=sprint.id, start=sprint.start, end=sprint.end))
            for ev in sprint.events:
                session.add(
                    m.Event(sprint_id=sprint.id, date=ev.date, kind=ev.kind, title=ev.title)
                )
                n_events += 1
            for entry in sprint.time_off:
                mid = members[entry.associate].id
                for d in entry.days:
                    key = (mid, d)
                    cur = day_off.get(key)
                    if cur is None or TYPE_PRIORITY[entry.type] > TYPE_PRIORITY[cur[0]]:
                        day_off[key] = (entry.type, entry.notes or (cur[1] if cur else ""))
                    elif not cur[1] and entry.notes:
                        day_off[key] = (cur[0], entry.notes)
        for (mid, d), (type_, notes) in day_off.items():
            session.add(m.MemberDayOff(member_id=mid, date=d, type=type_, notes=notes))

    return {
        "members": len(cfg.roster),
        "orchestration": len(cfg.orchestration),
        "aliases": len(cfg.name_aliases),
        "sprints": len(sprints),
        "events": n_events,
        "days_off": len(day_off),
    }


def _wipe(session: Session) -> None:
    """Delete all rows (used by force re-import)."""
    for model in (
        m.MemberDayOff,
        m.Event,
        m.Sprint,
        m.NameAlias,
        m.TeamMember,
        m.Settings,
    ):
        for row in session.exec(select(model)).all():
            session.delete(row)
    session.flush()
