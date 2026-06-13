"""Refresh pipeline: fetch live Jira state/metrics and cache them on Sprint rows.

This is the logic that used to live in ``build_report.py main()``, now writing
to the DB instead of rendering HTML. The scheduler calls ``refresh_all`` on a
cadence; the dashboard then renders instantly from the cached columns.
"""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from sprint_pulse.db import models as m
from sprint_pulse.jira import JiraUnavailable
from sprint_pulse.services import config_service, jira_service


def refresh_all(session: Session, *, now: datetime | None = None) -> dict:
    """Update cached Jira metrics for every sprint. Records last-run status on
    Settings. Archived sprints and sprints already cached as closed are skipped
    (their final numbers are kept); only future/active sprints are synced.
    Returns a small summary dict."""
    now = now or datetime.now()
    settings = config_service.get_settings(session)

    client = jira_service.make_client(session)
    if client is None:
        settings.last_run = now
        settings.last_status = "error"
        settings.last_log = "Jira is not fully configured (site, board, username, token)."
        session.add(settings)
        return {"status": "error", "updated": 0, "log": settings.last_log}

    try:
        jira_sprints = client.fetch_sprints()
    except JiraUnavailable as e:
        settings.last_run = now
        settings.last_status = "error"
        settings.last_log = f"Could not reach Jira ({e}). On the VPN?"
        session.add(settings)
        return {"status": "error", "updated": 0, "log": settings.last_log}

    prefix = settings.team_name or "My Team"
    by_jira_id = {info["id"]: info for info in jira_sprints.values()}
    rows = list(session.exec(select(m.Sprint)).all())
    updated = 0
    matched = 0
    skipped = 0
    metric_failures = 0
    for row in rows:
        # Archived sprints are off the dashboard and closed sprints have final
        # numbers — skip both (before any Jira call) so we don't re-fetch
        # unchanging data every run. "closed" is judged from our cached state:
        # the run that first sees a sprint close still captures it once.
        if row.archived or row.jira_state == "closed":
            skipped += 1
            continue
        # Prefer the stored Jira numeric id; fall back to the "{team} {id}" name
        # for sprints imported before that was tracked (e.g. YAML-migrated).
        info = None
        if row.jira_sprint_id is not None:
            info = by_jira_id.get(row.jira_sprint_id)
        if info is None:
            info = jira_sprints.get(f"{prefix} {row.label or row.id}")
        if not info:
            continue
        matched += 1
        try:
            metrics = client.fetch_metrics(info["id"])
        except JiraUnavailable:
            # Leave cached state + metrics untouched so we don't show a stale
            # state next to fresh numbers (or vice versa); count it as a failure.
            metric_failures += 1
            continue
        row.jira_state = info["state"]
        row.done_n = metrics["done_n"]
        row.tot_n = metrics["tot_n"]
        row.done_sp = metrics["done_sp"]
        row.tot_sp = metrics["tot_sp"]
        row.last_refreshed = now
        updated += 1
        session.add(row)

    eligible = len(rows) - skipped
    settings.last_run = now
    if eligible == 0:
        settings.last_status = "ok"
        if skipped:
            settings.last_log = (
                f"No active sprints to sync ({skipped} closed/archived skipped)."
            )
        else:
            settings.last_log = "No sprints to sync."
    elif matched == 0:
        settings.last_status = "ok"
        settings.last_log = "No matching Jira sprints — nothing to update."
    elif metric_failures:
        settings.last_status = "error"
        settings.last_log = (
            f"Updated {updated}/{eligible} sprints; "
            f"{metric_failures} metric fetch(es) failed (stale numbers kept)."
        )
    else:
        settings.last_status = "ok"
        skip_note = f" ({skipped} closed/archived skipped)" if skipped else ""
        settings.last_log = f"Updated {updated}/{eligible} sprints{skip_note}."
    session.add(settings)
    return {"status": settings.last_status, "updated": updated, "log": settings.last_log}
