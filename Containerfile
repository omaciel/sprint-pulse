# Browser-accessible Sprint Pulse — the same FastAPI app the desktop wraps.
#
#   podman build -t sprint-pulse .
#   podman run -p 8765:8765 -v sprint-pulse-data:/data \
#       -e JIRA_USERNAME=you@example.com -e JIRA_API_TOKEN=xxxx sprint-pulse
#
# Then open http://localhost:8765 — first run shows the setup wizard.
# The SQLite DB lives on the /data volume, so it survives container restarts.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install only the core/server dependencies from the lockfile (no desktop, no dev).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-default-groups
ENV PATH="/app/.venv/bin:$PATH"

COPY sprint_pulse ./sprint_pulse

# Headless: token comes from JIRA_API_TOKEN; bind all interfaces; DB on volume.
ENV SPRINT_PULSE_HEADLESS=1 \
    SPRINT_PULSE_HOST=0.0.0.0 \
    SPRINT_PULSE_PORT=8765 \
    SPRINT_PULSE_DB=/data/sprint-pulse.db

EXPOSE 8765
VOLUME /data

CMD ["python", "-m", "sprint_pulse.web"]
