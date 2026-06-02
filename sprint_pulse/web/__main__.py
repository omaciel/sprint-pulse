"""Run the web app with uvicorn.

Env:
  SPRINT_PULSE_HOST   default 127.0.0.1 (set 0.0.0.0 in the container)
  SPRINT_PULSE_PORT   default 8765
  SPRINT_PULSE_DB     SQLite path (default: platform data dir)
"""
from __future__ import annotations

import os

import uvicorn

from sprint_pulse.web.app import create_app


def main() -> None:
    host = os.environ.get("SPRINT_PULSE_HOST", "127.0.0.1")
    port = int(os.environ.get("SPRINT_PULSE_PORT", "8765"))
    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
