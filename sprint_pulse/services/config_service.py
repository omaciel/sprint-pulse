"""Config/team reads + validated mutators over the DB.

``build_config_from_db`` hydrates the existing frozen :class:`Config` dataclass
so all downstream code (capacity math, renderer) is reused unchanged.
"""
from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

from sprint_pulse.config import Config, JiraConfig, TypeDef, normalize_site
from sprint_pulse.db import models as m
from sprint_pulse.errors import ValidationError
from sprint_pulse.services import secrets, type_service


def get_settings(session: Session) -> m.Settings:
    settings = session.get(m.Settings, 1)
    if settings is None:
        settings = m.Settings(id=1)
        session.add(settings)
        session.flush()
    return settings


def list_members(session: Session) -> list[m.TeamMember]:
    # Display order is alphabetical by first name ascending. Names are stored as
    # a single "First Last" field, so a case-insensitive sort on the full string
    # orders by first name (with last name as the natural tiebreaker). This is the
    # single source of truth for the Team page and the dashboard roster.
    members = session.exec(select(m.TeamMember)).all()
    return sorted(members, key=lambda member: member.name.casefold())


def is_empty(session: Session) -> bool:
    """True when no team members exist yet (drives the first-run wizard)."""
    return session.exec(select(m.TeamMember)).first() is None


def build_config_from_db(session: Session) -> Config:
    settings = get_settings(session)
    members = list_members(session)
    roster = [member.name for member in members]
    excluded = {member.name for member in members if member.is_excluded}

    by_id = {member.id: member.name for member in members}
    aliases = {
        alias.source: by_id[alias.target_member_id]
        for alias in session.exec(select(m.NameAlias)).all()
        if alias.target_member_id in by_id
    }

    event_types = tuple(
        TypeDef(t.key, t.label, t.abbreviation, t.color, t.sort_order)
        for t in type_service.list_event_types(session)
    )
    absence_types = tuple(
        TypeDef(t.key, t.label, t.abbreviation, t.color, t.sort_order)
        for t in type_service.list_absence_types(session)
    )

    return Config(
        working_days_per_sprint=settings.working_days_per_sprint,
        jira=JiraConfig(site=settings.jira_site, board=settings.jira_board),
        roster=roster,
        excluded=excluded,
        name_aliases=aliases,
        team_name=settings.team_name or "My Team",
        event_types=event_types,
        absence_types=absence_types,
    )


# --- Mutators ---------------------------------------------------------------

def update_settings(session: Session, **fields) -> m.Settings:
    settings = get_settings(session)
    for key, value in fields.items():
        if not hasattr(settings, key):
            raise ValidationError(f"unknown setting '{key}'", field=key)
        setattr(settings, key, value)
    session.add(settings)
    return settings


def apply_jira_settings(
    session: Session,
    *,
    jira_site: str,
    jira_board: str,
    jira_username: str,
    jira_token: str = "",
    working_days_per_sprint: int | None = None,
    team_name: str | None = None,
) -> m.Settings:
    """Persist app + Jira settings and (only on the keyring backend) the token.

    Shared by the config page and the setup wizard so credential handling can't
    diverge between them.
    """
    username = (jira_username or "").strip()
    token_ref = secrets.detect_backend()
    fields: dict = {
        "jira_site": normalize_site(jira_site),
        "jira_board": (jira_board or "").strip(),
        "jira_username": username,
        "token_ref": token_ref,
    }
    if working_days_per_sprint is not None:
        fields["working_days_per_sprint"] = working_days_per_sprint
    if team_name is not None:
        fields["team_name"] = (team_name or "").strip() or "My Team"
    settings = update_settings(session, **fields)
    # Only the keyring backend is writable; env is operator-provided.
    if jira_token.strip() and token_ref == "keyring" and username:
        secrets.set_token(token_ref, username, jira_token.strip())
    return settings


