"""Shared FastAPI dependencies + Jinja environment."""
from __future__ import annotations

from typing import Iterator

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from sprint_pulse.render import CSS as RENDER_CSS
from sprint_pulse.web.nav import APP_BAR_CSS, app_bar_html
from sprint_pulse.web.paths import TEMPLATES_DIR

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
# Expose the shared chrome + the renderer's design tokens to every template so
# management pages match the dashboard palette.
templates.env.globals["app_bar"] = app_bar_html
templates.env.globals["app_bar_css"] = APP_BAR_CSS
templates.env.globals["render_css"] = RENDER_CSS


def get_session(request: Request) -> Iterator[Session]:
    """Yield a session bound to the app engine; commit on clean exit.

    Routes that catch a ``ValidationError`` should call ``session.rollback()``
    before returning their error fragment so nothing partial is committed here.
    """
    engine = request.app.state.engine
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
