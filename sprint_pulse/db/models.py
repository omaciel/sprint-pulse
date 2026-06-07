"""SQLModel tables — the source of truth that replaces the YAML files.

Mapping back to the original domain:
  config.yaml  -> Settings (singleton) + TeamMember + NameAlias
  sprints/*.yaml -> Sprint + Event + MemberDayOff

The Jira API token is NEVER stored here; Settings only holds ``token_ref``
naming the backend that holds it (see services/secrets.py).

We deliberately use plain foreign-key columns rather than ORM relationships:
SQLModel's string forward-refs in ``Relationship`` are brittle on newer
SQLAlchemy, and every consumer here queries explicitly anyway. Cascade
deletes are handled in the service layer (delete children before parents).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import ClassVar, Optional

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel


class Settings(SQLModel, table=True):
    """Singleton row (id == 1) holding app + integration config."""

    id: Optional[int] = Field(default=1, primary_key=True)
    working_days_per_sprint: int = 10
    # Display label + Jira sprint-name prefix (board sprints are "{team_name} {id}").
    team_name: str = "My Team"

    jira_site: str = ""
    jira_board: str = ""
    jira_username: str = ""
    # "keyring" (desktop) or "env" (container/headless). Never the raw token.
    token_ref: str = "env"

    # Scheduler config + last-run status (one in-process scheduler per DB).
    scheduler_enabled: bool = False
    scheduler_trigger: str = "interval"  # "interval" | "cron"
    scheduler_value: str = "60"  # minutes for interval, cron expr for cron
    last_run: Optional[datetime] = None
    last_status: str = ""  # "ok" | "error" | ""
    last_log: str = ""


class TeamMember(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    is_excluded: bool = False
    sort_order: int = 0


class NameAlias(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(unique=True, index=True)
    target_member_id: int = Field(foreign_key="teammember.id")


class Sprint(SQLModel, table=True):
    # URL/JS-safe slug primary key (e.g. "june-2026"), auto-derived from `label`.
    id: str = Field(primary_key=True)
    # Free-form display label (e.g. "June 2026"). Backfilled to `id` on upgrade.
    label: str = ""
    start: date
    end: date
    # Archived sprints stay in the Sprints list but drop off the dashboard.
    archived: bool = False
    # Jira's own numeric sprint id (set on import). Metrics refresh matches on
    # this directly; None for sprints created before this existed / by hand.
    jira_sprint_id: Optional[int] = None

    # Cached Jira metrics (refreshed by the scheduler) so the dashboard renders
    # instantly without a live API call.
    jira_state: str = "future"  # active | closed | future
    done_n: int = 0
    tot_n: int = 0
    done_sp: int = 0
    tot_sp: int = 0
    last_refreshed: Optional[datetime] = None


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sprint_id: str = Field(foreign_key="sprint.id", index=True)
    date: date
    kind: str  # tags | gono | ga | freeze | test
    title: str


class MemberDayOff(SQLModel, table=True):
    """One row per (member, working day) absence. Replaces TimeOff + TimeOffDay.
    Not anchored to a sprint — sprints derive outage by date overlap."""
    id: Optional[int] = Field(default=None, primary_key=True)
    member_id: int = Field(foreign_key="teammember.id", index=True)
    # Bare annotation (no Field assignment) avoids a pydantic v2 + SQLModel 0.0.38
    # name-clash error: field named 'date' typed as 'date' with = Field(…) breaks
    # annotation resolution when __table_args__ is also present. Index is declared
    # below in __table_args__ instead.
    date: date
    type: str = "pto"  # pto | holiday | company | partial | tentative
    notes: str = ""
    __table_args__: ClassVar[tuple] = (
        UniqueConstraint("member_id", "date", name="uq_member_day"),
        Index("ix_memberdayoff_date", "date"),
    )