def _get_member(session: Session, member_id: int) -> m.TeamMember:
    member = session.get(m.TeamMember, member_id)
    if member is None:
        raise ValidationError(f"no team member with id {member_id}")
    return member


def get_member(session: Session, member_id: int) -> m.TeamMember:
    """Public accessor: fetch a member by id (raises ValidationError if missing)."""
    return _get_member(session, member_id)


def add_member(
    session: Session,
    name: str,
    *,
    is_excluded: bool = False,
    start_date: date | None = None,
) -> m.TeamMember:
    name = (name or "").strip()
    if not name:
        raise ValidationError("name is required", field="name")
    if session.exec(select(m.TeamMember).where(m.TeamMember.name == name)).first():
        raise ValidationError(f'"{name}" is already on the roster', field="name")
    # max(sort_order)+1, not count: a prior removal would otherwise collide.
    existing = list_members(session)
    next_order = (max((member.sort_order for member in existing), default=-1)) + 1
    member = m.TeamMember(
        name=name, is_excluded=is_excluded, sort_order=next_order, start_date=start_date
    )
    session.add(member)
    session.flush()
    return member


def rename_member(session: Session, member_id: int, new_name: str) -> m.TeamMember:
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValidationError("name is required", field="name")
    clash = session.exec(select(m.TeamMember).where(m.TeamMember.name == new_name)).first()
    if clash and clash.id != member_id:
        raise ValidationError(f'"{new_name}" is already on the roster', field="name")
    member = _get_member(session, member_id)
    member.name = new_name
    session.add(member)
    return member


def toggle_excluded(session: Session, member_id: int) -> m.TeamMember:
    member = _get_member(session, member_id)
    member.is_excluded = not member.is_excluded
    session.add(member)
    return member


def depart_member(session: Session, member_id: int, end_date: date) -> m.TeamMember:
    """Mark a member as departed: set end_date, drop time off past it.

    History (time off up to and including end_date, aliases) is kept so past
    sprints keep rendering this member; use remove_member only for mistakes.
    """
    member = _get_member(session, member_id)
    if member.start_date is not None and end_date < member.start_date:
        raise ValidationError(
            f"departure ({end_date.isoformat()}) is before "
            f"{member.name}'s start date ({member.start_date.isoformat()})",
            field="end_date",
        )
    for row in session.exec(
        select(m.MemberDayOff).where(
            m.MemberDayOff.member_id == member_id, m.MemberDayOff.date > end_date
        )
    ).all():
        session.delete(row)
    member.end_date = end_date
    session.add(member)
    return member


def rejoin_member(session: Session, member_id: int) -> m.TeamMember:
    member = _get_member(session, member_id)
    if member.end_date is None:
        raise ValidationError(f"{member.name} has not departed", field="end_date")
    member.end_date = None
    session.add(member)
    return member


def remove_member(session: Session, member_id: int) -> None:
    """Delete a member plus dependent aliases and time-off (manual cascade)."""
    member = _get_member(session, member_id)
    for alias in session.exec(
        select(m.NameAlias).where(m.NameAlias.target_member_id == member_id)
    ).all():
        session.delete(alias)
    for row in session.exec(
        select(m.MemberDayOff).where(m.MemberDayOff.member_id == member_id)
    ).all():
        session.delete(row)
    session.delete(member)


def add_alias(session: Session, source: str, target_member_id: int) -> m.NameAlias:
    source = (source or "").strip()
    if not source:
        raise ValidationError("alias source is required", field="source")
    _get_member(session, target_member_id)  # target must exist
    if session.exec(select(m.NameAlias).where(m.NameAlias.source == source)).first():
        raise ValidationError(f'alias "{source}" already exists', field="source")
    alias = m.NameAlias(source=source, target_member_id=target_member_id)
    session.add(alias)
    session.flush()
    return alias


def remove_alias(session: Session, alias_id: int) -> None:
    alias = session.get(m.NameAlias, alias_id)
    if alias is None:
        raise ValidationError(f"no alias with id {alias_id}")
    session.delete(alias)
