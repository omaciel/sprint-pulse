from datetime import date


def _make_old_db(path):
    """Create a sqlite DB at `path` with the pre-rename teammember schema
    (is_orchestration column) and one member row."""
    import sqlite3
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE teammember (id INTEGER PRIMARY KEY, name VARCHAR, "
        "is_orchestration BOOLEAN DEFAULT 0, sort_order INTEGER DEFAULT 0);"
        "INSERT INTO teammember (id, name, is_orchestration) VALUES (1, 'Alice', 1);"
    )
    conn.commit()
    conn.close()


def test_migrate_renames_column_and_seeds(tmp_path):
    from scripts.migrate_excluded import migrate_db
    db = tmp_path / "sprint-pulse.db"
    _make_old_db(str(db))
    migrate_db(db)  # backup + rename + create_db_and_tables(seed)
    # backup created
    assert (tmp_path / "sprint-pulse.db.bak").exists()
    import sqlite3
    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(teammember)")}
    assert "is_excluded" in cols and "is_orchestration" not in cols
    # member's flag preserved (renamed column kept the value)
    val = conn.execute("SELECT is_excluded FROM teammember WHERE id=1").fetchone()[0]
    assert val == 1
    # type tables created + seeded
    et = {r[0] for r in conn.execute("SELECT key FROM eventtype")}
    at = {r[0] for r in conn.execute("SELECT key FROM absencetype")}
    conn.close()
    assert "ga" in et and "pto" in at


def test_migrate_is_idempotent_on_already_migrated(tmp_path):
    from scripts.migrate_excluded import migrate_db
    db = tmp_path / "sprint-pulse.db"
    _make_old_db(str(db))
    migrate_db(db)
    # second run must not error and must keep is_excluded
    migrate_db(db)
    import sqlite3
    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(teammember)")}
    conn.close()
    assert "is_excluded" in cols and "is_orchestration" not in cols
