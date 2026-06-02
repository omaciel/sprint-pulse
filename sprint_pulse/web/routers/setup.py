"""First-run setup wizard.

Flow:
  /setup            welcome — guided setup or YAML import
  /setup/wizard     step 1: app settings + Jira connection (+ test)
  /setup/team       step 2: add members (or import YAML), then finish
  /setup/import     one-click import of the bundled data/ YAML

Each page bails to "/" once the DB has members, so the wizard can't be
re-entered to clobber a configured install.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from sprint_pulse.db import models as m
from sprint_pulse.errors import ValidationError
from sprint_pulse.migrate import MigrationError, import_yaml
from sprint_pulse.services import config_service, jira_service, secrets
from sprint_pulse.web.deps import get_session, templates

router = APIRouter()

# YAML import source for the wizard's "Import from YAML". Defaults to the repo's
# data/, overridable via SPRINT_PULSE_SEED_DIR (the demo points it at examples/).
def _seed_dir() -> Path:
    override = os.environ.get("SPRINT_PULSE_SEED_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "data"


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, session: Session = Depends(get_session)):
    if not config_service.is_empty(session):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "setup/welcome.html", {"active": "", "has_yaml": (_seed_dir() / "config.yaml").exists()}
    )


@router.get("/setup/wizard", response_class=HTMLResponse)
def wizard_step1(request: Request, session: Session = Depends(get_session)):
    settings = config_service.get_settings(session)
    return templates.TemplateResponse(
        request, "setup/wizard.html", {"active": "", "settings": settings}
    )


@router.post("/setup/wizard", response_class=HTMLResponse)
def wizard_step1_save(
    request: Request,
    working_days_per_sprint: int = Form(10),
    team_name: str = Form("Wisdom"),
    jira_site: str = Form(""),
    jira_board: str = Form(""),
    jira_username: str = Form(""),
    jira_token: str = Form(""),
    session: Session = Depends(get_session),
):
    config_service.apply_jira_settings(
        session,
        working_days_per_sprint=working_days_per_sprint,
        team_name=team_name,
        jira_site=jira_site,
        jira_board=jira_board,
        jira_username=jira_username,
        jira_token=jira_token,
    )
    # Step 2 of the wizard is "import sprints" (the shared import page in wizard mode).
    return RedirectResponse("/sprints/import?wizard=1", status_code=303)


@router.post("/setup/wizard/test", response_class=HTMLResponse)
def wizard_test(
    request: Request,
    jira_site: str = Form(""),
    jira_board: str = Form(""),
    jira_username: str = Form(""),
    jira_token: str = Form(""),
):
    """Test the entered (not-yet-saved) credentials."""
    token = jira_token.strip() or secrets.get_token(secrets.detect_backend(), jira_username.strip())
    msg, ok = jira_service.probe(
        jira_site.strip(), jira_board.strip(), jira_username.strip(), token
    )
    return templates.TemplateResponse(
        request, "partials/_conn_result.html", {"message": msg, "ok": ok}
    )


@router.get("/setup/team", response_class=HTMLResponse)
def team_page(request: Request, session: Session = Depends(get_session)):
    members = config_service.list_members(session)
    has_sprints = session.exec(select(m.Sprint)).first() is not None
    return templates.TemplateResponse(
        request,
        "setup/team.html",
        {"active": "", "members": members, "error": "", "has_sprints": has_sprints},
    )


@router.post("/setup/team/add", response_class=HTMLResponse)
def team_add(
    request: Request,
    name: str = Form(...),
    is_orchestration: bool = Form(False),
    session: Session = Depends(get_session),
):
    error = ""
    try:
        config_service.add_member(session, name, is_orchestration=is_orchestration)
    except ValidationError as e:
        session.rollback()
        error = e.display()
    members = config_service.list_members(session)
    return templates.TemplateResponse(
        request, "partials/_setup_members.html", {"members": members, "error": error}
    )


@router.post("/setup/import")
def do_import(session: Session = Depends(get_session)):
    """One-click import of the bundled data/ YAML."""
    engine = session.get_bind()
    try:
        seed = _seed_dir()
        import_yaml(engine, seed / "config.yaml", seed / "sprints", force=False)
    except (MigrationError, FileNotFoundError):
        return RedirectResponse("/setup", status_code=303)
    return RedirectResponse("/", status_code=303)
