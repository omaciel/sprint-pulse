"""Config loader: data/config.yaml -> Config dataclass."""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from datetime import date
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


# Hosts we're willing to send Jira Basic-auth credentials to. The client puts the
# token in an Authorization header on https://{site}/..., so an unrestricted site
# means the token is handed to whoever controls that host (credential exfiltration
# via a forged "site"). Default to Atlassian Cloud; operators self-hosting Jira
# add their host via SPRINT_PULSE_JIRA_ALLOWED_HOSTS (a trusted env value).
_DEFAULT_ALLOWED_HOSTS = "*.atlassian.net"


def _allowed_host_patterns() -> list[str]:
    raw = os.environ.get("SPRINT_PULSE_JIRA_ALLOWED_HOSTS", _DEFAULT_ALLOWED_HOSTS)
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _host_matches(host: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        suffix = pattern[1:]  # ".atlassian.net"
        return host == pattern[2:] or host.endswith(suffix)
    return host == pattern


def validate_site(site: str) -> str:
    """Return the normalized host if it's an allowed Jira target; raise otherwise.

    This is the security chokepoint that prevents credential exfiltration: never
    let the client send the token to an arbitrary or internal host. Rejects
    private/loopback/link-local IPs and any host not on the allowlist.
    """
    host = normalize_site(site)
    if not host:
        raise ConfigError("Jira site is required")
    bare = host.split(":", 1)[0].lower()  # strip :port; hostnames are case-insensitive

    # An IP literal must be a public address — block loopback/private/link-local
    # so a forged site can't point the credentialed request at internal services.
    try:
        if not ipaddress.ip_address(bare).is_global:
            raise ConfigError(f"Jira site {host!r} is not a public address")
    except ValueError:
        pass  # not an IP literal — fall through to the hostname allowlist

    patterns = _allowed_host_patterns()
    if any(_host_matches(bare, pat) for pat in patterns):
        return host
    raise ConfigError(
        f"Jira site {host!r} is not in the allowed-hosts list "
        f"(set SPRINT_PULSE_JIRA_ALLOWED_HOSTS to permit it)"
    )


# A tenure is (start_date, end_date); None on either side means unbounded.
Tenure = tuple[date | None, date | None]


def in_tenure(tenure: Tenure | None, d: date) -> bool:
    """True when day ``d`` falls inside the member's tenure (inclusive)."""
    if tenure is None:
        return True
    start, end = tenure
    return (start is None or start <= d) and (end is None or d <= end)


def tenure_overlaps(tenure: Tenure | None, start: date, end: date) -> bool:
    """True when the tenure overlaps the [start, end] window (inclusive)."""
    if tenure is None:
        return True
    t_start, t_end = tenure
    return (t_start is None or t_start <= end) and (t_end is None or t_end >= start)


@dataclass(frozen=True)
class JiraConfig:
    site: str
    board: str

    def __post_init__(self) -> None:
        # Normalize at the single chokepoint every client path goes through.
        object.__setattr__(self, "site", normalize_site(self.site))


@dataclass(frozen=True)
class TypeDef:
    key: str
    label: str
    abbreviation: str
    color: str
    sort_order: int = 0


@dataclass(frozen=True)
class Config:
    working_days_per_sprint: int
    jira: JiraConfig
    roster: list[str]
    excluded: set[str]
    name_aliases: dict[str, str]
    # Team name shown in the page/sidebar headers and used as the Jira sprint-name prefix when matching the board.
    team_name: str = "My Team"
    # Event/absence type vocabularies (key/label/abbreviation/color), hydrated
    # from the DB; the renderer derives CSS, cell letters, and the legend from these.
    event_types: tuple[TypeDef, ...] = ()
    absence_types: tuple[TypeDef, ...] = ()
    # Per-member tenure, populated only for members that have tenure dates;
    # absent key = full tenure. Drives out-of-tenure cell rendering.
    tenures: dict[str, Tenure] = field(default_factory=dict)
    # Per-sprint prorated capacity, set on the per-sprint Config copies built
    # by sprint_service; None = derive from the roster as before.
    capacity_override: int | None = None

    @property
    def effective(self) -> list[str]:
        return [n for n in self.roster if n not in self.excluded]

    @property
    def capacity(self) -> int:
        if self.capacity_override is not None:
            return self.capacity_override
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

    excluded = set(raw.get("excluded") or [])
    for name in excluded:
        if name not in seen:
            raise ConfigError(f'{path.name}: excluded member "{name}" not in roster')

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
        excluded=excluded,
        name_aliases=aliases,
        team_name=str(raw.get("team_name") or "My Team"),
    )
