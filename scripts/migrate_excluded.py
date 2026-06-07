"""One-time: rename teammember.is_orchestration -> is_excluded on a Sprint Pulse
DB, backing it up first, then create+seed the new type tables. Idempotent.

Usage:  python scripts/migrate_excluded.py        # migrates the live DB
"""
from __future__ import annotations

import shutil
from pathlib import Path

from sprint_pulse.db.engine import create_db_and_tables, default_db_path, get_engine


def migrate_db(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        print(f"No DB at {path}; nothing to migrate (a fresh DB is created on first run).")
        return
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    print(f"Backed up {path} -> {backup}")

    engine = get_engine(path)
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(teammember)")}
        if "is_orchestration" in cols and "is_excluded" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE teammember RENAME COLUMN is_orchestration TO is_excluded"
            )
            print("Renamed is_orchestration -> is_excluded")
        elif "is_excluded" in cols:
            print("Column already renamed; skipping rename.")
        else:
            print("WARNING: teammember has neither is_orchestration nor is_excluded; check schema.")

    create_db_and_tables(engine)  # creates + seeds EventType/AbsenceType (idempotent)
    print("Ensured + seeded type tables. Done.")


def main() -> None:
    migrate_db(default_db_path())


if __name__ == "__main__":
    main()
