# Browser-accessible Sprint Pulse — the same FastAPI app the desktop wraps.
#
#   podman build -t sprint-pulse .
#   podman run -p 8765:8765 -v sprint-pulse-data:/data \
#       -e JIRA_USERNAME=you@example.com -e JIRA_API_TOKEN=xxxx sprint-pulse
#
# Then open http://localhost:8765 — first run shows the setup wizard.
# The SQLite DB lives on the /data volume, so it survives container restarts.
FROM python:3.12-slim

WORKDIR /app

COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

COPY sprint_pulse ./sprint_pulse
COPY data ./data

# Headless: token comes from JIRA_API_TOKEN; bind all interfaces; DB on volume.
ENV SPRINT_PULSE_HEADLESS=1 \
    SPRINT_PULSE_HOST=0.0.0.0 \
    SPRINT_PULSE_PORT=8765 \
    SPRINT_PULSE_DB=/data/sprint-pulse.db

EXPOSE 8765
VOLUME /data

CMD ["python", "-m", "sprint_pulse.web"]
