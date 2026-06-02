"""Shared pytest fixtures."""
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def valid_dir() -> Path:
    return FIXTURES / "valid"


@pytest.fixture
def invalid_dir() -> Path:
    return FIXTURES / "invalid"
