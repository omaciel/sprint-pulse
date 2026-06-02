"""Import sprints from Jira + archive/unarchive."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from sprint_pulse.db import models as m
from sprint_pulse.db.engine import get_engine, session_scope
from sprint_pulse.migrate import import_yaml
from sprint_pulse.services import jira_service
from sprint_pulse.services import sprint_service as spsvc
from sprint_pulse.web.app import create_app


class FakeClient:
    """Board with mixed names: a prefix match, a non-prefix name (still listed),
    a dateless one, and an odd name with no derivable id."""

    def fetch_sprints(self):
        return {
            "Wisdom 2026-20": {"id": 2, "state": "active",
                               "start": date(2026, 5, 14), "end": date(2026, 5, 27)},
            "Wisdom 2026-28": {"id": 3, "state": "future", "start": None, "end": None},
            "Galaxy 2026-30": {"id": 4, "state": "future",
                               "start": date(2026, 6, 11), "end": date(2026, 6, 24)},
            "Sprint Forty Two": {"id": 5, "state": "future",
                                 "start": date(2026, 6, 25), "end": date(2026, 7, 8)},
        }

    def fetch_metrics(self, sprint_id):
        return {"done_n": 1, "tot_n": 2, "done_sp": 3, "tot_sp": 4}


@pytest.fixture
def engine(valid_dir):
    eng = get_engine(":memory:")
    import_yaml(eng, valid_dir / "config.yaml", valid_dir / "sprints_dir")  # has 2026-16, 2026-18
    return eng


# --- candidate listing ------------------------------------------------------

def test_available_lists_all_board_sprints_with_flags(engine, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: FakeClient())
    with session_scope(engine) as s:
        candidates, error = spsvc.available_jira_sprints(s)
    assert error == ""
    by_jira = {c["jira_id"]: c for c in candidates}
    # ALL board sprints listed now, regardless of name.
    assert set(by_jira) == {2, 3, 4, 5}
    assert by_jira[2]["suggested_id"] == "2026-20"          # prefix match
    assert by_jira[4]["suggested_id"] == "2026-30"          # id embedded in non-prefix name
    assert by_jira[5]["suggested_id"] == "Sprint-Forty-Two" # slug of the whole name
    assert by_jira[3]["importable"] is False                # no Jira dates


def test_available_without_jira_returns_error(engine, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: None)
    with session_scope(engine) as s:
        candidates, error = spsvc.available_jira_sprints(s)
    assert candidates is None
    assert "not configured" in error


# --- importing --------------------------------------------------------------

def test_import_stores_jira_id_and_skips_bad(engine, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: FakeClient())
    with session_scope(engine) as s:
        # jira 2 -> good; jira 3 -> no dates (skip); jira 5 -> id has a space (skip)
        result = spsvc.import_jira_sprints(
            s, [(2, "2026-20"), (3, "2026-28"), (5, "forty two")]
        )
    assert result["imported"] == 1
    assert set(result["skipped"]) == {"2026-28", "forty two"}
    with session_scope(engine) as s:
        row = s.get(m.Sprint, "2026-20")
        assert row.start == date(2026, 5, 14)
        assert row.jira_state == "active"
        assert row.jira_sprint_id == 2


def test_reimport_skips_and_preserves_existing(engine, monkeypatch):
    """Re-importing an already-imported sprint does not overwrite it: it's
    skipped, and its events/time-off are left intact."""
    monkeypatch.setattr(jira_service, "make_client", lambda s: FakeClient())
    with session_scope(engine) as s:
        spsvc.import_jira_sprints(s, [(2, "2026-20")])           # first import
        spsvc.add_event(s, "2026-20", date(2026, 5, 14), "ga", "Local edit")
    with session_scope(engine) as s:
        result = spsvc.import_jira_sprints(s, [(2, "2026-20")])  # re-import same one
    assert result["imported"] == 0
    assert result["skipped"] == ["2026-20"]
    with session_scope(engine) as s:
        titles = [
            e.title
            for e in s.exec(select(m.Event).where(m.Event.sprint_id == "2026-20")).all()
        ]
    assert titles == ["Local edit"]  # untouched


def test_import_non_prefixed_name_with_chosen_id(engine, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: FakeClient())
    with session_scope(engine) as s:
        # "Galaxy 2026-30" (jira id 4) imported under a user-chosen id
        result = spsvc.import_jira_sprints(s, [(4, "2026-30")])
    assert result["imported"] == 1
    with session_scope(engine) as s:
        assert s.get(m.Sprint, "2026-30").jira_sprint_id == 4


# --- archive / dashboard exclusion -----------------------------------------

def test_archive_hides_from_dashboard(engine):
    with session_scope(engine) as s:
        spsvc.set_archived(s, "2026-16", True)
    with session_scope(engine) as s:
        ids = [sp.id for sp, _, _ in spsvc.build_dashboard_data(s)]
    assert "2026-16" not in ids
    assert "2026-18" in ids


def test_refresh_matches_by_stored_jira_id(engine, monkeypatch):
    from sprint_pulse.services import refresh
    monkeypatch.setattr(jira_service, "make_client", lambda s: FakeClient())
    with session_scope(engine) as s:
        # "Galaxy 2026-30" doesn't match the "Wisdom " prefix; imported by id 4.
        spsvc.import_jira_sprints(s, [(4, "2026-30")])
    with session_scope(engine) as s:
        refresh.refresh_all(s)
    with session_scope(engine) as s:
        row = s.get(m.Sprint, "2026-30")
        values = (row.done_n, row.tot_n, row.jira_state)
    assert values == (1, 2, "future")


def test_unarchive_restores(engine):
    with session_scope(engine) as s:
        spsvc.set_archived(s, "2026-16", True)
        spsvc.set_archived(s, "2026-16", False)
    with session_scope(engine) as s:
        ids = [sp.id for sp, _, _ in spsvc.build_dashboard_data(s)]
    assert "2026-16" in ids


# --- routes -----------------------------------------------------------------

class ManyClient:
    """30 importable sprints, for pagination / import-all tests."""

    def fetch_sprints(self):
        return {
            f"Wisdom 2026-{i:02d}": {"id": 100 + i, "state": "future",
                                     "start": date(2026, 1, 1), "end": date(2026, 1, 14)}
            for i in range(1, 31)
        }

    def fetch_metrics(self, sprint_id):
        return {"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}


@pytest.fixture
def client(valid_dir):
    app = create_app(":memory:")
    import_yaml(app.state.engine, valid_dir / "config.yaml", valid_dir / "sprints_dir")
    return TestClient(app)


@pytest.fixture
def fresh_client():
    """Empty DB (no sprints yet) for clean import-count assertions."""
    return TestClient(create_app(":memory:"))


def test_import_page_shows_candidates(client, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: FakeClient())
    r = client.get("/sprints/import")
    assert r.status_code == 200
    assert "2026-20" in r.text


def test_import_route_imports_selected(client, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: FakeClient())
    r = client.post(
        "/sprints/import",
        data={"jira_ids": ["2"], "id_2": "2026-20"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "2026-20" in client.get("/sprints").text


def test_archive_route_moves_to_archived_section(client):
    r = client.post("/sprints/2026-16/archive", follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/sprints").text
    assert "Unarchive" in page  # archived section rendered


# --- import page: pagination / select-all / empty selection -----------------

def test_import_page_paginates(fresh_client, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: ManyClient())
    p1 = fresh_client.get("/sprints/import")
    assert "Showing 1–25 of 30" in p1.text
    assert "page 1/2" in p1.text
    p2 = fresh_client.get("/sprints/import?page=2")
    assert "Showing 26–30 of 30" in p2.text


def test_import_rows_unchecked_by_default(fresh_client, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: ManyClient())
    html = fresh_client.get("/sprints/import").text
    # the per-row checkbox must not be pre-checked
    assert 'class="pick" name="jira_ids"' in html
    assert "checked" not in html.split("<tbody>")[1].split("</tbody>")[0]


def test_import_none_selected_redirects_with_notice(fresh_client, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: ManyClient())
    r = fresh_client.post("/sprints/import", data={}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/sprints/import?notice=none"
    assert "No sprints were selected" in fresh_client.get("/sprints/import?notice=none").text


def test_import_all_importable(fresh_client, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: ManyClient())
    r = fresh_client.post("/sprints/import", data={"action": "all"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/sprints"
    with session_scope(fresh_client.app.state.engine) as s:
        from sqlmodel import select as _select
        assert len(s.exec(_select(m.Sprint)).all()) == 30


# --- ordering is by date, not id -------------------------------------------

def test_sprints_ordered_by_date_not_id():
    from sprint_pulse.db.engine import create_db_and_tables
    eng = get_engine(":memory:")
    create_db_and_tables(eng)
    with session_scope(eng) as s:
        # "zzz" has the earlier dates, "aaa" the later — opposite of id order.
        spsvc.create_sprint(s, "zzz", date(2026, 1, 5), date(2026, 1, 16))
        spsvc.create_sprint(s, "aaa", date(2026, 3, 2), date(2026, 3, 13))
    with session_scope(eng) as s:
        ids = [sp.id for sp in spsvc.build_sprints_from_db(s)]
    assert ids == ["zzz", "aaa"]  # ascending by start date, ignoring the id string


# --- upgrade path: existing DB gains new columns ----------------------------

def test_ensure_columns_adds_archived_to_old_db(tmp_path):
    from sprint_pulse.db.engine import create_db_and_tables, get_engine

    db = tmp_path / "old.db"
    eng = get_engine(db)
    # Simulate a pre-upgrade DB whose sprint table lacks the new column.
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE sprint (id VARCHAR PRIMARY KEY)")
    create_db_and_tables(eng)  # create_all skips the existing table; _ensure_columns ALTERs it
    with eng.begin() as c:
        cols = {row[1] for row in c.exec_driver_sql("PRAGMA table_info(sprint)")}
    assert "archived" in cols
