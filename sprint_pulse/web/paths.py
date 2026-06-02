"""Resolve bundled resources (templates/static) in both source and frozen runs.

Under PyInstaller, data files live under ``sys._MEIPASS``; in a normal checkout
they sit next to this file.
"""
from __future__ import annotations

import sys
from pathlib import Path


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    # When frozen, datas are added under "sprint_pulse/web/...".
    if hasattr(sys, "_MEIPASS"):
        return base / "sprint_pulse" / "web" / Path(*parts)
    return base / Path(*parts)


TEMPLATES_DIR = resource_path("templates")
STATIC_DIR = resource_path("static")
