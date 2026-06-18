.PHONY: help install install-dev test test-update lint check hooks migrate db-path dev dev-desktop \
        demo demo-desktop build-desktop container-build container-run clean

# Default to the project venv that the dependency stamp (below) keeps synced.
# Override explicitly with `make <target> PYTHON=/path/to/python`.
PYTHON ?= .venv/bin/python
PORT ?= 8765
IMAGE ?= sprint-pulse
DEMO_DB ?= $(CURDIR)/.demo.db

# Browser launcher for the web targets: `open` (macOS) or `xdg-open` (Linux).
# Empty on headless boxes/containers, where opening a browser is skipped.
OPEN ?= $(shell command -v open 2>/dev/null || command -v xdg-open 2>/dev/null)

# Open the dashboard as soon as the server actually accepts connections, polling
# the port (up to ~20s) instead of guessing with a fixed sleep. Backgrounded so
# it never blocks the server; a no-op when no browser launcher is available.
open_browser = @[ -n "$(OPEN)" ] && ( i=0; until $(PYTHON) -c "import socket; socket.create_connection(('127.0.0.1', $(PORT)), 0.25).close()" 2>/dev/null || [ $$i -ge 100 ]; do i=$$((i+1)); sleep 0.2; done; $(OPEN) "http://localhost:$(PORT)" >/dev/null 2>&1 ) &

# Auto-install: targets that need Python deps depend on this stamp, so `.venv`
# is created and synced (runtime + desktop + dev) on demand — no manual install
# step required. Re-syncs whenever pyproject.toml or uv.lock change.
DEPS_STAMP := .venv/.deps-stamp
$(DEPS_STAMP): pyproject.toml uv.lock
	@command -v uv >/dev/null 2>&1 || { echo "uv not found — install it first: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	@echo "→ Installing dependencies (first run may take a moment)…"
	uv sync -q --extra desktop
	@touch $(DEPS_STAMP)

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install:  ## Install runtime dependencies (incl. desktop)
	uv sync --extra desktop --no-default-groups

install-dev:  ## Install runtime + desktop + dev dependencies (pytest, httpx, pyinstaller, ruff)
	uv sync --extra desktop

test: $(DEPS_STAMP)  ## Run the test suite
	$(PYTHON) -m pytest -v

test-update: $(DEPS_STAMP)  ## Run tests and refresh HTML snapshot fixtures
	$(PYTHON) -m pytest -v --snapshot-update

lint: $(DEPS_STAMP)  ## Lint with ruff
	$(PYTHON) -m ruff check sprint_pulse tests

check:  ## Run the full CI gate locally (lint + tests)
	$(MAKE) lint
	$(MAKE) test

hooks:  ## Install git hooks (pre-push runs 'make check' before every push)
	git config core.hooksPath .githooks
	@echo "Installed: pre-push now runs 'make check' (ruff + pytest) before each push."

migrate: $(DEPS_STAMP)  ## One-time import of data/*.yaml into the SQLite DB
	$(PYTHON) migrate_yaml_to_sqlite.py

db-path: $(DEPS_STAMP)  ## Print the resolved SQLite database path
	@$(PYTHON) -c "from sprint_pulse.db.engine import default_db_path; print(default_db_path())"

dev: $(DEPS_STAMP)  ## Run the web app with autoreload (browser at localhost:$(PORT))
	$(open_browser)
	$(PYTHON) -m uvicorn --factory sprint_pulse.web.app:create_app --reload --port $(PORT)

# Self-contained demo: throwaway DB, example YAML as the seed source, and a
# MOCKED Jira (no live instance / credentials). Import sprints manually
# (Import from YAML) or automatically (Import from Jira) — both work offline.
DEMO_ENV = SPRINT_PULSE_DB=$(DEMO_DB) SPRINT_PULSE_DEMO=1 SPRINT_PULSE_SEED_DIR=$(CURDIR)/examples

demo: $(DEPS_STAMP)  ## Run a browser demo with example data + mocked Jira (fresh DB)
	rm -f $(DEMO_DB)
	$(open_browser)
	$(DEMO_ENV) $(PYTHON) -m uvicorn --factory sprint_pulse.web.app:create_app --port $(PORT)

demo-desktop: $(DEPS_STAMP)  ## Same demo, in the native desktop window
	rm -f $(DEMO_DB)
	$(DEMO_ENV) $(PYTHON) -m sprint_pulse.desktop

dev-desktop: $(DEPS_STAMP)  ## Launch the native desktop window (pywebview)
	$(PYTHON) -m sprint_pulse.desktop

build-desktop: $(DEPS_STAMP)  ## Build the desktop app bundle with PyInstaller
	$(PYTHON) -m PyInstaller packaging/sprint_pulse.spec --noconfirm

container-build:  ## Build the container image
	podman build -t $(IMAGE) -f Containerfile .

container-run:  ## Run the container (browser at localhost:$(PORT))
	podman run --rm -p $(PORT):8765 -v sprint-pulse-data:/data \
		-e JIRA_USERNAME="$$JIRA_USERNAME" -e JIRA_API_TOKEN="$$JIRA_API_TOKEN" $(IMAGE)

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache build dist .demo.db
	find . -type d -name __pycache__ -exec rm -rf {} +
