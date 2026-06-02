"""JiraClient tests with mocked urlopen."""
import io
import json
from unittest.mock import patch

import pytest

from sprint_pulse.config import JiraConfig
from sprint_pulse.jira import JiraClient, JiraUnavailable


def _fake_response(payload: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode())


def test_fetch_returns_parsed_json() -> None:
    client = JiraClient(JiraConfig(site="x", board="1"), username="u", token="t")
    with patch("sprint_pulse.jira.urllib.request.urlopen") as m:
        m.return_value.__enter__.return_value = _fake_response({"hello": "world"})
        result = client.fetch("https://example.invalid/api")
    assert result == {"hello": "world"}


def test_fetch_retries_then_raises() -> None:
    import urllib.error
    client = JiraClient(JiraConfig(site="x", board="1"), username="u", token="t")
    with patch("sprint_pulse.jira.urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
        with patch("sprint_pulse.jira.time.sleep"):  # don't actually sleep
            with pytest.raises(JiraUnavailable):
                client.fetch("https://example.invalid/api")


def test_fetch_sprints_paginates() -> None:
    client = JiraClient(JiraConfig(site="x", board="1"), username="u", token="t")
    page1 = {
        "values": [{"name": "Wisdom 2026-16", "id": 100, "state": "closed"}],
        "isLast": False,
        "maxResults": 1,
    }
    page2 = {
        "values": [{"name": "Wisdom 2026-18", "id": 101, "state": "active"}],
        "isLast": True,
        "maxResults": 1,
    }
    with patch("sprint_pulse.jira.urllib.request.urlopen") as m:
        m.return_value.__enter__.side_effect = [_fake_response(page1), _fake_response(page2)]
        result = client.fetch_sprints()
    assert result == {
        "Wisdom 2026-16": {"id": 100, "state": "closed", "start": None, "end": None},
        "Wisdom 2026-18": {"id": 101, "state": "active", "start": None, "end": None},
    }


def test_fetch_sprints_parses_dates() -> None:
    from datetime import date
    client = JiraClient(JiraConfig(site="x", board="1"), username="u", token="t")
    page = {
        "values": [{
            "name": "Wisdom 2026-20", "id": 102, "state": "active",
            "startDate": "2026-05-14T00:00:00.000Z", "endDate": "2026-05-27T12:00:00.000Z",
        }],
        "isLast": True,
    }
    with patch("sprint_pulse.jira.urllib.request.urlopen") as m:
        m.return_value.__enter__.return_value = _fake_response(page)
        result = client.fetch_sprints()
    assert result["Wisdom 2026-20"]["start"] == date(2026, 5, 14)
    assert result["Wisdom 2026-20"]["end"] == date(2026, 5, 27)


def test_fetch_metrics_shape() -> None:
    client = JiraClient(JiraConfig(site="x", board="1"), username="u", token="t")
    body = {
        "contents": {
            "completedIssues": [
                {"currentEstimateStatistic": {"statFieldValue": {"value": 3}}},
                {"currentEstimateStatistic": {"statFieldValue": {"value": 5}}},
            ],
            "issuesNotCompletedInCurrentSprint": [
                {"currentEstimateStatistic": {"statFieldValue": {"value": 2}}},
            ],
        }
    }
    with patch("sprint_pulse.jira.urllib.request.urlopen") as m:
        m.return_value.__enter__.return_value = _fake_response(body)
        result = client.fetch_metrics(42)
    assert result == {"done_n": 2, "tot_n": 3, "done_sp": 8, "tot_sp": 10}
