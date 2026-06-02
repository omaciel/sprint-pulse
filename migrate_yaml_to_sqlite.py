#!/usr/bin/env python3
"""One-time import of data/config.yaml + data/sprints/*.yaml into SQLite.

Usage:
  python3 migrate_yaml_to_sqlite.py [--db PATH] [--data DIR] [--force]

With no --db, the platform default location is used (see db/engine.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sprint_pulse.db.engine import default_db_path, get_engine
from sprint_pulse.migrate import MigrationError, import_yaml

PROJECT_ROOT = Path(__file__).parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="SQLite path (default: platform data dir)")
    parser.add_argument("--data", default=str(PROJECT_ROOT / "data"), help="data/ directory")
    parser.add_argument("--force", action="store_true", help="overwrite a populated DB")
    args = parser.parse_args()

    data_dir = Path(args.data)
    config_path = data_dir / "config.yaml"
    sprints_dir = data_dir / "sprints"
    db_path = Path(args.db) if args.db else default_db_path()

    print(f"Importing {config_path} + {sprints_dir} -> {db_path}")
    engine = get_engine(db_path)
    try:
        counts = import_yaml(engine, config_path, sprints_dir, force=args.force)
    except MigrationError as e:
        sys.exit(f"Refused: {e}")

    print("Imported:")
    for key, val in counts.items():
        print(f"  {key:16} {val}")


if __name__ == "__main__":
    main()
