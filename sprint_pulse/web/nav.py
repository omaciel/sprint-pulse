"""Shared top app-bar.

The dashboard is a full self-contained page produced by ``render.render_full_html``;
the management pages render through ``base.html``. Both get the same slim bar so
users can move between Dashboard / Sprints / Team / Settings / Schedule.
"""
from __future__ import annotations

NAV_LINKS = [
    ("/", "Dashboard"),
    ("/sprints", "Sprints"),
    ("/members", "Team"),
    ("/config", "Settings"),
    ("/scheduler", "Schedule"),
]


def app_bar_html(active: str = "") -> str:
    links = "".join(
        f'<a href="{href}" class="{"active" if href == active else ""}">{label}</a>'
        for href, label in NAV_LINKS
    )
    return (
        '<div class="app-bar">'
        '<span class="app-bar-brand">⚡ Sprint Pulse</span>'
        f'<nav class="app-bar-links">{links}</nav>'
        "</div>"
    )


APP_BAR_CSS = """
.app-bar { position: sticky; top: 0; z-index: 50; display: flex; align-items: center;
  gap: 24px; padding: 10px 20px; background: #111827; color: #f9fafb;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
.app-bar-brand { font-weight: 700; letter-spacing: .2px; }
.app-bar-links { display: flex; gap: 4px; }
.app-bar-links a { color: #d1d5db; text-decoration: none; padding: 6px 12px;
  border-radius: 6px; font-size: 14px; }
.app-bar-links a:hover { background: #1f2937; color: #fff; }
.app-bar-links a.active { background: #2563eb; color: #fff; }
"""


def inject_app_bar(full_html: str, active: str = "/") -> str:
    """Insert the app-bar (and its CSS) into a render_full_html() document."""
    html = full_html.replace("</head>", f"<style>{APP_BAR_CSS}</style></head>", 1)
    # render.py uses `body { padding: 32px 24px }`; drop the top pad so the bar
    # sits flush, then place the bar as the first body child.
    html = html.replace("<body>", f'<body style="padding-top:0">{app_bar_html(active)}', 1)
    return html
