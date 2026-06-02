"""Member calendar page: render, paint, clear, range, roster link."""
import pytest
from fastapi.testclient import TestClient

from sprint_pulse.migrate import import_yaml
from sprint_pulse.web.app import create_app


@pytest.fixture
def client(valid_dir):
    app = create_app(":memory:")
    import_yaml(app.state.engine, valid_dir / "config.yaml", valid_dir / "sprints_dir")
    return TestClient(app)


def _alice_id(client):
    from sprint_pulse.db.engine import session_scope
    from sprint_pulse.services import config_service as cfgsvc
    with session_scope(client.app.state.engine) as s:
        return next(mem.id for mem in cfgsvc.list_members(s) if mem.name == "Alice Anderson")


def test_member_page_renders_calendar(client):
    r = client.get(f"/members/{_alice_id(client)}?month=2026-07")
    assert r.status_code == 200
    assert "Alice Anderson" in r.text
    assert 'id="calendar"' in r.text


def test_paint_then_clear_single_day(client):
    mid = _alice_id(client)
    r = client.post(f"/members/{mid}/timeoff",
                    data={"date": "2026-07-20", "type": "pto", "notes": "PTO", "month": "2026-07"})
    assert r.status_code == 200 and "P" in r.text
    r2 = client.post(f"/members/{mid}/timeoff/clear",
                     data={"date": "2026-07-20", "month": "2026-07"})
    assert r2.status_code == 200
    from sprint_pulse.db.engine import session_scope
    from sprint_pulse.services import time_off_service as tos
    from datetime import date
    with session_scope(client.app.state.engine) as s:
        assert date(2026, 7, 20) not in tos.member_calendar(s, mid, 2026, 7)


def test_range_quick_add(client):
    mid = _alice_id(client)
    r = client.post(f"/members/{mid}/timeoff",
                    data={"start": "2026-07-20", "end": "2026-07-24", "type": "pto",
                          "notes": "", "month": "2026-07"})
    assert r.status_code == 200
    from sprint_pulse.db.engine import session_scope
    from sprint_pulse.services import time_off_service as tos
    with session_scope(client.app.state.engine) as s:
        cal = tos.member_calendar(s, mid, 2026, 7)
    assert len(cal) == 5  # Mon-Fri, weekend skipped


def test_weekend_paint_is_rejected_gracefully(client):
    mid = _alice_id(client)
    r = client.post(f"/members/{mid}/timeoff",
                    data={"date": "2026-07-25", "type": "pto", "notes": "", "month": "2026-07"})
    assert r.status_code == 200  # returns the calendar with an inline error, not a 500
    assert "Saturday" in r.text


def test_roster_links_to_member_page(client):
    r = client.get("/members")
    assert f'href="/members/{_alice_id(client)}"' in r.text


def test_invalid_month_falls_back_without_500(client):
    mid = _alice_id(client)
    for bad in ("2026-13", "2026-00", "abc", "2026"):
        r = client.get(f"/members/{mid}?month={bad}")
        assert r.status_code == 200
        assert 'id="calendar"' in r.text


def test_malformed_date_post_does_not_500(client):
    mid = _alice_id(client)
    r = client.post(f"/members/{mid}/timeoff",
                    data={"date": "not-a-date", "type": "pto", "notes": "", "month": "2026-07"})
    assert r.status_code == 200
    assert "invalid date" in r.text
    r2 = client.post(f"/members/{mid}/timeoff/clear",
                     data={"date": "not-a-date", "month": "2026-07"})
    assert r2.status_code == 200  # clear is best-effort, no 500


def test_edit_refreshes_sidebar_summary(client):
    # Painting/clearing a day must also refresh the sidebar (days-off stat +
    # Upcoming), delivered as an out-of-band swap so it updates live.
    mid = _alice_id(client)
    r = client.post(f"/members/{mid}/timeoff",
                    data={"date": "2026-07-20", "type": "pto", "notes": "", "month": "2026-07"})
    assert r.status_code == 200
    assert 'id="member-summary"' in r.text
    assert "hx-swap-oob" in r.text
    assert "days off" in r.text  # the stat card rides along in the refreshed sidebar
    r2 = client.post(f"/members/{mid}/timeoff/clear",
                     data={"date": "2026-07-20", "month": "2026-07"})
    assert r2.status_code == 200
    assert 'id="member-summary"' in r2.text and "hx-swap-oob" in r2.text
