"""Dashboard: the live availability heatmap (reuses render.render_full_html)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from sprint_pulse.db import models as m
from sprint_pulse.render import render_full_html
from sprint_pulse.services import config_service, sprint_service
from sprint_pulse.web.deps import get_session
from sprint_pulse.web.nav import inject_app_bar

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(session: Session = Depends(get_session)):
    cfg = config_service.build_config_from_db(session)
    data = sprint_service.build_dashboard_data(session, cfg)
    if data:
        # Render whenever there are (active) sprints — even before a team exists;
        # the heatmap just has no member rows yet and availability shows n/a.
        cfg_by_sprint = sprint_service.build_sprint_configs(session, cfg)
        return HTMLResponse(
            inject_app_bar(
                render_full_html(data, cfg, cfg_by_sprint=cfg_by_sprint), active="/"
            )
        )

    has_members = not config_service.is_empty(session)
    has_sprints = session.exec(select(m.Sprint)).first() is not None
    if not has_members and not has_sprints:
        return RedirectResponse("/setup", status_code=303)  # fresh install → wizard
    # Members but nothing to chart (no sprints, or only archived ones).
    return RedirectResponse("/sprints", status_code=303)
