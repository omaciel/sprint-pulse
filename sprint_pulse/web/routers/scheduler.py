"""Scheduler UI: cadence config, Run-now, and last-run status."""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from sprint_pulse.errors import ValidationError
from sprint_pulse.services import config_service
from sprint_pulse.web.deps import get_session, templates

router = APIRouter()


@router.get("/scheduler", response_class=HTMLResponse)
def scheduler_page(request: Request, session: Session = Depends(get_session), error: str = ""):
    settings = config_service.get_settings(session)
    return templates.TemplateResponse(
        request, "scheduler.html", {"active": "/scheduler", "settings": settings, "error": error}
    )


@router.post("/scheduler")
def save_scheduler(
    request: Request,
    enabled: bool = Form(False),
    trigger: str = Form("interval"),
    value: str = Form("60"),
    session: Session = Depends(get_session),
):
    manager = request.app.state.scheduler
    try:
        manager.reschedule(enabled=enabled, trigger=trigger, value=value)
    except ValidationError as e:
        qs = urlencode({"error": e.display()})
        return RedirectResponse(f"/scheduler?{qs}", status_code=303)
    return RedirectResponse("/scheduler", status_code=303)


@router.post("/scheduler/run", response_class=HTMLResponse)
def run_now(request: Request, session: Session = Depends(get_session)):
    request.app.state.scheduler.run_now()
    settings = config_service.get_settings(session)
    return templates.TemplateResponse(request, "partials/_run_status.html", {"settings": settings})


@router.get("/scheduler/status", response_class=HTMLResponse)
def status(request: Request, session: Session = Depends(get_session)):
    settings = config_service.get_settings(session)
    return templates.TemplateResponse(request, "partials/_run_status.html", {"settings": settings})
