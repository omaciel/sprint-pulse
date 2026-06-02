"""Smoke test: load every example YAML file and assert success."""
from pathlib import Path


from sprint_pulse.config import load_config
from sprint_pulse.sprints import load_sprints


PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "examples"


def test_real_config_loads() -> None:
    cfg = load_config(DATA_DIR / "config.yaml")
    assert len(cfg.roster) >= 1
    assert cfg.capacity > 0


def test_real_sprints_load() -> None:
    cfg = load_config(DATA_DIR / "config.yaml")
    sprints = load_sprints(DATA_DIR / "sprints", cfg)
    assert len(sprints) >= 1
    # Sanity: every event/time_off entry passed validation by virtue of loading
    for sprint in sprints:
        for event in sprint.events:
            assert sprint.start <= event.date <= sprint.end
        for entry in sprint.time_off:
            for day in entry.days:
                assert sprint.start <= day <= sprint.end
