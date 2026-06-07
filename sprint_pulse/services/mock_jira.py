"""A canned, offline stand-in for JiraClient — used in demo mode.

Enabled by ``SPRINT_PULSE_DEMO=1`` (see jira_service.make_client). Lets you demo
the whole app — Test connection, Import from Jira, Refresh metrics — with no live
Jira instance and no credentials. The data is deterministic.
"""
from __future__ import annotations

from datetime import date

# (short id, start, end, state). Sprint numbers follow a 2-week cadence; the
# first three overlap the example YAML so "Import from Jira" shows some rows as
# already-imported and some as new.
_SPRINTS = [
    ("2026-16", date(2026, 4, 16), date(2026, 4, 29), "closed"),
    ("2026-18", date(2026, 4, 30), date(2026, 5, 13), "closed"),
    ("2026-20", date(2026, 5, 14), date(2026, 5, 27), "active"),
    ("2026-22", date(2026, 5, 28), date(2026, 6, 10), "future"),
    ("2026-24", date(2026, 6, 11), date(2026, 6, 24), "future"),
    ("2026-26", date(2026, 6, 25), date(2026, 7, 8), "future"),
    ("2026-28", date(2026, 7, 9), date(2026, 7, 22), "future"),
]


class MockJiraClient:
    """Implements the bits the app uses: fetch_sprints + fetch_metrics."""

    def __init__(self, team_name: str = "My Team") -> None:
        self.team_name = team_name or "My Team"

    def fetch_sprints(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for jira_id, (sid, start, end, state) in enumerate(_SPRINTS, start=1):
            out[f"{self.team_name} {sid}"] = {
                "id": jira_id,
                "state": state,
                "start": start,
                "end": end,
            }
        return out

    def fetch_metrics(self, sprint_id: int) -> dict[str, int]:
        # Deterministic, plausible burndown that grows with the sprint number.
        tot_n = 40 + sprint_id * 4
        done_n = min(tot_n, sprint_id * 6)
        return {"done_n": done_n, "tot_n": tot_n, "done_sp": done_n * 2, "tot_sp": tot_n * 2}
