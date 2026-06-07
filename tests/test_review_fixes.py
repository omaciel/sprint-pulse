"""Regression tests for the code-review findings."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from sprint_pulse.config import Config, JiraConfig
from sprint_pulse.db import models as m
from sprint_pulse.db.engine import get_engine, session_scope
from sprint_pulse.errors import ValidationError
from sprint_pulse.migrate import import_yaml
from sprint_pulse.render import render_full_html, render_sprint
from sprint_pulse.services import config_service as cfgsvc
from sprint_pulse.services import jira_service
from sprint_pulse.services import sprint_service as spsvc
from sprint_pulse.sprints import Sprint, TimeOffEntry
from sprint_pulse.web.app import create_app


def _cfg(team_name="Wisdom"):
    return Config(
        working_days_per_sprint=10,
        jira=JiraConfig(site="x", board="1"),
        roster=["Alice Anderson", "Grace Hughes"],
        excluded={"Grace Hughes"},
        name_aliases={},
        team_name=team_name,
    )


# --- #1/#2: HTML escaping (stored XSS) --------------------------------------

def test_member_name_is_escaped_in_render():
    cfg = Config(
        working_days_per_sprint=10,
        jira=JiraConfig(site="x", board="1"),
        roster=["<script>alert(1)</script>", "Grace Hughes"],
        excluded={"Grace Hughes"},
        name_aliases={},
    )
    sprint = Sprint(id="2026-16", start=date(2026, 4, 16), end=date(2026, 4, 29),
                    events=(), time_off=())
    html, _ = render_sprint(sprint, cfg, {"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}, "future")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_notes_are_escaped_in_render():
    cfg = _cfg()
    sprint = Sprint(
        id="2026-16", start=date(2026, 4, 16), end=date(2026, 4, 29), events=(),
        time_off=(TimeOffEntry(associate="Alice Anderson", days=(date(2026, 4, 24),),
                               notes='</td><script>x</script>', type="pto"),),
    )
    html, _ = render_sprint(sprint, cfg, {"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}, "future")
    assert "<script>x</script>" not in html


# --- #3: sprint id must be int-parseable (renderer crash guard) -------------

def test_create_sprint_slugifies_unsafe_labels():
    """Labels need not be URL-safe; the service derives a safe slug id."""
    from sprint_pulse.db.engine import create_db_and_tables
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        row = spsvc.create_sprint(s, "Q1 sprint", date(2026, 4, 16), date(2026, 4, 29))
        assert row.id == "q1-sprint"
        assert row.label == "Q1 sprint"
    with session_scope(engine) as s:
        row = spsvc.create_sprint(s, "a/b", date(2026, 5, 14), date(2026, 5, 27))
        assert row.id == "a-b"


def test_create_sprint_accepts_non_numeric_safe_id():
    """Sorting is by date now, so a non-numeric label like '2026-Q1' is fine;
    the derived slug id is lowercased ('2026-q1')."""
    from sprint_pulse.db.engine import create_db_and_tables
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        row = spsvc.create_sprint(s, "2026-Q1", date(2026, 4, 16), date(2026, 4, 29))
        assert row.id == "2026-q1"
        assert row.label == "2026-Q1"
        assert s.get(m.Sprint, "2026-q1")


def test_dashboard_survives_after_valid_ids_only(valid_dir):
    # render_full_html sorts by int(id parts); ensure DB ids stay parseable.
    cfg = _cfg()
    sprints = [
        Sprint(id="2026-16", start=date(2026, 4, 16), end=date(2026, 4, 29), events=(), time_off=()),
    ]
    data = [(sprints[0], {"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}, "active")]
    assert "2026-16" in render_full_html(data, cfg)


# --- #4: configurable team prefix; #5: honest refresh status ----------------

class _FakeClient:
    def __init__(self, names):
        self._names = names

    def fetch_sprints(self):
        return {n: {"id": 1, "state": "active"} for n in self._names}

    def fetch_metrics(self, sprint_id):
        return {"done_n": 1, "tot_n": 2, "done_sp": 3, "tot_sp": 4}


@pytest.fixture
def seeded_engine(valid_dir):
    eng = get_engine(":memory:")
    import_yaml(eng, valid_dir / "config.yaml", valid_dir / "sprints_dir")
    return eng


def test_refresh_uses_configured_prefix(seeded_engine, monkeypatch):
    from sprint_pulse.services import refresh
    with session_scope(seeded_engine) as s:
        cfgsvc.update_settings(s, team_name="Galaxy")
    # Jira board names sprints "Galaxy 2026-16" etc.
    monkeypatch.setattr(
        jira_service, "make_client",
        lambda s: _FakeClient(["Galaxy 2026-16", "Galaxy 2026-18"]),
    )
    with session_scope(seeded_engine) as s:
        result = refresh.refresh_all(s)
    assert result["status"] == "ok"
    assert result["updated"] == 2


def test_refresh_zero_match_is_ok_not_error(seeded_engine, monkeypatch):
    from sprint_pulse.services import refresh
    # Default prefix "Wisdom" but board returns names that match nothing.
    monkeypatch.setattr(jira_service, "make_client", lambda s: _FakeClient(["WIS 2026-16"]))
    with session_scope(seeded_engine) as s:
        result = refresh.refresh_all(s)
    assert result["status"] == "ok"
    assert result["updated"] == 0
    assert "matching" in result["log"].lower()


# --- #6: scheduler error is URL-encoded -------------------------------------

def test_scheduler_invalid_cron_redirect_is_encoded():
    client = TestClient(create_app(":memory:"))
    r = client.post(
        "/scheduler",
        data={"enabled": "true", "trigger": "cron", "value": "not a cron"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    loc = r.headers["location"]
    assert " " not in loc  # spaces encoded
    assert loc.startswith("/scheduler?error=")


# --- Jira site normalization (pasted full URL) ------------------------------

def test_normalize_site_strips_scheme_and_path():
    from sprint_pulse.config import normalize_site
    assert normalize_site("https://acme.atlassian.net") == "acme.atlassian.net"
    assert normalize_site("https://acme.atlassian.net/") == "acme.atlassian.net"
    assert normalize_site("http://acme.atlassian.net/jira/x") == "acme.atlassian.net"
    assert normalize_site("acme.atlassian.net") == "acme.atlassian.net"


def test_jiraconfig_normalizes_site():
    assert JiraConfig(site="https://acme.atlassian.net/", board="1").site == "acme.atlassian.net"


def test_apply_jira_settings_stores_bare_host():
    engine = get_engine(":memory:")
    from sprint_pulse.db.engine import create_db_and_tables
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        cfgsvc.apply_jira_settings(
            s, jira_site="https://acme.atlassian.net/", jira_board="1", jira_username="me@x.com"
        )
    with session_scope(engine) as s:
        assert cfgsvc.get_settings(s).jira_site == "acme.atlassian.net"


# --- #7: sort_order stable after remove+add ---------------------------------

def test_add_member_after_remove_no_sortorder_collision(seeded_engine):
    from sqlmodel import select
    with session_scope(seeded_engine) as s:
        member = s.exec(select(m.TeamMember).where(m.TeamMember.name == "Mei Lin")).one()
        cfgsvc.remove_member(s, member.id)
    with session_scope(seeded_engine) as s:
        cfgsvc.add_member(s, "Zoe New")
    with session_scope(seeded_engine) as s:
        orders = [mem.sort_order for mem in cfgsvc.list_members(s)]
    assert len(orders) == len(set(orders)), "sort_order values must stay unique"
