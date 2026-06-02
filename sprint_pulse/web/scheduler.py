"""In-process APScheduler wrapper.

One scheduler per app/engine. The cadence + enabled flag live in Settings, so
the schedule survives restarts. The job runs the refresh pipeline in its own
session (it executes on a background thread).
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.engine import Engine

from sprint_pulse.db.engine import session_scope
from sprint_pulse.errors import ValidationError
from sprint_pulse.services import config_service, refresh

_JOB_ID = "refresh"


def build_trigger(trigger: str, value: str):
    """Build an APScheduler trigger, raising ValidationError on bad input."""
    if trigger == "interval":
        try:
            minutes = int(value)
            if minutes < 1:
                raise ValueError
        except ValueError:
            raise ValidationError("interval must be a positive number of minutes", field="value")
        return IntervalTrigger(minutes=minutes)
    if trigger == "cron":
        try:
            return CronTrigger.from_crontab(value)
        except Exception:
            raise ValidationError(f'invalid cron expression "{value}"', field="value")
    raise ValidationError(f'unknown trigger "{trigger}"', field="trigger")


class SchedulerManager:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.scheduler = BackgroundScheduler()

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
        self._sync_from_settings()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def _job(self) -> None:
        with session_scope(self.engine) as session:
            refresh.refresh_all(session)

    def _sync_from_settings(self) -> None:
        with session_scope(self.engine) as session:
            settings = config_service.get_settings(session)
            enabled = settings.scheduler_enabled
            trigger, value = settings.scheduler_trigger, settings.scheduler_value

        existing = self.scheduler.get_job(_JOB_ID)
        if existing:
            existing.remove()
        if enabled:
            self.scheduler.add_job(self._job, build_trigger(trigger, value), id=_JOB_ID)

    def reschedule(self, *, enabled: bool, trigger: str, value: str) -> None:
        """Persist new schedule settings and apply them. Validates first."""
        build_trigger(trigger, value)  # raises ValidationError before persisting
        with session_scope(self.engine) as session:
            config_service.update_settings(
                session,
                scheduler_enabled=enabled,
                scheduler_trigger=trigger,
                scheduler_value=value,
            )
        if self.scheduler.running:
            self._sync_from_settings()

    def run_now(self) -> dict:
        with session_scope(self.engine) as session:
            return refresh.refresh_all(session)
