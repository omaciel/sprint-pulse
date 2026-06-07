"""Config loader: data/config.yaml -> Config dataclass."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when config.yaml is missing required fields or fails validation."""


def normalize_site(site: str) -> str:
    """Reduce a Jira site to a bare host.

    The client builds URLs as ``https://{site}/rest/...``, so the stored site
    must be just the host. Accept a pasted full URL too:
    ``https://acme.atlassian.net/jira/`` -> ``acme.atlassian.net``.
    """
    s = (site or "").strip()
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0]  # drop any path
    return s.strip().rstrip("/")


@dataclass(frozen=True)
class JiraConfig:
    site: str
    board: str

    def __post_init__(self) -> None:
        # Normalize at the single chokepoint every client path goes through.
        object.__setattr__(self, "site", normalize_site(self.site))


@dataclass(frozen=True)
class Config:
    working_days_per_sprint: int
    jira: JiraConfig
    roster: list[str]
    orchestration: set[str]
    name_aliases: dict[str, str]
    # Team name shown in the page/sidebar headers and used as the Jira sprint-name prefix when matching the board.
    team_name: str = "Wisdom"

    @property
    def effective(self) -> list[str]:
        return [n for n in self.roster if n not in self.orchestration]

    @property
    def capacity(self) -> int:
        return len(self.effective) * self.working_days_per_sprint


def load_config(path: Path | str) -> Config:
    path = Path(path)
    with path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    for required in ("working_days_per_sprint", "jira", "roster"):
        if required not in raw:
            raise ConfigError(f'{path.name}: missing required field "{required}"')

    roster = raw["roster"]
    if not isinstance(roster, list) or not roster:
        raise ConfigError(f"{path.name}: roster must be a non-empty list")

    seen: set[str] = set()
    for name in roster:
        if name in seen:
            raise ConfigError(f'{path.name}: duplicate roster entry "{name}"')
        seen.add(name)

    orchestration = set(raw.get("orchestration") or [])
    for name in orchestration:
        if name not in seen:
            raise ConfigError(f'{path.name}: orchestration member "{name}" not in roster')

    aliases = dict(raw.get("name_aliases") or {})
    for src, target in aliases.items():
        if target not in seen:
            raise ConfigError(f'{path.name}: alias target "{target}" not in roster')

    jira_raw = raw["jira"] or {}
    jira = JiraConfig(site=jira_raw["site"], board=str(jira_raw["board"]))

    return Config(
        working_days_per_sprint=int(raw["working_days_per_sprint"]),
        jira=jira,
        roster=list(roster),
        orchestration=orchestration,
        name_aliases=aliases,
        team_name=str(raw.get("team_name") or "Wisdom"),
    )
