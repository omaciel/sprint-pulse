.PHONY: help install install-dev test test-update lint check hooks migrate db-path dev dev-desktop \
        demo demo-desktop build-desktop container-build container-run clean

# Use the project venv automatically if it exists; else fall back to python3.
# Override explicitly with `make <target> PYTHON=/path/to/python`.
PYTHON ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
PORT ?= 8765
IMAGE ?= sprint-pulse
DEMO_DB ?= $(CURDIR)/.demo.db

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install:  ## Install runtime dependencies (incl. desktop)
	uv sync --extra desktop --no-default-groups

install-dev:  ## Install runtime + desktop + dev dependencies (pytest, httpx, pyinstaller, ruff)
	uv sync --extra desktop

test:  ## Run the test suite
	$(PYTHON) -m pytest -v

test-update:  ## Run tests and refresh HTML snapshot fixtures
	$(PYTHON) -m pytest -v --snapshot-update

lint:  ## Lint with ruff
	$(PYTHON) -m ruff check sprint_pulse tests

check:  ## Run the full CI gate locally (lint + tests)
	$(MAKE) lint
	$(MAKE) test

hooks:  ## Install git hooks (pre-push runs 'make check' before every push)
	git config core.hooksPath .githooks
	@echo "Installed: pre-push now runs 'make check' (ruff + pytest) before each push."

migrate:  ## One-time import of data/*.yaml into the SQLite DB
	$(PYTHON) migrate_yaml_to_sqlite.py

db-path:  ## Print the resolved SQLite database path
	@$(PYTHON) -c "from sprint_pulse.db.engine import default_db_path; print(default_db_path())"

dev:  ## Run the web app with autoreload (browser at localhost:$(PORT))
	$(PYTHON) -m uvicorn --factory sprint_pulse.web.app:create_app --reload --port $(PORT)

# Self-contained demo: throwaway DB, example YAML as the seed source, and a
# MOCKED Jira (no live instance / credentials). Import sprints manually
# (Import from YAML) or automatically (Import from Jira) — both work offline.
DEMO_ENV = SPRINT_PULSE_DB=$(DEMO_DB) SPRINT_PULSE_DEMO=1 SPRINT_PULSE_SEED_DIR=$(CURDIR)/examples

demo:  ## Run a browser demo with example data + mocked Jira (fresh DB)
	rm -f $(DEMO_DB)
	$(DEMO_ENV) $(PYTHON) -m uvicorn --factory sprint_pulse.web.app:create_app --port $(PORT)

demo-desktop:  ## Same demo, in the native desktop window
	rm -f $(DEMO_DB)
	$(DEMO_ENV) $(PYTHON) -m sprint_pulse.desktop

dev-desktop:  ## Launch the native desktop window (pywebview)
	$(PYTHON) -m sprint_pulse.desktop

build-desktop:  ## Build the desktop app bundle with PyInstaller
	$(PYTHON) -m PyInstaller packaging/sprint_pulse.spec --noconfirm

container-build:  ## Build the container image
	podman build -t $(IMAGE) -f Containerfile .

container-run:  ## Run the container (browser at localhost:$(PORT))
	podman run --rm -p $(PORT):8765 -v sprint-pulse-data:/data \
		-e JIRA_USERNAME="$$JIRA_USERNAME" -e JIRA_API_TOKEN="$$JIRA_API_TOKEN" $(IMAGE)

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache build dist .demo.db
	find . -type d -name __pycache__ -exec rm -rf {} +
