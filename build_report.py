#!/usr/bin/env python3
"""sprint-pulse: build the team time-off + sprint report HTML.

Reads:
  - data/config.yaml         (team + integration config)
  - data/sprints/*.yaml      (one file per sprint)
  - Jira board               (live tickets / story points via Greenhopper API)

Writes:
  - output/report.html

Usage:
  export JIRA_USERNAME="you@redhat.com"
  export JIRA_API_TOKEN="..."
  python3 build_report.py [--skip-jira]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from sprint_pulse.config import load_config
from sprint_pulse.jira import JiraClient, JiraUnavailable
from sprint_pulse.render import render_full_html
from sprint_pulse.sprints import Sprint, load_sprints


PROJECT_ROOT = Path(__file__).parent
CONFIG_PATH = PROJECT_ROOT / "data" / "config.yaml"
SPRINTS_DIR = PROJECT_ROOT / "data" / "sprints"
HTML_PATH = Path(os.environ.get("SPRINT_PULSE_OUTPUT", PROJECT_ROOT / "output" / "report.html"))


def _empty_metrics() -> dict[str, int]:
    return {"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}


def main() -> None:
    skip_jira = "--skip-jira" in sys.argv[1:]

    print(f"Reading {CONFIG_PATH}")
    cfg = load_config(CONFIG_PATH)
    print(f"Reading {SPRINTS_DIR}")
    sprints: list[Sprint] = load_sprints(SPRINTS_DIR, cfg)
    if not sprints:
        sys.exit("No sprints found.")

    missing_creds = [v for v in ("JIRA_USERNAME", "JIRA_API_TOKEN") if not os.environ.get(v)]
    if missing_creds and not skip_jira:
        print(
            f"Missing env var(s): {', '.join(missing_creds)}. "
            f"Skipping Jira metrics; report will render without ticket/SP counts.",
            file=sys.stderr,
        )
        skip_jira = True

    jira_sprints: dict = {}
    client: JiraClient | None = None
    if skip_jira:
        print("Skipping Jira fetch (--skip-jira or missing credentials).")
    else:
        client = JiraClient(cfg.jira, os.environ["JIRA_USERNAME"], os.environ["JIRA_API_TOKEN"])
        print("Fetching Jira sprint metadata...")
        try:
            jira_sprints = client.fetch_sprints()
        except JiraUnavailable as e:
            print(f"Could not reach Jira ({e}). Are you on the VPN?", file=sys.stderr)
            print(
                "Falling back to no metrics; re-run with --skip-jira to suppress this attempt.",
                file=sys.stderr,
            )
            jira_sprints = {}

    sprints_with_data: list[tuple[Sprint, dict, str]] = []
    for sprint in sprints:
        info = jira_sprints.get(sprint.name)
        if info and client is not None:
            try:
                metrics = client.fetch_metrics(info["id"])
            except JiraUnavailable as e:
                print(f"  {sprint.name}: metrics fetch failed ({e}); using zeros.", file=sys.stderr)
                metrics = _empty_metrics()
            state = info["state"]
        else:
            metrics = _empty_metrics()
            state = "future"
        print(
            f"  {sprint.name}: state={state}, "
            f"{metrics['done_n']}/{metrics['tot_n']} tickets, "
            f"{metrics['done_sp']}/{metrics['tot_sp']} SP"
        )
        sprints_with_data.append((sprint, metrics, state))

    HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    HTML_PATH.write_text(render_full_html(sprints_with_data, cfg))
    print(f"Wrote {HTML_PATH}")


if __name__ == "__main__":
    main()
