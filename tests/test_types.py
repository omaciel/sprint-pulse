from sprint_pulse.types_defaults import (
    PALETTE, DEFAULT_EVENT_TYPES, DEFAULT_ABSENCE_TYPES,
    DEFAULT_EVENT_KEYS, DEFAULT_ABSENCE_KEYS,
)


def test_defaults_use_palette_colors():
    for t in DEFAULT_EVENT_TYPES + DEFAULT_ABSENCE_TYPES:
        assert t["color"] in PALETTE, f'{t["key"]} color {t["color"]} not in palette'


def test_default_keys_match_legacy_values():
    assert DEFAULT_EVENT_KEYS == {"tags", "gono", "ga", "freeze", "test"}
    assert DEFAULT_ABSENCE_KEYS == {"pto", "holiday", "company", "partial", "tentative"}


def test_defaults_have_required_fields():
    for t in DEFAULT_EVENT_TYPES + DEFAULT_ABSENCE_TYPES:
        assert set(t) == {"key", "label", "abbreviation", "color", "sort_order"}
        assert 1 <= len(t["abbreviation"]) <= 2


def test_seed_creates_defaults_idempotently():
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc
    engine = get_engine(":memory:")
    create_db_and_tables(engine)  # should auto-seed
    with session_scope(engine) as s:
        assert {t.key for t in tsvc.list_event_types(s)} == DEFAULT_EVENT_KEYS
        assert {t.key for t in tsvc.list_absence_types(s)} == DEFAULT_ABSENCE_KEYS
    with session_scope(engine) as s:
        tsvc.seed_default_types(s)  # re-run adds no dupes
    with session_scope(engine) as s:
        assert len(tsvc.list_event_types(s)) == len(DEFAULT_EVENT_KEYS)


def test_seed_skips_when_user_deleted_a_default():
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        tsvc.delete_event_type(s, "test")  # unused -> allowed
    with session_scope(engine) as s:
        tsvc.seed_default_types(s)  # must NOT re-add 'test'
    with session_scope(engine) as s:
        assert "test" not in {t.key for t in tsvc.list_event_types(s)}


def test_delete_blocked_while_type_in_use():
    from datetime import date
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc, sprint_service as spsvc, config_service as cfgsvc
    from sprint_pulse.errors import ValidationError
    import pytest
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        cfgsvc.add_member(s, "Alice Anderson")
        spsvc.create_sprint(s, "2026-16", date(2026, 4, 16), date(2026, 4, 29))
        spsvc.add_event(s, "2026-16", date(2026, 4, 17), "ga", "Release")
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            tsvc.delete_event_type(s, "ga")  # in use -> blocked


def test_create_validates_color_and_abbreviation():
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc
    from sprint_pulse.errors import ValidationError
    import pytest
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            tsvc.create_absence_type(s, "Bad Color", "B", "#000000")  # not in palette
        with pytest.raises(ValidationError):
            tsvc.create_absence_type(s, "Too Long Abbr", "ABC", "#A0CBE8")  # >2 chars
        row = tsvc.create_absence_type(s, "Jury Duty", "J", "#A0CBE8")
        assert row.key == "jury-duty"


def test_update_event_type_keeps_key_changes_fields():
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        row = tsvc.update_event_type(s, "ga", "Generally Available", "GA", "#A0CBE8")
        assert row.key == "ga"            # PK unchanged
        assert row.label == "Generally Available"
        assert row.abbreviation == "GA"
        assert row.color == "#A0CBE8"


def test_update_missing_type_raises():
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc
    from sprint_pulse.errors import ValidationError
    import pytest
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            tsvc.update_absence_type(s, "nope", "X", "X", "#A0CBE8")


def test_delete_missing_type_raises():
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc
    from sprint_pulse.errors import ValidationError
    import pytest
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        with pytest.raises(ValidationError):
            tsvc.delete_event_type(s, "ghost")


def test_add_event_accepts_custom_type_rejects_unknown():
    from datetime import date
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc, sprint_service as spsvc
    from sprint_pulse.errors import ValidationError
    import pytest
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        spsvc.create_sprint(s, "2026-16", date(2026, 4, 16), date(2026, 4, 29))
        tsvc.create_event_type(s, "Webinar", "W", "#A0CBE8")  # key "webinar"
        spsvc.add_event(s, "2026-16", date(2026, 4, 17), "webinar", "Launch webinar")
        with pytest.raises(ValidationError):
            spsvc.add_event(s, "2026-16", date(2026, 4, 20), "nope", "bad")


def test_sprint_detail_lists_custom_event_type():
    """Sprint detail 'Add event' dropdown renders DB event-type labels (not bare keys)."""
    from datetime import date
    from fastapi.testclient import TestClient
    from sprint_pulse.web.app import create_app

    client = TestClient(create_app(":memory:"))
    # Create a sprint via HTTP
    client.post(
        "/sprints",
        data={"label": "2026-16", "start": "2026-04-16", "end": "2026-04-29"},
        follow_redirects=False,
    )
    # Fetch the sprint detail page
    page = client.get("/sprints/2026-16")
    assert page.status_code == 200
    # The dropdown should render labels, not bare keys — "Target release" is the
    # default label for key "ga".
    assert "Target release" in page.text
    # Confirm the option carries the correct value attribute too
    assert '<option value="ga">Target release</option>' in page.text


def test_full_html_css_is_data_driven():
    from datetime import date
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc, config_service as cfgsvc, sprint_service as spsvc
    from sprint_pulse.services.sprint_service import build_dashboard_data
    from sprint_pulse.render import render_full_html
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        cfgsvc.add_member(s, "Alice Anderson")
        spsvc.create_sprint(s, "2026-16", date(2026, 4, 16), date(2026, 4, 29))
        tsvc.create_absence_type(s, "Jury Duty", "J", "#A0CBE8")
        cfg = cfgsvc.build_config_from_db(s)
        data = build_dashboard_data(s, cfg)
    html = render_full_html(data, cfg)
    assert "#A0CBE8" in html          # custom type color injected into generated CSS
    assert "Jury Duty" in html        # custom type appears in the legend
    assert "td.jury-duty" in html     # generated per-type CSS rule by key


def test_set_days_accepts_custom_absence_type_rejects_unknown():
    from datetime import date
    from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
    from sprint_pulse.services import type_service as tsvc, time_off_service as tos, config_service as cfgsvc
    from sprint_pulse.errors import ValidationError
    import pytest
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        member = cfgsvc.add_member(s, "Alice Anderson")
        tsvc.create_absence_type(s, "Jury Duty", "J", "#A0CBE8")  # key "jury-duty"
        tos.set_days(s, member.id, [date(2026, 4, 17)], "jury-duty", "court")
        with pytest.raises(ValidationError):
            tos.set_days(s, member.id, [date(2026, 4, 18)], "bogus", "")
