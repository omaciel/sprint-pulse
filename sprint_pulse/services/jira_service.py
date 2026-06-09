"""Build a JiraClient from DB settings + the secrets backend."""
from __future__ import annotations

import os

from sqlmodel import Session

from sprint_pulse.config import ConfigError, JiraConfig, validate_site
from sprint_pulse.jira import JiraClient, JiraUnavailable
from sprint_pulse.services import config_service, secrets


def demo_mode() -> bool:
    """SPRINT_PULSE_DEMO=1 → use the offline mock instead of a real Jira."""
    return os.environ.get("SPRINT_PULSE_DEMO") == "1"


def probe(site: str, board: str, username: str, token: str | None) -> tuple[str, bool]:
    """Test a connection with the given (possibly unsaved) credentials.

    Returns (message, ok). Single source of the connection-test UX used by both
    the config page and the setup wizard.
    """
    if demo_mode():
        from sprint_pulse.services.mock_jira import MockJiraClient

        n = len(MockJiraClient().fetch_sprints())
        return f"Connected to mock Jira (demo) — {n} sprints.", True
    if not (site and board and username and token):
        return "Fill in site, board, username, and token first.", False
    # Don't send the token to a forged/internal host (credential exfiltration).
    try:
        site = validate_site(site)
    except ConfigError as e:
        return str(e), False
    client = JiraClient(JiraConfig(site=site, board=board), username, token)
    try:
        sprints = client.fetch_sprints()
        return f"Connected — found {len(sprints)} sprints on the board.", True
    except JiraUnavailable as e:
        return f"Could not reach Jira ({e}). On the VPN?", False


def make_client(session: Session):
    """Return a Jira client, or None if not configured.

    In demo mode (SPRINT_PULSE_DEMO=1) a MockJiraClient is returned regardless of
    credentials, so the whole app works offline.
    """
    settings = config_service.get_settings(session)
    if demo_mode():
        from sprint_pulse.services.mock_jira import MockJiraClient

        return MockJiraClient(settings.team_name or "My Team")
    token = secrets.get_token(settings.token_ref, settings.jira_username)
    if not (settings.jira_site and settings.jira_board and settings.jira_username and token):
        return None
    # Defense in depth: never hand the token to a host that isn't allowlisted,
    # even if a bad value reached the DB (e.g. an older row or a YAML import).
    try:
        site = validate_site(settings.jira_site)
    except ConfigError:
        return None
    return JiraClient(
        JiraConfig(site=site, board=settings.jira_board),
        settings.jira_username,
        token,
    )
