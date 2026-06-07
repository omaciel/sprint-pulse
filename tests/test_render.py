"""HTML rendering tests."""
from datetime import date

import pytest

from sprint_pulse.config import Config, JiraConfig
from sprint_pulse.render import render_sprint, derive_sprint_notes
from sprint_pulse.sprints import Event, Sprint, TimeOffEntry


@pytest.fixture
def cfg() -> Config:
    return Config(
        working_days_per_sprint=10,
        jira=JiraConfig(site="x", board="1"),
        roster=[
            "Alice Anderson",
            "Carol Diaz",
            "Dmitri Egorov",
            "Grace Hughes",
            "Hassan Ibrahim",
        ],
        excluded={"Grace Hughes", "Hassan Ibrahim"},
        name_aliases={},
    )


def _minimal_sprint() -> Sprint:
    return Sprint(
        id="2026-16",
        start=date(2026, 4, 16),
        end=date(2026, 4, 29),
        events=(
            Event(date=date(2026, 4, 17), kind="gono", title="Go/No-Go deadline 4PM EST"),
            Event(date=date(2026, 4, 22), kind="ga", title="2.7 GA release"),
        ),
        time_off=(
            TimeOffEntry(
                associate="Alice Anderson",
                days=(date(2026, 4, 24),),
                notes="PTO",
                type="pto",
            ),
        ),
        label="June 2026",
    )


def test_render_sprint_includes_label_and_dates(cfg: Config) -> None:
    sprint = _minimal_sprint()
    html, _ = render_sprint(sprint, cfg, metrics={"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}, state="future")
    assert "June 2026" in html          # the label shows
    assert "Wisdom 2026-16" not in html  # no team/Jira prefix anymore
    assert "Apr 16" in html


def test_render_sprint_includes_event_letters(cfg: Config) -> None:
    sprint = _minimal_sprint()
    html, _ = render_sprint(sprint, cfg, metrics={"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}, state="future")
    assert ">G<" in html  # Go/No-Go letter
    assert ">R<" in html  # GA release letter


def test_render_sprint_excluded_marked_and_uncounted(cfg: Config) -> None:
    sprint = _minimal_sprint()
    html, days_out = render_sprint(sprint, cfg, metrics={"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}, state="future")
    assert 'class="excluded"' in html or 'excluded-row' in html
    assert 'title="Excluded from capacity"' in html


def test_render_sprint_days_out_excludes_excluded(cfg: Config) -> None:
    sprint = _minimal_sprint()
    _, days_out = render_sprint(sprint, cfg, metrics={"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}, state="future")
    assert days_out["Alice Anderson"] == 1
    assert days_out["Grace Hughes"] == 0


def test_derive_sprint_notes_format(cfg: Config) -> None:
    sprint = _minimal_sprint()
    notes = derive_sprint_notes(sprint)
    assert notes == [
        "Go/No-Go deadline 4PM EST — Apr 17",
        "2.7 GA release — Apr 22",
    ]


def test_render_sprint_release_row_labelled_releases(cfg: Config) -> None:
    sprint = _minimal_sprint()
    html, _ = render_sprint(sprint, cfg, metrics={"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0}, state="future")
    assert ">Releases<" in html
    assert "AAP" not in html


def test_render_sprint_snapshot(cfg: Config, snapshot) -> None:
    """Golden file for the minimal sprint render."""
    sprint = _minimal_sprint()
    html, _ = render_sprint(
        sprint,
        cfg,
        metrics={"done_n": 0, "tot_n": 0, "done_sp": 0, "tot_sp": 0},
        state="future",
    )
    snapshot.assert_match(html, "sprint-minimal.html")
