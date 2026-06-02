# Make Sprint Pulse uv-native — design

**Date:** 2026-06-02
**Status:** Approved

## Context

Running `uv sync` in the repo produced a warning — *"No `requires-python` value
found in the workspace. Defaulting to `>=3.13`"* — and a 52-byte `uv.lock` stub
that locked **nothing**. The created `.venv` was empty (`fastapi` not installed).

Root cause: `pyproject.toml` had only a `[tool.pytest.ini_options]` section — no
PEP 621 `[project]` table. Dependencies lived in three `requirements*.txt` files
consumed by plain `pip` (Makefile, Containerfile, CI). `uv sync` had no project
metadata to act on, so it did nothing useful.

The goal: make `pyproject.toml` the single source of truth for dependencies and
make `uv sync` the real entry point everywhere (local, container, CI), while
preserving the existing server / desktop / dev dependency boundary and the
"run from repo root, never pip-installed" execution model.

## Decisions

- **Dependency layout:** core/server set → `[project.dependencies]`; GUI +
  packaging deps → `[project.optional-dependencies] desktop`; test/lint deps →
  PEP 735 `[dependency-groups] dev` (installed by `uv sync` by default).
- **Container:** uv runs inside the image (`uv sync` from `pyproject.toml` +
  `uv.lock`); `requirements-server.txt` is deleted.
- **Python version:** `requires-python = ">=3.13"`; CI and the Containerfile
  base image are bumped to 3.13 to match (local venv is already 3.13.11).
- **Not a package:** `[tool.uv] package = false`. Sprint Pulse runs as
  `python -m sprint_pulse.web` from the repo root and the container COPYs the
  source directory directly — it is never `pip install`ed, so uv installs only
  dependencies and no build backend is required.

## Changes

### 1. `pyproject.toml`
Add `[project]`, `[project.optional-dependencies]`, `[dependency-groups]`, and
`[tool.uv]` alongside the existing pytest config:

```toml
[project]
name = "sprint-pulse"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
  "PyYAML>=6.0", "fastapi>=0.110", "uvicorn[standard]>=0.29",
  "sqlmodel>=0.0.16", "jinja2>=3.1", "python-multipart>=0.0.9",
  "apscheduler>=3.10", "certifi>=2024.0",
]

[project.optional-dependencies]
desktop = ["keyring>=24.0", "pywebview>=5.0", "pyinstaller>=6.0"]

[dependency-groups]
dev = ["pytest>=7.0", "pytest-snapshot>=0.9.0", "httpx>=0.27", "ruff>=0.4"]

[tool.uv]
package = false
```

### 2. Delete `requirements*.txt`
`requirements.txt`, `requirements-server.txt`, `requirements-dev.txt` — their
contents map 1:1 into the groups above and are now redundant.

### 3. `Containerfile`
```dockerfile
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-default-groups   # core deps only
ENV PATH="/app/.venv/bin:$PATH"
COPY sprint_pulse ./sprint_pulse
COPY data ./data
# existing ENV / EXPOSE / VOLUME / CMD unchanged
```

### 4. `Makefile`
- `install`     → `uv sync --extra desktop --no-default-groups` (runtime + desktop, no dev)
- `install-dev` → `uv sync --extra desktop` (everything; dev group is default)

Other targets are unchanged — they invoke `$(PYTHON)` (= `.venv/bin/python`,
the same venv uv manages).

### 5. CI `.github/workflows/test.yml`
Replace `setup-python@v6` + `pip install` with `astral-sh/setup-uv`,
`python-version: "3.13"`, then `uv sync --extra desktop`, `uv run ruff check
sprint_pulse tests`, `uv run pytest -v`.

### 6. `uv.lock` + `README.md`
Regenerate the lockfile (commit it). Update README: bump "Python 3.10+" → 3.13+,
and replace the `pip install -r requirements-dev.txt` setup instructions with
`uv sync --extra desktop`.

## Verification

1. `rm -rf .venv && uv sync --extra desktop` — populates a real venv with no
   `requires-python` warning; `uv.lock` is fully populated.
2. `.venv/bin/python -c "import fastapi, pywebview, keyring"` — deps present.
3. `make test` and `make lint` — pass.
4. `podman build -f Containerfile -t sprint-pulse .` — builds (optional, manual).
