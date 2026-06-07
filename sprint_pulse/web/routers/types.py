"""Manage event & absence types (CRUD) on a dedicated /types page."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from sprint_pulse.errors import ValidationError
from sprint_pulse.services import type_service
from sprint_pulse.types_defaults import PALETTE
from sprint_pulse.web.deps import get_session, templates

router = APIRouter()


def _ctx(session: Session, *, error: str = "") -> dict:
    return {
        "active": "/types",
        "event_types": type_service.list_event_types(session),
        "absence_types": type_service.list_absence_types(session),
        "palette": PALETTE,
        "error": error,
    }


@router.get("/types", response_class=HTMLResponse)
def types_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "types.html", _ctx(session))


@router.post("/types/event", response_class=HTMLResponse)
def create_event(request: Request, label: str = Form(...), abbreviation: str = Form(...),
                 color: str = Form(...), session: Session = Depends(get_session)):
    try:
        type_service.create_event_type(session, label, abbreviation, color)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(request, "types.html", _ctx(session, error=e.display()))
    return RedirectResponse("/types", status_code=303)


@router.post("/types/absence", response_class=HTMLResponse)
def create_absence(request: Request, label: str = Form(...), abbreviation: str = Form(...),
                   color: str = Form(...), session: Session = Depends(get_session)):
    try:
        type_service.create_absence_type(session, label, abbreviation, color)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(request, "types.html", _ctx(session, error=e.display()))
    return RedirectResponse("/types", status_code=303)


@router.post("/types/event/{key}/update", response_class=HTMLResponse)
def update_event(request: Request, key: str, label: str = Form(...), abbreviation: str = Form(...),
                 color: str = Form(...), session: Session = Depends(get_session)):
    try:
        type_service.update_event_type(session, key, label, abbreviation, color)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(request, "types.html", _ctx(session, error=e.display()))
    return RedirectResponse("/types", status_code=303)


@router.post("/types/absence/{key}/update", response_class=HTMLResponse)
def update_absence(request: Request, key: str, label: str = Form(...), abbreviation: str = Form(...),
                   color: str = Form(...), session: Session = Depends(get_session)):
    try:
        type_service.update_absence_type(session, key, label, abbreviation, color)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(request, "types.html", _ctx(session, error=e.display()))
    return RedirectResponse("/types", status_code=303)


@router.post("/types/event/{key}/delete", response_class=HTMLResponse)
def delete_event(request: Request, key: str, session: Session = Depends(get_session)):
    try:
        type_service.delete_event_type(session, key)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(request, "types.html", _ctx(session, error=e.display()))
    return RedirectResponse("/types", status_code=303)


@router.post("/types/absence/{key}/delete", response_class=HTMLResponse)
def delete_absence(request: Request, key: str, session: Session = Depends(get_session)):
    try:
        type_service.delete_absence_type(session, key)
    except ValidationError as e:
        session.rollback()
        return templates.TemplateResponse(request, "types.html", _ctx(session, error=e.display()))
    return RedirectResponse("/types", status_code=303)
