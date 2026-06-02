"""Jira API client (extracted from build_report.py)."""
from __future__ import annotations

import base64
import functools
import json
import ssl
from datetime import date
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from sprint_pulse.config import JiraConfig


JIRA_TIMEOUT_SECONDS = 15
JIRA_MAX_ATTEMPTS = 3


class JiraUnavailable(Exception):
    """Raised when Jira can't be reached after retries."""


def _parse_jira_date(value: str | None) -> date | None:
    """Jira returns ISO timestamps like '2026-05-28T00:00:00.000Z'; take the
    date part. Future sprints may have no dates -> None."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


@functools.lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi  # type: ignore
        ctx.load_verify_locations(certifi.where())
    except ImportError:
        ctx.load_verify_locations("/etc/ssl/cert.pem")
    return ctx


class JiraClient:
    def __init__(self, config: JiraConfig, username: str, token: str) -> None:
        self.config = config
        self._auth = base64.b64encode(f"{username}:{token}".encode()).decode()
        self._ctx = _ssl_context()

    def fetch(self, url: str) -> dict[str, Any]:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Basic {self._auth}",
                "Accept": "application/json",
            },
        )
        last_err: Exception | None = None
        for attempt in range(1, JIRA_MAX_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(req, context=self._ctx, timeout=JIRA_TIMEOUT_SECONDS) as r:
                    return json.loads(r.read().decode())
            except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
                last_err = e
                if attempt < JIRA_MAX_ATTEMPTS:
                    backoff = 2 ** (attempt - 1)
                    print(
                        f"  Jira request failed ({e}); retrying in {backoff}s "
                        f"({attempt}/{JIRA_MAX_ATTEMPTS - 1})...",
                        file=sys.stderr,
                    )
                    time.sleep(backoff)
        raise JiraUnavailable(str(last_err))

    def fetch_sprints(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        start = 0
        while True:
            d = self.fetch(
                f"https://{self.config.site}/rest/agile/1.0/board/{self.config.board}/sprint"
                f"?state=active,closed,future&maxResults=50&startAt={start}"
            )
            for s in d.get("values", []):
                out[s["name"]] = {
                    "id": s["id"],
                    "state": s["state"],
                    "start": _parse_jira_date(s.get("startDate")),
                    "end": _parse_jira_date(s.get("endDate")),
                }
            if d.get("isLast", True):
                return out
            start += d.get("maxResults", 50)

    def fetch_metrics(self, sprint_id: int) -> dict[str, int]:
        d = self.fetch(
            f"https://{self.config.site}/rest/greenhopper/1.0/rapid/charts/sprintreport"
            f"?rapidViewId={self.config.board}&sprintId={sprint_id}"
        )["contents"]
        comp = d.get("completedIssues", [])
        nc = d.get("issuesNotCompletedInCurrentSprint", [])

        def sp(items):
            return sum(
                (i.get("currentEstimateStatistic", {}).get("statFieldValue", {}).get("value") or 0)
                for i in items
            )
        return {
            "done_n": len(comp),
            "tot_n": len(comp) + len(nc),
            "done_sp": int(sp(comp)),
            "tot_sp": int(sp(comp) + sp(nc)),
        }
