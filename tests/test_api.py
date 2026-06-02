"""FastAPI route tests (TestClient over an in-memory DB)."""

import pytest
from fastapi.testclient import TestClient

from sprint_pulse.db.engine import session_scope
from sprint_pulse.migrate import import_yaml
from sprint_pulse.web.app import create_app


@pytest.fixture
def empty_client():
    app = create_app(":memory:")
    return TestClient(app)


@pytest.fixture
def seeded_client(valid_dir):
    app = create_app(":memory:")
    import_yaml(
        app.state.engine, valid_dir / "config.yaml", valid_dir / "sprints_dir"
    )
    return TestClient(app)


def test_health(empty_client):
    r = empty_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_empty_db_redirects_to_setup(empty_client):
    r = empty_client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/setup"


def test_dashboard_renders_when_seeded(seeded_client):
    r = seeded_client.get("/")
    assert r.status_code == 200
    assert "Wisdom Team" in r.text
    assert "Sprint Pulse" in r.text  # the injected app-bar


def test_dashboard_renders_with_sprints_but_no_team(empty_client):
    from datetime import date

    from sprint_pulse.db.engine import session_scope
    from sprint_pulse.services import sprint_service as spsvc

    with session_scope(empty_client.app.state.engine) as s:
        spsvc.create_sprint(s, "2026-16", date(2026, 4, 16), date(2026, 4, 29))
    r = empty_client.get("/")
    assert r.status_code == 200          # not redirected to /setup
    assert "2026-16" in r.text
    assert "n/a" in r.text               # availability with an empty roster


def test_members_page_lists_roster(seeded_client):
    r = seeded_client.get("/members")
    assert r.status_code == 200
    assert "Alice Anderson" in r.text


def test_add_member_returns_updated_table(seeded_client):
    r = seeded_client.post("/members", data={"name": "Brand New"})
    assert r.status_code == 200
    assert "Brand New" in r.text


def test_add_duplicate_member_shows_error(seeded_client):
    r = seeded_client.post("/members", data={"name": "Alice Anderson"})
    assert r.status_code == 200
    assert "already on the roster" in r.text


def test_delete_member(seeded_client):
    # find Tami's id via the config service
    from sqlmodel import select
    from sprint_pulse.db import models as m

    with session_scope(seeded_client.app.state.engine) as s:
        mid = s.exec(select(m.TeamMember).where(m.TeamMember.name == "Jack Kelly")).one().id
    r = seeded_client.post(f"/members/{mid}/delete")
    assert r.status_code == 200
    assert "Jack Kelly" not in r.text


def test_sprint_detail_renders(seeded_client):
    r = seeded_client.get("/sprints/2026-16")
    assert r.status_code == 200
    assert "Sprint 2026-16" in r.text


def test_add_time_off_invalid_day_shows_error(seeded_client):
    r = seeded_client.post(
        "/sprints/2026-16/timeoff",
        data={
            "associate": "Alice Anderson",
            "start": "2026-12-25",
            "end": "2026-12-25",
            "notes": "PTO",
        },
    )
    assert r.status_code == 200
    assert "outside sprint range" in r.text


def test_add_time_off_unknown_associate_suggests(seeded_client):
    r = seeded_client.post(
        "/sprints/2026-16/timeoff",
        data={
            "associate": "Alice Andersen",
            "start": "2026-04-17",
            "end": "2026-04-17",
            "notes": "PTO",
        },
    )
    assert r.status_code == 200
    assert "did you mean" in r.text


def test_add_event_then_appears(seeded_client):
    r = seeded_client.post(
        "/sprints/2026-16/events",
        data={"event_date": "2026-04-17", "kind": "ga", "title": "Test Release"},
    )
    assert r.status_code == 200
    assert "Test Release" in r.text


def test_config_save_roundtrip(seeded_client):
    r = seeded_client.post(
        "/config",
        data={
            "working_days_per_sprint": "9",
            "jira_site": "x.atlassian.net",
            "jira_board": "999",
            "jira_username": "me@x.com",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    page = seeded_client.get("/config")
    assert "999" in page.text
    assert "me@x.com" in page.text


def test_scheduler_page_shows_busy_affordances(empty_client):
    html = empty_client.get("/scheduler").text
    assert "hx-disabled-elt" in html      # button disables itself during the request
    assert "Refreshing" in html           # spinner/indicator text
    assert "spinner" in html              # spinner element


def test_run_now_without_jira_returns_error_status(empty_client):
    r = empty_client.post("/scheduler/run")
    assert r.status_code == 200
    assert 'pill error' in r.text         # error pill rendered
    assert "not" in r.text.lower()        # "...not configured"
