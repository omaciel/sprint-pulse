"""Settings + Jira connection configuration."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from sprint_pulse.errors import ValidationError
from sprint_pulse.services import config_service, jira_service, secrets
from sprint_pulse.web.deps import get_session, templates

router = APIRouter()


@router.get("/config", response_class=HTMLResponse)
def config_page(request: Request, session: Session = Depends(get_session), saved: bool = False):
    settings = config_service.get_settings(session)
    return templates.TemplateResponse(
        request,
        "config.html",
        {"settings": settings, "active": "/config", "saved": saved, "error": ""},
    )


@router.post("/config", response_class=HTMLResponse)
def save_config(
    request: Request,
    working_days_per_sprint: int = Form(...),
    team_name: str = Form("My Team"),
    jira_site: str = Form(""),
    jira_board: str = Form(""),
    jira_username: str = Form(""),
    jira_token: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        config_service.apply_jira_settings(
            session,
            working_days_per_sprint=working_days_per_sprint,
            team_name=team_name,
            jira_site=jira_site,
            jira_board=jira_board,
            jira_username=jira_username,
            jira_token=jira_token,
        )
    except ValidationError as e:
        session.rollback()
        settings = config_service.get_settings(session)
        return templates.TemplateResponse(
            request,
            "config.html",
            {"settings": settings, "active": "/config", "saved": False, "error": e.display()},
        )
    return RedirectResponse("/config?saved=true", status_code=303)


@router.post("/config/test-connection", response_class=HTMLResponse)
def test_connection(request: Request, session: Session = Depends(get_session)):
    settings = config_service.get_settings(session)
    token = secrets.get_token(settings.token_ref, settings.jira_username)
    msg, ok = jira_service.probe(
        settings.jira_site, settings.jira_board, settings.jira_username, token
    )
    return templates.TemplateResponse(
        request, "partials/_conn_result.html", {"message": msg, "ok": ok}
    )
