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
    "settings": [("team_name", "VARCHAR DEFAULT 'Wisdom'")],
    "sprint": [("archived", "BOOLEAN DEFAULT 0"), ("jira_sprint_id", "INTEGER")],
}


def _ensure_columns(engine: Engine) -> None:
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, decl in columns:
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def create_db_and_tables(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    _ensure_columns(engine)


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
