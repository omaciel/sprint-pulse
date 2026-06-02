"""Jira API token storage — never in the database.

Two backends behind one interface, chosen by ``Settings.token_ref``:

  - "keyring": OS secret store (macOS Keychain / Linux libsecret). Desktop.
  - "env":     read JIRA_API_TOKEN (or the file named by JIRA_API_TOKEN_FILE).
               Container / headless.

The DB only ever holds the *reference* ("keyring" | "env"), never the secret.
``detect_backend()`` picks a sensible default for the current environment.
"""
from __future__ import annotations

import os
from pathlib import Path

KEYRING_SERVICE = "sprint-pulse"


def detect_backend() -> str:
    """Pick "env" when headless/container, else "keyring" if usable."""
    if os.environ.get("SPRINT_PULSE_HEADLESS") == "1":
        return "env"
    if os.environ.get("JIRA_API_TOKEN") or os.environ.get("JIRA_API_TOKEN_FILE"):
        return "env"
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring

        if isinstance(keyring.get_keyring(), FailKeyring):
            return "env"
        return "keyring"
    except Exception:
        return "env"


def _env_token() -> str | None:
    token = os.environ.get("JIRA_API_TOKEN")
    if token:
        return token
    file_ref = os.environ.get("JIRA_API_TOKEN_FILE")
    if file_ref:
        p = Path(file_ref)
        if p.exists():
            return p.read_text().strip()
    return None


def get_token(token_ref: str, username: str) -> str | None:
    """Resolve the token for the given backend reference."""
    if token_ref == "keyring":
        try:
            import keyring

            return keyring.get_password(KEYRING_SERVICE, username)
        except Exception:
            return None
    return _env_token()


def set_token(token_ref: str, username: str, token: str) -> None:
    """Persist the token in the named backend.

    The "env" backend is read-only (the operator provides the env var), so
    storing there is a no-op — the value already lives in the environment.
    """
    if token_ref == "keyring":
        import keyring

        keyring.set_password(KEYRING_SERVICE, username, token)
    # env backend: nothing to write.


def delete_token(token_ref: str, username: str) -> None:
    if token_ref == "keyring":
        try:
            import keyring

            keyring.delete_password(KEYRING_SERVICE, username)
        except Exception:
            pass
