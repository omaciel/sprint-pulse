"""Config/team reads + validated mutators over the DB.

``build_config_from_db`` hydrates the existing frozen :class:`Config` dataclass
so all downstream code (capacity math, renderer) is reused unchanged.
"""
from __future__ import annotations

from sqlmodel import Session, select

from sprint_pulse.config import Config, JiraConfig, normalize_site
from sprint_pulse.db import models as m
from sprint_pulse.errors import ValidationError
from sprint_pulse.services import secrets


def get_settings(session: Session) -> m.Settings:
    settings = session.get(m.Settings, 1)
    if settings is None:
        settings = m.Settings(id=1)
        session.add(settings)
        session.flush()
    return settings


def list_members(session: Session) -> list[m.TeamMember]:
    return list(
        session.exec(select(m.TeamMember).order_by(m.TeamMember.sort_order, m.TeamMember.id)).all()
    )


def is_empty(session: Session) -> bool:
    """True when no team members exist yet (drives the first-run wizard)."""
    return session.exec(select(m.TeamMember)).first() is None


def build_config_from_db(session: Session) -> Config:
    settings = get_settings(session)
    members = list_members(session)
    roster = [member.name for member in members]
    orchestration = {member.name for member in members if member.is_orchestration}

    by_id = {member.id: member.name for member in members}
    aliases = {
        alias.source: by_id[alias.target_member_id]
        for alias in session.exec(select(m.NameAlias)).all()
        if alias.target_member_id in by_id
    }

    return Config(
        working_days_per_sprint=settings.working_days_per_sprint,
        jira=JiraConfig(site=settings.jira_site, board=settings.jira_board),
        roster=roster,
        orchestration=orchestration,
        name_aliases=aliases,
        team_name=settings.team_name or "Wisdom",
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
        fields["team_name"] = (team_name or "").strip() or "Wisdom"
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


def add_member(session: Session, name: str, *, is_orchestration: bool = False) -> m.TeamMember:
    name = (name or "").strip()
    if not name:
        raise ValidationError("name is required", field="name")
    if session.exec(select(m.TeamMember).where(m.TeamMember.name == name)).first():
        raise ValidationError(f'"{name}" is already on the roster', field="name")
    # max(sort_order)+1, not count: a prior removal would otherwise collide.
    existing = list_members(session)
    next_order = (max((member.sort_order for member in existing), default=-1)) + 1
    member = m.TeamMember(name=name, is_orchestration=is_orchestration, sort_order=next_order)
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


def toggle_orchestration(session: Session, member_id: int) -> m.TeamMember:
    member = _get_member(session, member_id)
    member.is_orchestration = not member.is_orchestration
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
