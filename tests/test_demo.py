"""Demo mode (SPRINT_PULSE_DEMO=1, mock Jira) + example YAML data."""
from pathlib import Path

import pytest
from sqlmodel import select

from sprint_pulse.db import models as m
from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
from sprint_pulse.migrate import import_yaml
from sprint_pulse.services import config_service, jira_service, sprint_service
from sprint_pulse.services.mock_jira import MockJiraClient

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


# --- mock client ------------------------------------------------------------

def test_mock_client_shapes():
    c = MockJiraClient("Demo")
    sprints = c.fetch_sprints()
    assert "Demo 2026-16" in sprints
    one = sprints["Demo 2026-16"]
    assert set(one) == {"id", "state", "start", "end"}
    metrics = c.fetch_metrics(one["id"])
    assert set(metrics) == {"done_n", "tot_n", "done_sp", "tot_sp"}
    assert metrics["done_n"] <= metrics["tot_n"]


# --- make_client / probe honor the flag -------------------------------------

@pytest.fixture
def engine():
    eng = get_engine(":memory:")
    create_db_and_tables(eng)
    return eng


def test_make_client_returns_mock_in_demo_mode(engine, monkeypatch):
    monkeypatch.setenv("SPRINT_PULSE_DEMO", "1")
    with session_scope(engine) as s:
        # No Jira creds configured at all, yet we still get a working client.
        assert isinstance(jira_service.make_client(s), MockJiraClient)


def test_make_client_none_without_demo_or_creds(engine, monkeypatch):
    monkeypatch.delenv("SPRINT_PULSE_DEMO", raising=False)
    with session_scope(engine) as s:
        assert jira_service.make_client(s) is None


def test_probe_ok_in_demo_mode(monkeypatch):
    monkeypatch.setenv("SPRINT_PULSE_DEMO", "1")
    msg, ok = jira_service.probe("", "", "", None)  # no creds needed in demo
    assert ok and "demo" in msg.lower()


def test_available_sprints_use_mock_in_demo(engine, monkeypatch):
    monkeypatch.setenv("SPRINT_PULSE_DEMO", "1")
    with session_scope(engine) as s:
        candidates, error = sprint_service.available_jira_sprints(s)
    assert error == ""
    assert {c["suggested_id"] for c in candidates} >= {"2026-16", "2026-28"}  # mock board sprints


# --- example data imports ---------------------------------------------------

def test_examples_import(engine):
    counts = import_yaml(engine, EXAMPLES / "config.yaml", EXAMPLES / "sprints")
    assert counts["members"] == 6
    assert counts["orchestration"] == 2
    assert counts["sprints"] == 3
    with session_scope(engine) as s:
        cfg = config_service.build_config_from_db(s)
        names = {member.name for member in s.exec(select(m.TeamMember)).all()}
    assert cfg.team_name == "Demo"          # example sets a custom team name
    assert "Alice Anderson" in names
