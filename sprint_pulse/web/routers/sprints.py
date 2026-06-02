"""Sprint, event, and time-off management."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from sprint_pulse.db import models as m
from sprint_pulse.errors import ValidationError
from sprint_pulse.services import config_service, sprint_service, time_off_service
from sprint_pulse.sprints import EVENT_KINDS
from sprint_pulse.web.deps import get_session, templates

router = APIRouter()


def _list_context(session: Session, *, error: str = "") -> dict:
    rows = sorted(
        session.exec(select(m.Sprint)).all(),
        key=sprint_service.sort_key,
        reverse=True,
    )
    return {
        "active_sprints": [r for r in rows if not r.archived],
        "archived_sprints": [r for r in rows if r.archived],
        "active": "/sprints",
        "error": error,
    }


@router.get("/sprints", response_class=HTMLResponse)
def sprints_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "sprints.html", _list_context(session))


@router.post("/sprints", response_class=HTMLResponse)
def create_sprint(
    request: Request,
    sprint_id: str = Form(...),
    start: date = Form(...),
    end: date = Form(...),
    session: Session = Depends(get_session),
):
    try:
        sprint_service.create_sprint(session, sprint_id, start, end)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(
            request, "sprints.html", _list_context(session, error=e.display())
        )
    return RedirectResponse(f"/sprints/{sprint_id}", status_code=303)


_IMPORT_PAGE_SIZE = 25


@router.get("/sprints/import", response_class=HTMLResponse)
def import_page(
    request: Request,
    page: int = 1,
    notice: str = "",
    wizard: int = 0,
    session: Session = Depends(get_session),
):
    candidates, error = sprint_service.available_jira_sprints(session)
    total = len(candidates) if candidates else 0
    pages = max(1, (total + _IMPORT_PAGE_SIZE - 1) // _IMPORT_PAGE_SIZE)
    page = min(max(page, 1), pages)
    lo = (page - 1) * _IMPORT_PAGE_SIZE
    page_items = (candidates or [])[lo:lo + _IMPORT_PAGE_SIZE]
    importable_total = sum(
        1 for c in (candidates or []) if c["importable"] and not c["already_imported"]
    )
    return templates.TemplateResponse(
        request,
        "sprints_import.html",
        {
            "active": "/sprints",
            "candidates": page_items,
            "error": error,
            "notice": notice,
            "wizard": bool(wizard),
            "settings": config_service.get_settings(session),
            "page": page,
            "pages": pages,
            "total": total,
            "range_lo": lo + 1 if total else 0,
            "range_hi": lo + len(page_items),
            "importable_total": importable_total,
        },
    )


@router.post("/sprints/import")
async def do_import(request: Request, session: Session = Depends(get_session)):
    # Two actions: "all" imports every importable candidate across all pages;
    # otherwise import the rows submitted (current page + any carried over from
    # other pages via hidden inputs). Each carries name="jira_ids" (Jira id) and
    # a text "id_<jira_id>". In wizard mode we continue to the team step.
    form = await request.form()
    action = form.get("action", "selected")
    wizard = form.get("wizard") == "1"
    self_url = "/sprints/import?wizard=1" if wizard else "/sprints/import"
    next_url = "/setup/team" if wizard else "/sprints"

    if action == "all":
        candidates, _ = sprint_service.available_jira_sprints(session)
        selections = [
            (c["jira_id"], c["suggested_id"])
            for c in (candidates or [])
            if c["importable"] and not c["already_imported"] and c["suggested_id"]
        ]
    else:
        selections = []
        for raw in form.getlist("jira_ids"):
            try:
                jira_id = int(raw)
            except (TypeError, ValueError):
                continue
            selections.append((jira_id, form.get(f"id_{raw}", "")))

    if not selections:
        # Nothing chosen — bounce back with a gentle notice instead of a no-op.
        sep = "&" if "?" in self_url else "?"
        return RedirectResponse(f"{self_url}{sep}notice=none", status_code=303)

    try:
        sprint_service.import_jira_sprints(session, selections)
    except ValidationError:
        session.rollback()
    return RedirectResponse(next_url, status_code=303)


@router.post("/sprints/{sprint_id}/archive")
def archive_sprint(sprint_id: str, session: Session = Depends(get_session)):
    try:
        sprint_service.set_archived(session, sprint_id, True)
    except ValidationError:
        session.rollback()
    return RedirectResponse("/sprints", status_code=303)


@router.post("/sprints/{sprint_id}/unarchive")
def unarchive_sprint(sprint_id: str, session: Session = Depends(get_session)):
    try:
        sprint_service.set_archived(session, sprint_id, False)
    except ValidationError:
        session.rollback()
    return RedirectResponse("/sprints", status_code=303)


@router.post("/sprints/{sprint_id}/delete")
def delete_sprint(sprint_id: str, session: Session = Depends(get_session)):
    try:
        sprint_service.delete_sprint(session, sprint_id)
    except ValidationError:
        session.rollback()
    return RedirectResponse("/sprints", status_code=303)


def _detail_context(session: Session, sprint_id: str, *, event_error="", date_error=""):
    sprint = session.get(m.Sprint, sprint_id)
    events = session.exec(
        select(m.Event).where(m.Event.sprint_id == sprint_id).order_by(m.Event.date)
    ).all()
    member_name = {mem.id: mem.name for mem in config_service.list_members(session)}
    outage = []
    if sprint is not None:
        outage = sorted(
            time_off_service.outage_entries(session, sprint.start, sprint.end, member_name),
            key=lambda e: (e.associate, e.days[0]),
        )
    return {
        "active": "/sprints",
        "sprint": sprint,
        "events": events,
        "event_kinds": EVENT_KINDS,
        "outage": outage,
        "member_id_by_name": {name: mid for mid, name in member_name.items()},
        "event_error": event_error,
        "date_error": date_error,
    }


@router.get("/sprints/{sprint_id}", response_class=HTMLResponse)
def sprint_detail(request: Request, sprint_id: str, session: Session = Depends(get_session)):
    if session.get(m.Sprint, sprint_id) is None:
        return RedirectResponse("/sprints", status_code=303)
    return templates.TemplateResponse(
        request, "sprint_detail.html", _detail_context(session, sprint_id)
    )


@router.post("/sprints/{sprint_id}/dates", response_class=HTMLResponse)
def set_dates(
    request: Request,
    sprint_id: str,
    start: date = Form(...),
    end: date = Form(...),
    session: Session = Depends(get_session),
):
    try:
        sprint_service.set_sprint_dates(session, sprint_id, start, end)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(
            request, "sprint_detail.html", _detail_context(session, sprint_id, date_error=e.display())
        )
    return RedirectResponse(f"/sprints/{sprint_id}", status_code=303)


@router.post("/sprints/{sprint_id}/events", response_class=HTMLResponse)
def add_event(
    request: Request,
    sprint_id: str,
    event_date: date = Form(...),
    kind: str = Form(...),
    title: str = Form(...),
    session: Session = Depends(get_session),
):
    error = ""
    try:
        sprint_service.add_event(session, sprint_id, event_date, kind, title)
    except ValidationError as e:
        session.rollback()
        error = e.display()
    return templates.TemplateResponse(
        request,
        "partials/_events.html",
        _detail_context(session, sprint_id, event_error=error),
    )


@router.post("/sprints/{sprint_id}/events/{event_id}/delete", response_class=HTMLResponse)
def delete_event(request: Request, sprint_id: str, event_id: int, session: Session = Depends(get_session)):
    try:
        sprint_service.delete_event(session, event_id)
    except ValidationError:
        session.rollback()
    return templates.TemplateResponse(
        request, "partials/_events.html", _detail_context(session, sprint_id)
    )


