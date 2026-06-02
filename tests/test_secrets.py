"""Token storage: keyring round-trip, env backend, and DB never holds the token."""
import keyring
import pytest
from keyring.backend import KeyringBackend

from sprint_pulse.db import models as m
from sprint_pulse.db.engine import create_db_and_tables, get_engine, session_scope
from sprint_pulse.services import config_service, secrets


class MemoryKeyring(KeyringBackend):
    """In-memory keyring backend for tests."""

    priority = 1  # type: ignore[assignment]

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture
def memory_keyring():
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


def test_keyring_round_trip(memory_keyring):
    secrets.set_token("keyring", "me@example.com", "s3cr3t")
    assert secrets.get_token("keyring", "me@example.com") == "s3cr3t"


def test_env_backend(monkeypatch):
    monkeypatch.setenv("JIRA_API_TOKEN", "from-env")
    assert secrets.get_token("env", "me@example.com") == "from-env"


def test_env_backend_file(monkeypatch, tmp_path):
    f = tmp_path / "token"
    f.write_text("file-token\n")
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.setenv("JIRA_API_TOKEN_FILE", str(f))
    assert secrets.get_token("env", "me@example.com") == "file-token"


def test_detect_backend_headless(monkeypatch):
    monkeypatch.setenv("SPRINT_PULSE_HEADLESS", "1")
    assert secrets.detect_backend() == "env"


def test_detect_backend_env_token(monkeypatch):
    monkeypatch.delenv("SPRINT_PULSE_HEADLESS", raising=False)
    monkeypatch.setenv("JIRA_API_TOKEN", "x")
    assert secrets.detect_backend() == "env"


def test_token_never_stored_in_db(memory_keyring):
    engine = get_engine(":memory:")
    create_db_and_tables(engine)
    with session_scope(engine) as s:
        config_service.update_settings(
            s, jira_username="me@example.com", token_ref="keyring"
        )
    secrets.set_token("keyring", "me@example.com", "super-secret-token")

    with session_scope(engine) as s:
        settings = s.get(m.Settings, 1)
        dumped = settings.model_dump()
    assert "super-secret-token" not in str(dumped)
    assert dumped["token_ref"] == "keyring"
