"""Sprint loader tests."""
import warnings
from datetime import date
from pathlib import Path

import pytest

from sprint_pulse.config import Config, JiraConfig
from sprint_pulse.sprints import (
    HOLIDAY_KEYWORDS,
    SprintError,
    infer_type,
    load_sprint_file,
    load_sprints,
    working_days,
)


# --- Helpers ---

def test_working_days_excludes_weekends() -> None:
    # Apr 16 (Thu) - Apr 29 (Wed) 2026
    days = working_days(date(2026, 4, 16), date(2026, 4, 29))
    assert len(days) == 10
    assert date(2026, 4, 18) not in days  # Saturday
    assert date(2026, 4, 19) not in days  # Sunday


def test_working_days_single_day() -> None:
    assert working_days(date(2026, 4, 16), date(2026, 4, 16)) == [date(2026, 4, 16)]


def test_working_days_weekend_only() -> None:
    assert working_days(date(2026, 4, 18), date(2026, 4, 19)) == []


# --- Type inference ---

@pytest.mark.parametrize(
    "notes, expected",
    [
        ("PTO", "pto"),
        ("", "pto"),
        ("Brazil holiday", "holiday"),
        ("Memorial Day", "holiday"),
        ("Pentecost Monday", "holiday"),
        ("Liberation Day", "holiday"),
        ("Victoria Day", "holiday"),
        ("US Independence Day", "holiday"),
        ("Company holiday", "company"),
        ("Partially available", "partial"),
        ("Tentative", "tentative"),
        ("tentative — not a holiday", "tentative"),
    ],
)
def test_infer_type(notes: str, expected: str) -> None:
    assert infer_type(notes) == expected


def test_holiday_keywords_complete() -> None:
    # Sanity: HOLIDAY_KEYWORDS exposed for testability
    assert "memorial day" in HOLIDAY_KEYWORDS
    assert "pentecost" in HOLIDAY_KEYWORDS


# --- Single-file loader: valid ---

@pytest.fixture
def cfg() -> Config:
    return Config(
        working_days_per_sprint=10,
        jira=JiraConfig(site="x", board="1"),
        roster=[
            "Alice Anderson",
            "Bruno Costa",
            "Carol Diaz",
            "Dmitri Egorov",
            "Grace Hughes",
            "Hassan Ibrahim",
            "Elena Fischer",
            "Frank Garcia",
            "Mei Lin",
            "Jack Kelly",
            "Ines Jensen",
        ],
        excluded={"Grace Hughes", "Hassan Ibrahim"},
        name_aliases={},
    )


def test_load_minimal_sprint(valid_dir: Path, cfg: Config) -> None:
    sprint = load_sprint_file(valid_dir / "sprint-minimal.yaml", cfg)
    assert sprint.id == "2026-16"
    assert sprint.start == date(2026, 4, 16)
    assert sprint.end == date(2026, 4, 29)
    assert sprint.events == ()
    assert sprint.time_off == ()


def test_load_full_sprint(valid_dir: Path, cfg: Config) -> None:
    sprint = load_sprint_file(valid_dir / "sprint-full.yaml", cfg)
    assert len(sprint.events) == 4
    assert sprint.events[0].kind == "gono"
    assert sprint.events[0].date == date(2026, 4, 17)
    # __all__ expanded to one entry per roster member
    all_assoc_entries = [e for e in sprint.time_off if e.notes == "Company holiday"]
    assert len(all_assoc_entries) == len(cfg.roster)
    # Type inference: PTO and Company
    pto = next(e for e in sprint.time_off if e.associate == "Alice Anderson")
    assert pto.type == "pto"
    company = all_assoc_entries[0]
    assert company.type == "company"


def test_sprint_length_warning_skipped_for_14_day(valid_dir: Path, cfg: Config) -> None:
    # 14-day sprint should not warn (recwarn captures all warnings)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        load_sprint_file(valid_dir / "sprint-minimal.yaml", cfg)
    assert not any("sprint length" in str(w.message).lower() for w in caught)


# --- Single-file loader: validation errors ---

@pytest.mark.parametrize(
    "fixture, expected_substring",
    [
        ("sprint-end-before-start.yaml", "end (2026-04-16) is before start (2026-04-29)"),
        ("sprint-event-outside-range.yaml", "outside sprint range"),
        ("sprint-event-on-saturday.yaml", "is a Saturday"),
        ("sprint-unknown-kind.yaml", 'unknown kind "release"'),
        ("sprint-event-missing-title.yaml", "missing title"),
        ("sprint-unknown-associate.yaml", 'unknown associate "Alice Andersen"'),
        ("sprint-unknown-associate.yaml", "Alice Anderson"),  # suggestion
        ("sprint-day-outside-range.yaml", "outside sprint range"),
        ("sprint-day-on-saturday.yaml", "is a Saturday"),
        ("sprint-empty-days.yaml", "empty days list"),
    ],
)
def test_invalid_sprint_raises(invalid_dir: Path, cfg: Config, fixture: str, expected_substring: str) -> None:
    with pytest.raises(SprintError) as exc_info:
        load_sprint_file(invalid_dir / fixture, cfg)
    assert expected_substring in str(exc_info.value)


# --- Directory loader ---

def test_load_sprints_directory(valid_dir: Path, cfg: Config) -> None:
    sprints = load_sprints(valid_dir / "sprints_dir", cfg)
    assert len(sprints) == 2
    ids = [s.id for s in sprints]
    assert "2026-16" in ids
    assert "2026-18" in ids


def test_load_sprints_skips_archive(valid_dir: Path, cfg: Config) -> None:
    sprints = load_sprints(valid_dir / "sprints_dir", cfg)
    assert "2025-50" not in [s.id for s in sprints]


def test_load_sprints_returns_sorted(valid_dir: Path, cfg: Config) -> None:
    sprints = load_sprints(valid_dir / "sprints_dir", cfg)
    assert [(s.start, s.end) for s in sprints] == sorted((s.start, s.end) for s in sprints)


def test_duplicate_sprint_slug_raises(cfg: Config) -> None:
    """The duplicate-slug check engages defensively. Two distinct filenames whose
    ids slugify to the same value can't realistically occur on disk, so test via
    the helper.
    """
    from sprint_pulse.sprints import _check_duplicate_slugs
    with pytest.raises(SprintError, match="Duplicate sprint slug 2026-16"):
        _check_duplicate_slugs([("a.yaml", "2026-16"), ("b.yaml", "2026-16")])
