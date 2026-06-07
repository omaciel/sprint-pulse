"""Fixed color palette + the default event/absence type sets.

Single source of truth shared by the DB seed (services/type_service.seed_default_types),
the renderer, and the YAML loader's validation. Default keys/letters match the
pre-CRUD hard-coded vocabulary so existing Event.kind / MemberDayOff.type values
keep working; colors are the Tableau 10 categorical palette.
"""
from __future__ import annotations

PALETTE = [
    # Tableau 10 (one per default type)
    "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
    # extras for custom types
    "#A0CBE8", "#FFBE7D", "#8CD17D", "#D4A6C8",
]

DEFAULT_EVENT_TYPES = [
    {"key": "tags",   "label": "Git tags due",   "abbreviation": "T", "color": "#4E79A7", "sort_order": 0},
    {"key": "gono",   "label": "Go/No-Go",       "abbreviation": "G", "color": "#F28E2B", "sort_order": 1},
    {"key": "ga",     "label": "Target release", "abbreviation": "R", "color": "#59A14F", "sort_order": 2},
    {"key": "freeze", "label": "Release freeze",  "abbreviation": "F", "color": "#BAB0AC", "sort_order": 3},
    {"key": "test",   "label": "Testathon",      "abbreviation": "X", "color": "#B07AA1", "sort_order": 4},
]

DEFAULT_ABSENCE_TYPES = [
    {"key": "pto",       "label": "PTO",                          "abbreviation": "P", "color": "#E15759", "sort_order": 0},
    {"key": "holiday",   "label": "Regional / National holiday",  "abbreviation": "H", "color": "#76B7B2", "sort_order": 1},
    {"key": "company",   "label": "Company holiday",              "abbreviation": "C", "color": "#9C755F", "sort_order": 2},
    {"key": "partial",   "label": "Partial availability",         "abbreviation": "~", "color": "#EDC948", "sort_order": 3},
    {"key": "tentative", "label": "Tentative",                    "abbreviation": "?", "color": "#FF9DA7", "sort_order": 4},
]

DEFAULT_EVENT_KEYS = {t["key"] for t in DEFAULT_EVENT_TYPES}
DEFAULT_ABSENCE_KEYS = {t["key"] for t in DEFAULT_ABSENCE_TYPES}
