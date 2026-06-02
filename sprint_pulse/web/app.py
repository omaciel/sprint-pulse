"""FastAPI application factory.

The same app runs three ways:
  - desktop:    wrapped by pywebview (sprint_pulse/desktop.py)
  - container:  `python -m sprint_pulse.web`
  - tests:      create_app(db_path=":memory:") + TestClient
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from sprint_pulse.db.engine import create_db_and_tables, get_engine
from sprint_pulse.web.paths import STATIC_DIR
from sprint_pulse.web.routers import config_page, dashboard, members, scheduler, setup, sprints
from sprint_pulse.web.scheduler import SchedulerManager


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Runs under uvicorn (and `with TestClient(app)`), but NOT for a bare
    # TestClient(app) — so most tests don't spin up a background thread.
    manager = SchedulerManager(app.state.engine)
    manager.start()
    app.state.scheduler = manager
    try:
        yield
    finally:
        manager.shutdown()


def create_app(db_path: Path | str | None = None) -> FastAPI:
    app = FastAPI(title="Sprint Pulse", lifespan=_lifespan)

    engine = get_engine(db_path)
    create_db_and_tables(engine)
    app.state.engine = engine
    # Fallback manager (not started) so routes work even without lifespan,
    # e.g. under a bare TestClient. run_now/reschedule still operate on the DB.
    app.state.scheduler = SchedulerManager(engine)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(dashboard.router)
    app.include_router(setup.router)
    app.include_router(config_page.router)
    app.include_router(members.router)
    app.include_router(sprints.router)
    app.include_router(scheduler.router)

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return app
