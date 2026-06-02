"""Config loader tests."""
from pathlib import Path

import pytest

from sprint_pulse.config import Config, ConfigError, load_config


def test_load_valid_config(valid_dir: Path) -> None:
    cfg = load_config(valid_dir / "config.yaml")
    assert isinstance(cfg, Config)
    assert cfg.working_days_per_sprint == 10
    assert cfg.jira.site == "redhat.atlassian.net"
    assert cfg.jira.board == "1046"
    assert "Alice Anderson" in cfg.roster
    assert cfg.roster.index("Alice Anderson") == 0
    assert cfg.orchestration == {"Grace Hughes", "Hassan Ibrahim"}
    assert cfg.name_aliases["Alyce Anderson"] == "Alice Anderson"


def test_capacity_property(valid_dir: Path) -> None:
    cfg = load_config(valid_dir / "config.yaml")
    # 11 roster - 2 orchestration = 9 effective; 9 * 10 = 90
    assert cfg.capacity == 90


def test_effective_excludes_orchestration(valid_dir: Path) -> None:
    cfg = load_config(valid_dir / "config.yaml")
    assert "Grace Hughes" not in cfg.effective
    assert "Alice Anderson" in cfg.effective


@pytest.mark.parametrize(
    "fixture, expected_substring",
    [
        ("config-orch-not-in-roster.yaml", "orchestration member \"Carol\" not in roster"),
        ("config-alias-target-not-in-roster.yaml", "alias target \"Carol\" not in roster"),
        ("config-duplicate-roster.yaml", "duplicate roster entry \"Alice\""),
        ("config-missing-roster.yaml", "missing required field \"roster\""),
    ],
)
def test_invalid_config_raises(invalid_dir: Path, fixture: str, expected_substring: str) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_config(invalid_dir / fixture)
    assert expected_substring in str(exc_info.value)
