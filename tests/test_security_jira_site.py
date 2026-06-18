"""Security regression tests for the Jira-site SSRF / credential-exfiltration fix.

The Jira client sends ``Authorization: Basic base64(user:token)`` to
``https://{site}/...``. A forged ``site`` would hand the operator's token to an
attacker-controlled host. These tests pin the two defenses:

  1. ``validate_site`` allowlist (host + private-IP rejection), enforced on write
     (``apply_jira_settings``) and on use (``jira_service.probe``/``make_client``).
  2. ``/setup/wizard/test`` no longer falls back to the stored/env token, so an
     anonymous caller can't borrow the real token to probe an arbitrary host.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from sprint_pulse.config import ConfigError, validate_site
from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
from sprint_pulse.errors import ValidationError
from sprint_pulse.services import config_service as cfgsvc
from sprint_pulse.services import jira_service
from sprint_pulse.web.app import create_app


# --- validate_site -----------------------------------------------------------

@pytest.mark.parametrize("site", [
    "acme.atlassian.net",
    "https://acme.atlassian.net/jira/",  # normalized first
    "ACME.ATLASSIAN.NET",
])
def test_validate_site_allows_atlassian_cloud(site):
    # Assert the dotted suffix: a bare "atlassian.net" check would also accept a
    # look-alike like "evilatlassian.net", which the allowlist must reject.
    assert validate_site(site).lower().endswith(".atlassian.net")


@pytest.mark.parametrize("site", [
    "evil.attacker.com",
    "atlassian.net.evil.com",   # suffix-confusion must not match "*.atlassian.net"
    "127.0.0.1",
    "169.254.169.254",          # cloud metadata endpoint
    "10.0.0.5",
    "192.168.1.1",
    "[::1]",
    "",
])
def test_validate_site_rejects_forged_and_internal(site):
    with pytest.raises(ConfigError):
        validate_site(site)


def test_validate_site_respects_env_allowlist(monkeypatch):
    monkeypatch.setenv("SPRINT_PULSE_JIRA_ALLOWED_HOSTS", "jira.corp.example.com")
    assert validate_site("jira.corp.example.com") == "jira.corp.example.com"
    with pytest.raises(ConfigError):
        validate_site("acme.atlassian.net")  # default no longer applies


# --- write-side guard --------------------------------------------------------

def test_apply_jira_settings_rejects_forged_host():
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            cfgsvc.apply_jira_settings(
                s, jira_site="evil.attacker.com", jira_board="1", jira_username="me@x.com"
            )


# --- use-side guard ----------------------------------------------------------

def test_probe_rejects_forged_host_without_sending_token():
    # JiraClient must never be constructed for a non-allowlisted host.
    with patch("sprint_pulse.services.jira_service.JiraClient") as JC:
        msg, ok = jira_service.probe("evil.attacker.com", "1", "me@x.com", "secret-token")
    assert ok is False
    JC.assert_not_called()


# --- wizard test endpoint: no token fallback ---------------------------------

@pytest.fixture
def client():
    return TestClient(create_app(":memory:"))


def test_wizard_test_blank_token_does_not_leak(client):
    # An empty token must NOT fall back to the stored/env token, and must not
    # reach the Jira client at all.
    with patch("sprint_pulse.services.jira_service.JiraClient") as JC:
        r = client.post(
            "/setup/wizard/test",
            data={
                "jira_site": "evil.attacker.com",
                "jira_board": "1",
                "jira_username": "me@x.com",
                "jira_token": "",
            },
        )
    assert r.status_code == 200
    assert "Enter a token" in r.text
    JC.assert_not_called()


def test_wizard_save_forged_host_keeps_submitted_values(client):
    # A rejected host re-renders the wizard with an error AND preserves the
    # other values the user entered (no reset to defaults).
    r = client.post(
        "/setup/wizard",
        data={
            "working_days_per_sprint": "7",
            "team_name": "Wisdom",
            "jira_site": "evil.attacker.com",
            "jira_board": "42",
            "jira_username": "me@x.com",
            "jira_token": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 200  # re-rendered, not redirected
    assert "allowed-hosts" in r.text
    assert 'value="7"' in r.text
    assert 'value="Wisdom"' in r.text
    assert 'value="evil.attacker.com"' in r.text
    assert 'value="42"' in r.text
    assert 'value="me@x.com"' in r.text


def test_wizard_test_forged_host_rejected_with_token(client):
    with patch("sprint_pulse.services.jira_service.JiraClient") as JC:
        r = client.post(
            "/setup/wizard/test",
            data={
                "jira_site": "evil.attacker.com",
                "jira_board": "1",
                "jira_username": "me@x.com",
                "jira_token": "secret-token",
            },
        )
    assert r.status_code == 200
    assert "allowed-hosts" in r.text
    JC.assert_not_called()
