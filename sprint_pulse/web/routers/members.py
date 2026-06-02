"""Team management: list / add / rename / toggle-orchestration / remove."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from sprint_pulse.errors import ValidationError
from sprint_pulse.services import config_service
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
    is_orchestration: bool = Form(False),
    session: Session = Depends(get_session),
):
    try:
        config_service.add_member(session, name, is_orchestration=is_orchestration)
    except ValidationError as e:
        session.rollback()
        return _table(request, session, error=e.display())
    return _table(request, session)


@router.post("/members/{member_id}/toggle", response_class=HTMLResponse)
def toggle(request: Request, member_id: int, session: Session = Depends(get_session)):
    try:
        config_service.toggle_orchestration(session, member_id)
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
