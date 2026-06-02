"""Setup wizard flow + YAML import path."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from sprint_pulse.web.app import create_app


@pytest.fixture
def client():
    app = create_app(":memory:")
    return TestClient(app)


def test_welcome_shown_when_empty(client):
    r = client.get("/setup")
    assert r.status_code == 200
    assert "Welcome to Sprint Pulse" in r.text


def test_wizard_step1_saves_settings(client):
    r = client.post(
        "/setup/wizard",
        data={
            "working_days_per_sprint": "8",
            "jira_site": "x.atlassian.net",
            "jira_board": "42",
            "jira_username": "me@x.com",
            "jira_token": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/sprints/import?wizard=1"  # step 2 = import
    # team page (step 3) still reachable
    assert client.get("/setup/team").status_code == 200


def test_wizard_add_member_then_dashboard(client):
    client.post("/setup/wizard", data={"working_days_per_sprint": "10"}, follow_redirects=False)
    r = client.post("/setup/team/add", data={"name": "Jane Doe"})
    assert r.status_code == 200
    assert "Jane Doe" in r.text
    # now the DB is non-empty: setup redirects to dashboard
    assert client.get("/setup", follow_redirects=False).status_code == 303


def test_wizard_test_connection_handles_unreachable(client):
    from sprint_pulse.jira import JiraUnavailable

    fake = type("F", (), {"fetch_sprints": lambda self: (_ for _ in ()).throw(
        JiraUnavailable("boom"))})()
    with patch("sprint_pulse.services.jira_service.JiraClient", return_value=fake):
        r = client.post(
            "/setup/wizard/test",
            data={
                "jira_site": "x.atlassian.net",
                "jira_board": "1",
                "jira_username": "me@x.com",
                "jira_token": "tok",
            },
        )
    assert r.status_code == 200
    assert "Could not reach Jira" in r.text


def test_wizard_test_connection_success(client):
    fake = type("F", (), {"fetch_sprints": lambda self: {"Wisdom 2026-16": {}}})()
    with patch("sprint_pulse.services.jira_service.JiraClient", return_value=fake):
        r = client.post(
            "/setup/wizard/test",
            data={
                "jira_site": "x.atlassian.net",
                "jira_board": "1",
                "jira_username": "me@x.com",
                "jira_token": "tok",
            },
        )
    assert "Connected" in r.text


def test_wizard_import_step_offers_skip_when_jira_absent(client, monkeypatch):
    from sprint_pulse.services import jira_service
    monkeypatch.setattr(jira_service, "make_client", lambda s: None)
    r = client.get("/sprints/import?wizard=1")
    assert r.status_code == 200
    assert "Step 2 of 3" in r.text
    assert "Skip → add your team" in r.text


def test_wizard_import_continues_to_team(client, monkeypatch):
    from datetime import date

    from sprint_pulse.services import jira_service

    class _Client:
        def fetch_sprints(self):
            return {"Wisdom 2026-16": {"id": 9, "state": "active",
                                       "start": date(2026, 4, 16), "end": date(2026, 4, 29)}}

    monkeypatch.setattr(jira_service, "make_client", lambda s: _Client())
    r = client.post(
        "/sprints/import",
        data={"wizard": "1", "action": "selected", "jira_ids": "9", "id_9": "2026-16"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/setup/team"  # wizard advances to step 3


def test_team_step_back_link_only_without_sprints(client):
    from datetime import date

    from sprint_pulse.db.engine import session_scope
    from sprint_pulse.services import sprint_service as spsvc

    # No sprints yet → team step offers to go back to import.
    assert "Back to import sprints" in client.get("/setup/team").text

    with session_scope(client.app.state.engine) as s:
        spsvc.create_sprint(s, "2026-16", date(2026, 4, 16), date(2026, 4, 29))
    # Now that a sprint exists, the back-to-import nudge is gone.
    assert "Back to import sprints" not in client.get("/setup/team").text


def test_yaml_import_populates_db(client):
    r = client.post("/setup/import", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    # dashboard now renders (the bundled data has sprints)
    assert "Wisdom Team" in client.get("/").text
