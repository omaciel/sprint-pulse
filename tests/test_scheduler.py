"""Scheduler + refresh pipeline (fake Jira client, no background thread)."""
import pytest

from sprint_pulse.db import models as m
from sprint_pulse.db.engine import get_engine, session_scope
from sprint_pulse.errors import ValidationError
from sprint_pulse.jira import JiraUnavailable
from sprint_pulse.migrate import import_yaml
from sprint_pulse.services import config_service, jira_service
from sprint_pulse.web.scheduler import SchedulerManager, build_trigger


class FakeClient:
    def fetch_sprints(self):
        return {
            "My Team 2026-16": {"id": 100, "state": "active"},
            "My Team 2026-18": {"id": 101, "state": "closed"},
        }

    def fetch_metrics(self, sprint_id):
        return {"done_n": 5, "tot_n": 68, "done_sp": 11, "tot_sp": 153}


class UnreachableClient:
    def fetch_sprints(self):
        raise JiraUnavailable("network down")


@pytest.fixture
def engine(valid_dir):
    eng = get_engine(":memory:")
    import_yaml(eng, valid_dir / "config.yaml", valid_dir / "sprints_dir")
    return eng


# --- build_trigger ----------------------------------------------------------

def test_build_trigger_interval():
    assert build_trigger("interval", "30") is not None


@pytest.mark.parametrize("value", ["0", "-5", "abc"])
def test_build_trigger_interval_invalid(value):
    with pytest.raises(ValidationError):
        build_trigger("interval", value)


def test_build_trigger_cron():
    assert build_trigger("cron", "0 7 * * 1-5") is not None


def test_build_trigger_cron_invalid():
    with pytest.raises(ValidationError):
        build_trigger("cron", "not a cron")


def test_build_trigger_unknown():
    with pytest.raises(ValidationError):
        build_trigger("hourly", "1")


# --- refresh via run_now ----------------------------------------------------

def test_run_now_updates_cache(engine, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: FakeClient())
    result = SchedulerManager(engine).run_now()
    assert result["status"] == "ok"
    assert result["updated"] == 2
    with session_scope(engine) as s:
        row = s.get(m.Sprint, "2026-16")
        assert (row.done_n, row.tot_n, row.jira_state) == (5, 68, "active")
        settings = config_service.get_settings(s)
        assert settings.last_status == "ok"


def test_run_now_without_jira_sets_error(engine, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: None)
    result = SchedulerManager(engine).run_now()
    assert result["status"] == "error"
    with session_scope(engine) as s:
        assert config_service.get_settings(s).last_status == "error"


def test_run_now_unreachable_mentions_vpn(engine, monkeypatch):
    monkeypatch.setattr(jira_service, "make_client", lambda s: UnreachableClient())
    SchedulerManager(engine).run_now()
    with session_scope(engine) as s:
        assert "VPN" in config_service.get_settings(s).last_log


# --- reschedule persistence -------------------------------------------------

def test_reschedule_persists_settings(engine):
    SchedulerManager(engine).reschedule(enabled=True, trigger="interval", value="15")
    with session_scope(engine) as s:
        settings = config_service.get_settings(s)
        assert settings.scheduler_enabled is True
        assert settings.scheduler_value == "15"


def test_reschedule_rejects_bad_value(engine):
    with pytest.raises(ValidationError):
        SchedulerManager(engine).reschedule(enabled=True, trigger="interval", value="zero")


# --- skip closed/archived during refresh ------------------------------------

class RecordingClient:
    """Fake Jira client that records which sprint ids it fetched metrics for."""

    def __init__(self):
        self.fetched: list[int] = []

    def fetch_sprints(self):
        return {
            "My Team 2026-16": {"id": 100, "state": "active"},
            "My Team 2026-18": {"id": 101, "state": "closed"},
        }

    def fetch_metrics(self, sprint_id):
        self.fetched.append(sprint_id)
        return {"done_n": 5, "tot_n": 68, "done_sp": 11, "tot_sp": 153}


def test_refresh_skips_closed_sprint(engine, monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(jira_service, "make_client", lambda s: client)
    with session_scope(engine) as s:
        row = s.get(m.Sprint, "2026-18")
        row.jira_state = "closed"
        row.done_n = 99  # sentinel that must survive the refresh
        s.add(row)
    result = SchedulerManager(engine).run_now()
    assert 101 not in client.fetched          # closed sprint never fetched
    assert 100 in client.fetched              # active sprint still fetched
    assert result["status"] == "ok"
    with session_scope(engine) as s:
        assert s.get(m.Sprint, "2026-18").done_n == 99  # cached numbers kept


def test_refresh_skips_archived_sprint(engine, monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(jira_service, "make_client", lambda s: client)
    with session_scope(engine) as s:
        row = s.get(m.Sprint, "2026-16")
        row.archived = True
        s.add(row)
    SchedulerManager(engine).run_now()
    assert 100 not in client.fetched          # archived sprint never fetched


def test_refresh_all_skipped_reports_ok(engine, monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(jira_service, "make_client", lambda s: client)
    with session_scope(engine) as s:
        c = s.get(m.Sprint, "2026-16")
        c.jira_state = "closed"
        s.add(c)
        a = s.get(m.Sprint, "2026-18")
        a.archived = True
        s.add(a)
    result = SchedulerManager(engine).run_now()
    assert result["status"] == "ok"
    assert client.fetched == []               # zero Jira metric calls
    assert "skipped" in result["log"]


def test_refresh_log_mentions_skipped_count(engine, monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(jira_service, "make_client", lambda s: client)
    with session_scope(engine) as s:
        row = s.get(m.Sprint, "2026-18")
        row.jira_state = "closed"
        s.add(row)
    result = SchedulerManager(engine).run_now()
    assert result["updated"] == 1             # only 2026-16 updated
    assert "1 closed/archived skipped" in result["log"]
