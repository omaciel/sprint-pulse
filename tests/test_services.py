"""Service layer: validation parity + DB->dataclass hydration."""
from datetime import date

import pytest
from sqlmodel import select

from sprint_pulse.db import models as m
from sprint_pulse.db.engine import get_engine, session_scope
from sprint_pulse.errors import ValidationError
from sprint_pulse.migrate import import_yaml
from sprint_pulse.services import config_service as cfgsvc
from sprint_pulse.services import sprint_service as spsvc


@pytest.fixture
def engine(valid_dir):
    eng = get_engine(":memory:")
    import_yaml(eng, valid_dir / "config.yaml", valid_dir / "sprints_dir")
    return eng


# --- config_service ---------------------------------------------------------

def test_build_config_from_db_matches_yaml(engine):
    with session_scope(engine) as s:
        cfg = cfgsvc.build_config_from_db(s)
    assert len(cfg.roster) == 11
    assert cfg.orchestration == {"Grace Hughes", "Hassan Ibrahim"}
    assert cfg.capacity == 90  # (11 - 2) * 10
    assert cfg.name_aliases["Alyce Anderson"] == "Alice Anderson"


def test_add_member_rejects_duplicate(engine):
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            cfgsvc.add_member(s, "Alice Anderson")


def test_add_member_appends(engine):
    with session_scope(engine) as s:
        cfgsvc.add_member(s, "New Person")
    with session_scope(engine) as s:
        cfg = cfgsvc.build_config_from_db(s)
    assert "New Person" in cfg.roster


def test_alias_target_must_exist(engine):
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            cfgsvc.add_alias(s, "Some Source", target_member_id=99999)


def test_remove_member_cascades(engine):
    with session_scope(engine) as s:
        member = s.exec(select(m.TeamMember).where(m.TeamMember.name == "Alice Anderson")).one()
        mid = member.id
        cfgsvc.remove_member(s, mid)
    with session_scope(engine) as s:
        assert s.exec(select(m.MemberDayOff).where(m.MemberDayOff.member_id == mid)).first() is None
        assert s.exec(select(m.NameAlias).where(m.NameAlias.target_member_id == mid)).first() is None


# --- sprint_service ---------------------------------------------------------

def test_build_sprints_from_db(engine):
    with session_scope(engine) as s:
        sprints = spsvc.build_sprints_from_db(s)
    ids = [sp.id for sp in sprints]
    assert ids == ["2026-16", "2026-18"]  # sorted, archive excluded
    assert all(isinstance(sp.start, date) for sp in sprints)


def test_create_sprint_accepts_free_form_label(engine):
    from sprint_pulse.services import sprint_service as spsvc
    with session_scope(engine) as s:
        row = spsvc.create_sprint(s, "June 2026", date(2026, 6, 1), date(2026, 6, 12))
        assert row.id == "june-2026"
        assert row.label == "June 2026"
        assert s.get(m.Sprint, "june-2026") is not None


def test_create_sprint_folds_accented_label_to_ascii(engine):
    from sprint_pulse.services import sprint_service as spsvc
    with session_scope(engine) as s:
        row = spsvc.create_sprint(s, "Été 2026", date(2026, 6, 1), date(2026, 6, 12))
        assert row.id == "ete-2026"
        assert row.label == "Été 2026"


def test_create_sprint_rejects_label_that_slugifies_empty(engine):
    from sprint_pulse.services import sprint_service as spsvc
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            spsvc.create_sprint(s, "!!!", date(2026, 6, 1), date(2026, 6, 12))


def test_create_sprint_rejects_duplicate_slug(engine):
    from sprint_pulse.services import sprint_service as spsvc
    with session_scope(engine) as s:
        spsvc.create_sprint(s, "June 2026", date(2026, 6, 1), date(2026, 6, 12))
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            spsvc.create_sprint(s, "june 2026", date(2026, 6, 15), date(2026, 6, 26))


def test_create_sprint_rejects_end_before_start(engine):
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            spsvc.create_sprint(s, "2026-99", date(2026, 5, 13), date(2026, 4, 30))


def test_set_sprint_dates_rejects_end_before_start(engine):
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            spsvc.set_sprint_dates(s, "2026-16", date(2026, 4, 29), date(2026, 4, 16))


def test_create_sprint_rejects_duplicate(engine):
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            spsvc.create_sprint(s, "2026-16", date(2026, 4, 16), date(2026, 4, 29))


def test_add_event_rejects_weekend(engine):
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            # 2026-04-18 is a Saturday
            spsvc.add_event(s, "2026-16", date(2026, 4, 18), "ga", "Release")


def test_add_event_rejects_unknown_kind(engine):
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            spsvc.add_event(s, "2026-16", date(2026, 4, 17), "bogus", "X")


def test_dashboard_hydration_reflects_member_day_off(engine):
    from sprint_pulse.services import time_off_service as tos
    with session_scope(engine) as s:
        alice = next(mem for mem in cfgsvc.list_members(s) if mem.name == "Alice Anderson")
        sprint = spsvc._get_sprint(s, "2026-16")
        tos.set_days(s, alice.id, [sprint.start], "pto", "PTO")
    with session_scope(engine) as s:
        sprints = spsvc.build_sprints_from_db(s)
    target = next(sp for sp in sprints if sp.id == "2026-16")
    assert any(e.associate == "Alice Anderson" and target.start in e.days
               for e in target.time_off)
