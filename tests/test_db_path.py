"""default_db_path resolution.

Explicit env wins (SPRINT_PULSE_DB, then XDG_DATA_HOME). Otherwise search the
XDG-default location then platform-native, using whichever exists; create at the
XDG-default if neither does.
"""
from pathlib import Path

import pytest

from sprint_pulse.db import engine


@pytest.fixture
def fake_home(monkeypatch, tmp_path):
    monkeypatch.delenv("SPRINT_PULSE_DB", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(engine.Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def _xdg(home):
    return home / ".local" / "share" / "sprint-pulse" / "sprint-pulse.db"


def _native_mac(home):
    return home / "Library" / "Application Support" / "sprint-pulse" / "sprint-pulse.db"


# --- explicit env wins ------------------------------------------------------

def test_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("SPRINT_PULSE_DB", "/tmp/explicit.db")
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg")
    assert engine.default_db_path() == Path("/tmp/explicit.db")


def test_explicit_xdg_wins(monkeypatch):
    monkeypatch.delenv("SPRINT_PULSE_DB", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg")
    monkeypatch.setattr(engine.sys, "platform", "darwin")
    assert engine.default_db_path() == Path("/tmp/xdg/sprint-pulse/sprint-pulse.db")


# --- search when neither env is set -----------------------------------------

def test_search_prefers_existing_xdg(fake_home, monkeypatch):
    monkeypatch.setattr(engine.sys, "platform", "darwin")
    p = _xdg(fake_home)
    p.parent.mkdir(parents=True)
    p.touch()
    assert engine.default_db_path() == p


def test_search_falls_back_to_existing_native(fake_home, monkeypatch):
    monkeypatch.setattr(engine.sys, "platform", "darwin")
    native = _native_mac(fake_home)
    native.parent.mkdir(parents=True)
    native.touch()  # only the native DB exists (e.g. older install)
    assert engine.default_db_path() == native


def test_search_xdg_wins_when_both_exist(fake_home, monkeypatch):
    monkeypatch.setattr(engine.sys, "platform", "darwin")
    for p in (_xdg(fake_home), _native_mac(fake_home)):
        p.parent.mkdir(parents=True)
        p.touch()
    assert engine.default_db_path() == _xdg(fake_home)


def test_search_none_exist_creates_at_xdg_default(fake_home, monkeypatch):
    monkeypatch.setattr(engine.sys, "platform", "darwin")
    # nothing on disk → create target is the XDG default, even on macOS
    assert engine.default_db_path() == _xdg(fake_home)


def test_symlinked_db_is_found(fake_home, monkeypatch):
    monkeypatch.setattr(engine.sys, "platform", "darwin")
    real = fake_home / "dotfiles" / "sprint-pulse.db"
    real.parent.mkdir(parents=True)
    real.touch()
    link = _xdg(fake_home)
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    assert engine.default_db_path() == link  # exists() follows the symlink
