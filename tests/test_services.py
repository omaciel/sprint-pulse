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
        assert s.exec(select(m.TimeOff).where(m.TimeOff.member_id == mid)).first() is None
        assert s.exec(select(m.NameAlias).where(m.NameAlias.target_member_id == mid)).first() is None


# --- sprint_service ---------------------------------------------------------

def test_build_sprints_from_db(engine):
    with session_scope(engine) as s:
        sprints = spsvc.build_sprints_from_db(s)
    ids = [sp.id for sp in sprints]
    assert ids == ["2026-16", "2026-18"]  # sorted, archive excluded
    assert all(isinstance(sp.start, date) for sp in sprints)


def test_create_sprint_rejects_end_before_start(engine):
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            spsvc.create_sprint(s, "2026-99", date(2026, 5, 13), date(2026, 4, 30))


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


def test_add_time_off_unknown_associate_suggests(engine):
    with session_scope(engine) as s:
        with pytest.raises(ValidationError) as ei:
            spsvc.add_time_off(s, "2026-16", "Alice Andersen", [date(2026, 4, 17)], "PTO")
    assert "did you mean" in (ei.value.suggestion or "")


def test_add_time_off_rejects_out_of_range_day(engine):
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            spsvc.add_time_off(s, "2026-16", "Alice Anderson", [date(2026, 12, 25)], "PTO")


def test_add_time_off_infers_type_and_persists(engine):
    with session_scope(engine) as s:
        created = spsvc.add_time_off(
            s, "2026-16", "Alice Anderson", [date(2026, 4, 17)], "Christmas holiday"
        )
        assert created[0].type == "holiday"
    with session_scope(engine) as s:
        sprints = {sp.id: sp for sp in spsvc.build_sprints_from_db(s)}
        entries = [t for t in sprints["2026-16"].time_off if t.associate == "Alice Anderson"]
    assert any(t.type == "holiday" for t in entries)


def test_add_time_off_all_expands_to_every_member(engine):
    with session_scope(engine) as s:
        created = spsvc.add_time_off(s, "2026-16", "__all__", [date(2026, 4, 17)], "Company holiday")
    assert len(created) == 11
