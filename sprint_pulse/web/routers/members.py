"""Team management: list / add / rename / toggle-excluded / remove."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from sprint_pulse.errors import ValidationError
from sprint_pulse.render import calendar_type_css
from sprint_pulse.services import config_service, time_off_service, type_service
from sprint_pulse.sprints import working_days
from sprint_pulse.web.deps import get_session, templates

router = APIRouter()


def _table(request: Request, session: Session, error: str = "") -> HTMLResponse:
    members = config_service.list_members(session)
    return templates.TemplateResponse(
        request,
        "partials/_members_table.html",
        {"members": members, "error": error},
    )


@router.get("/members", response_class=HTMLResponse)
def members_page(request: Request, session: Session = Depends(get_session)):
    members = config_service.list_members(session)
    return templates.TemplateResponse(
        request, "members.html", {"members": members, "active": "/members"}
    )


@router.post("/members", response_class=HTMLResponse)
def add_member(
    request: Request,
    name: str = Form(...),
    is_excluded: bool = Form(False),
    session: Session = Depends(get_session),
):
    try:
        config_service.add_member(session, name, is_excluded=is_excluded)
    except ValidationError as e:
        session.rollback()
        return _table(request, session, error=e.display())
    return _table(request, session)


@router.post("/members/{member_id}/toggle", response_class=HTMLResponse)
def toggle(request: Request, member_id: int, session: Session = Depends(get_session)):
    try:
        config_service.toggle_excluded(session, member_id)
    except ValidationError as e:
        session.rollback()
        return _table(request, session, error=e.display())
    return _table(request, session)


@router.post("/members/{member_id}/delete", response_class=HTMLResponse)
def delete(request: Request, member_id: int, session: Session = Depends(get_session)):
    try:
        config_service.remove_member(session, member_id)
    except ValidationError as e:
        session.rollback()
        return _table(request, session, error=e.display())
    return _table(request, session)


def _parse_month(value: str | None) -> tuple[int, int]:
    """'YYYY-MM' -> (year, month); falls back to today on missing/invalid input."""
    try:
        y, mo = (value or "").split("-")
        year, month = int(y), int(mo)
        if not (1 <= month <= 12):
            raise ValueError
        return year, month
    except (ValueError, AttributeError):
        today = date.today()
        return today.year, today.month


def _shift_month(year: int, month: int, delta: int) -> str:
    idx = (year * 12 + (month - 1)) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _calendar_context(session: Session, member_id: int, month: str | None, *, error: str = "") -> dict:
    member = config_service.get_member(session, member_id)
    year, mo = _parse_month(month)
    day_map = time_off_service.member_calendar(session, member_id, year, mo)
    today = date.today()
    absence_types = type_service.list_absence_types(session)
    letters = {t.key: t.abbreviation for t in absence_types}
    return {
        "active": "/members",
        "member": member,
        "month_value": f"{year:04d}-{mo:02d}",
        "month_label": f"{date(year, mo, 1):%B %Y}",
        "prev_month": _shift_month(year, mo, -1),
        "next_month": _shift_month(year, mo, 1),
        "weeks": time_off_service.build_month_grid(year, mo, day_map, letters),
        "absence_types": absence_types,
        "cal_type_css": calendar_type_css(absence_types),
        "summary": time_off_service.member_summary(session, member_id, today),
        "error": error,
    }


@router.get("/members/{member_id}", response_class=HTMLResponse)
def member_detail(request: Request, member_id: int, month: str = "", session: Session = Depends(get_session)):
    try:
        ctx = _calendar_context(session, member_id, month or None)
    except ValidationError:
        return RedirectResponse("/members", status_code=303)
    # HTMX month-nav links want only the calendar fragment; full nav requests get the page.
    name = "partials/_calendar.html" if request.headers.get("HX-Request") else "member_detail.html"
    return templates.TemplateResponse(request, name, ctx)


@router.post("/members/{member_id}/timeoff", response_class=HTMLResponse)
def set_member_time_off(
    request: Request,
    member_id: int,
    date_: str = Form("", alias="date"),
    start: str = Form(""),
    end: str = Form(""),
    type: str = Form("pto"),
    notes: str = Form(""),
    month: str = Form(""),
    session: Session = Depends(get_session),
):
    error = ""
    try:
        try:
            if start and end:
                s, e = date.fromisoformat(start), date.fromisoformat(end)
                days = working_days(s, e) if e >= s else []
            elif date_:
                days = [date.fromisoformat(date_)]
            else:
                raise ValidationError("a date is required", field="date")
        except ValueError:
            raise ValidationError("invalid date", field="date")
        if not days:
            raise ValidationError("end is before start", field="end")
        time_off_service.set_days(session, member_id, days, type, notes)
    except ValidationError as exc:
        session.rollback()
        error = exc.display()
    return templates.TemplateResponse(
        request, "partials/_calendar_edit.html", _calendar_context(session, member_id, month, error=error)
    )


@router.post("/members/{member_id}/timeoff/clear", response_class=HTMLResponse)
def clear_member_time_off(
    request: Request,
    member_id: int,
    date_: str = Form("", alias="date"),
    month: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        if date_:
            time_off_service.clear_days(session, member_id, [date.fromisoformat(date_)])
    except (ValidationError, ValueError):
        session.rollback()
    return templates.TemplateResponse(
        request, "partials/_calendar_edit.html", _calendar_context(session, member_id, month)
    )
