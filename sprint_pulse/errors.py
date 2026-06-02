"""Shared validation error for the service + web layers.

Carries an optional ``field`` (for inline form highlighting) and ``suggestion``
(e.g. the Levenshtein "did you mean" for an unknown associate). The web layer
renders these as inline HTMX error fragments.
"""
from __future__ import annotations


class ValidationError(Exception):
    def __init__(self, message: str, *, field: str | None = None, suggestion: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
        self.suggestion = suggestion

    def display(self) -> str:
        return self.message + (self.suggestion or "")
