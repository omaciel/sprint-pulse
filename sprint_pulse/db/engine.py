"""SQLite engine + session helpers.

The DB path is resolved once, in this order:
  1. env SPRINT_PULSE_DB           (explicit override; used by the container)
  2. platform data dir             (desktop default)
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# Importing models registers them on SQLModel.metadata so create_all sees them.
from sprint_pulse.db import models as _models  # noqa: F401

_APP_DIRNAME = "sprint-pulse"
_DB_FILENAME = "sprint-pulse.db"


def _xdg_default_data_dir() -> Path:
    """XDG data dir when XDG_DATA_HOME is unset (the spec default)."""
    return Path.home() / ".local" / "share" / _APP_DIRNAME


def _native_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_DIRNAME
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", Path.home())) / _APP_DIRNAME
    return Path.home() / ".local" / "share" / _APP_DIRNAME


def default_db_path() -> Path:
    """Location for the SQLite file.

    Explicit env always wins:
      1. ``SPRINT_PULSE_DB``  — exact path override (used by the container)
      2. ``XDG_DATA_HOME``    — ``$XDG_DATA_HOME/sprint-pulse/...`` (any OS)

    Otherwise SEARCH candidate locations and use the first that already exists,
    so an install is found wherever it lives:
      a. XDG default  (~/.local/share/sprint-pulse/...)   — preferred
      b. platform-native (macOS ~/Library/Application Support, Windows %APPDATA%)
    If none exist, return the preferred (XDG-default) path as the create target.
    """
    override = os.environ.get("SPRINT_PULSE_DB")
    if override:
        return Path(override)

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / _APP_DIRNAME / _DB_FILENAME

    candidates: list[Path] = []
    for directory in (_xdg_default_data_dir(), _native_data_dir()):
        candidate = directory / _DB_FILENAME
        if candidate not in candidates:  # de-dup (identical on Linux)
            candidates.append(candidate)
    for candidate in candidates:
        if candidate.exists():  # follows symlinks
            return candidate
    return candidates[0]  # nothing found → create at the preferred location


def get_engine(db_path: Path | str | None = None, *, echo: bool = False) -> Engine:
    """Create an Engine for the given path (or the platform default).

    Pass ``":memory:"`` for an in-memory DB (tests).
    """
    connect_args = {"check_same_thread": False}
    if db_path == ":memory:":
        # A bare in-memory DB gives each connection its OWN empty database;
        # StaticPool keeps a single shared connection so tables persist across
        # sessions (and across the scheduler thread).
        return create_engine(
            "sqlite://", echo=echo, connect_args=connect_args, poolclass=StaticPool
        )
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the scheduler thread shares the engine with the
    # request threads; SQLite is fine with this for our low write volume.
    return create_engine(f"sqlite:///{path}", echo=echo, connect_args=connect_args)


# Columns added after the initial schema. Since we don't use Alembic, we add
# any missing ones in place so an existing DB file keeps working after upgrade.
_ADDED_COLUMNS = {
    "settings": [("team_name", "VARCHAR DEFAULT 'My Team'")],
    "sprint": [
        ("archived", "BOOLEAN DEFAULT 0"),
        ("jira_sprint_id", "INTEGER"),
        ("label", "VARCHAR DEFAULT ''"),
    ],
}


# One-off column renames: (table, old, new). SQLite >= 3.25 supports RENAME COLUMN.
_RENAMED_COLUMNS = [
    ("teammember", "is_orchestration", "is_excluded"),
]


def _rename_columns(engine: Engine) -> None:
    """Apply pending column renames idempotently (old present, new absent)."""
    with engine.begin() as conn:
        for table, old, new in _RENAMED_COLUMNS:
            cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if old in cols and new not in cols:
                conn.exec_driver_sql(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")


def _ensure_columns(engine: Engine) -> None:
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, decl in columns:
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _backfill_sprint_labels(engine: Engine) -> None:
    """Populate Sprint.label from the id for rows created before label existed.
    Idempotent: once labels are set this UPDATE matches nothing."""
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE sprint SET label = id WHERE label IS NULL OR label = ''"
        )


# Higher wins when the same (member, day) carried two types in legacy data.
# NOTE: mirrors time_off_service.TYPE_PRIORITY (kept in sync by hand; the engine
# layer can't import the service layer). Update both together.
_TYPE_PRIORITY = {"company": 4, "holiday": 3, "pto": 2, "partial": 1, "tentative": 0}


def _migrate_legacy_timeoff(engine: Engine, *, pre_existing: set[str]) -> None:
    """Flatten legacy TimeOff+TimeOffDay into MemberDayOff, then drop them.

    ``pre_existing`` is the set of table names that existed BEFORE create_all
    was called.  The migration runs only when the DB was in the old schema:
    timeoff + timeoffday were present before create_all but memberdayoff was
    not (i.e. a genuine pre-migration install).  Idempotent thereafter.
    """
    if "memberdayoff" in pre_existing:
        return  # already migrated (or fresh install that previously ran)
    if "timeoff" not in pre_existing or "timeoffday" not in pre_existing:
        return  # fresh install — tables were just created by create_all, no legacy data
    with engine.begin() as conn:
        rows = conn.exec_driver_sql(
            "SELECT t.member_id, d.date, t.type, t.notes "
            "FROM timeoff t JOIN timeoffday d ON d.time_off_id = t.id"
        ).fetchall()
        best: dict[tuple, tuple[str, str]] = {}
        for member_id, dt, type_, notes in rows:
            key = (member_id, dt)
            cur = best.get(key)
            if cur is None or _TYPE_PRIORITY.get(type_, 0) > _TYPE_PRIORITY.get(cur[0], 0):
                # Winner takes its own type; keep any existing note if it has none.
                best[key] = (type_, notes or (cur[1] if cur else ""))
            elif not cur[1] and notes:
                best[key] = (cur[0], notes)
        for (member_id, dt), (type_, notes) in best.items():
            conn.exec_driver_sql(
                "INSERT OR IGNORE INTO memberdayoff (member_id, date, type, notes) "
                "VALUES (?, ?, ?, ?)", (member_id, dt, type_, notes or ""))
        conn.exec_driver_sql("DROP TABLE timeoffday")
        conn.exec_driver_sql("DROP TABLE timeoff")


def create_db_and_tables(engine: Engine) -> None:
    # Correct any pre-rename schema FIRST so create_all (which never alters an
    # existing table) and every later step see the renamed columns. No-op on a
    # fresh DB (the table doesn't exist yet) and on a second run (old absent).
    _rename_columns(engine)
    # Snapshot table names BEFORE create_all so the migration can distinguish
    # a genuine legacy install (old tables present, memberdayoff absent) from a
    # fresh install (all tables created simultaneously by create_all).
    with engine.connect() as conn:
        pre_existing = {row[0] for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    SQLModel.metadata.create_all(engine)
    _ensure_columns(engine)
    _backfill_sprint_labels(engine)
    _migrate_legacy_timeoff(engine, pre_existing=pre_existing)
    from sprint_pulse.services.type_service import seed_default_types
    with Session(engine) as s:
        seed_default_types(s)
        s.commit()


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Transactional session: commit on success, rollback on error."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
