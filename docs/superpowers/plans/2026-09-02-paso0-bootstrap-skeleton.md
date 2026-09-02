# Paso 0 — Package Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `py-attest` package skeleton (build config, CI, pre-commit, a `--version`-only CLI) with zero command implementations, so later work packages (F0.1+) have a green pipeline to build on.

**Architecture:** A single-package hatchling project (`py_attest/`) versioned from git tags via hatch-vcs (fallback `0.0.0`). The only runtime code is `py_attest/__init__.py` (exposes `__version__`) and `py_attest/cli/main.py` (a click group supporting only `--version`). GitHub Actions runs `lint` (ruff check + format --check) and `test` (pytest across 3.11/3.12/3.13) via `uv`. Pre-commit mirrors the lint checks locally plus gitleaks and commitizen.

**Tech Stack:** hatchling + hatch-vcs, uv, click, pytest + pytest-cov, ruff, pre-commit, GitHub Actions.

**Spec:** This plan implements CLAUDE.md's "before touching code" contract, `docs/trd.md` §3 (module layout, toolchain, config) and §4.1 (exit codes — not yet exercised, but the CLI must not preempt them), and `docs/plan-cc.md` §4 "Paso 0". No separate design doc — the user's task message plus these docs fully specify the deliverable; this is a bounded bootstrap, not a new architecture.

## Global Constraints

- Do NOT create `py_attest/review`, `check`, `llm`, `standards`, or `doctor` — those belong to later work packages.
- Do NOT implement any CLI command beyond `--version`.
- Do NOT modify `docs/` or `CLAUDE.md`.
- Do NOT add dependencies beyond: `click`, `pyyaml`, `jsonschema`, `jinja2`, `packaging` (runtime); `copier>=9` (extra `scaffold`), `openai` (extra `openai`), `anthropic` (extra `anthropic`); `pytest`, `pytest-cov`, `ruff` (dev group).
- `requires-python = ">=3.11,<3.14"` (per user decision — capped to the TRD's tested range).
- `[project.authors]` = `{name = "Luis Alberto Cruz", email = "luis@luicruz.com"}` (per user decision).
- Ruff: `line-length = 100`, `target-version = "py311"`, `select = ["E","F","W","I","UP","S","ERA","ARG","T20"]`.
- Coverage: `fail_under = 90` (raised later in F0.2).
- Console script: `attest = py_attest.cli.main:cli`.
- No telemetry, no network calls except the configured LLM provider and git/PyPI/GitHub on explicit user action (not relevant yet — no such calls exist in this WP).
- One work package, one branch: stay on `wp/bootstrap` (current branch). Do not push.

---

### Task 1: Package skeleton (pyproject.toml + py_attest + CLI + smoke test)

**Files:**
- Create: `pyproject.toml`
- Create: `py_attest/__init__.py`
- Create: `py_attest/cli/__init__.py`
- Create: `py_attest/cli/main.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `py_attest.__version__` (str) — read by later CLI/report code for `meta.engine_version` (TRD §4.3).
- Produces: `py_attest.cli.main:cli` (click.Group) — the console-script entry point; F0.1 will attach the six real subcommands to this same group object.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "py-attest"
dynamic = ["version"]
description = "CLI + quality-gate engine for Python repos: deterministic checks first, an LLM reviewer whose verdicts are computed by policy."
readme = "README.md"
license = { file = "LICENSE" }
requires-python = ">=3.11,<3.14"
authors = [
    { name = "Luis Alberto Cruz", email = "luis@luicruz.com" },
]
classifiers = [
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
]
dependencies = [
    "click>=8.1",
    "pyyaml>=6.0",
    "jsonschema>=4.20",
    "jinja2>=3.1",
    "packaging>=24.0",
]

[project.urls]
Homepage = "https://github.com/luicruz01/py-attest"
Repository = "https://github.com/luicruz01/py-attest"
Template = "https://github.com/luicruz01/py-attest-template"

[project.scripts]
attest = "py_attest.cli.main:cli"

[project.optional-dependencies]
scaffold = ["copier>=9"]
openai = ["openai>=1.0"]
anthropic = ["anthropic>=0.34"]
all = ["copier>=9", "openai>=1.0", "anthropic>=0.34"]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "ruff>=0.6",
]

[tool.hatch.version]
source = "vcs"

[tool.hatch.version.raw-options]
fallback_version = "0.0.0"

[tool.hatch.build.targets.wheel]
packages = ["py_attest"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "S", "ERA", "ARG", "T20"]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["S101"]

[tool.pytest.ini_options]
addopts = "--cov=py_attest --cov-report=term-missing --cov-fail-under=90"
testpaths = ["tests"]

[tool.coverage.run]
source = ["py_attest"]

[tool.coverage.report]
fail_under = 90
```

- [ ] **Step 2: Write `py_attest/__init__.py`**

```python
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("py-attest")
except PackageNotFoundError:
    __version__ = "0.0.0"
```

- [ ] **Step 3: Write `py_attest/cli/__init__.py`** (empty file, makes `cli` a package)

- [ ] **Step 4: Write `py_attest/cli/main.py`**

```python
import click

from py_attest import __version__


@click.group()
@click.version_option(__version__, prog_name="attest")
def cli() -> None:
    """attest: CLI + quality-gate engine for Python repos."""
```

- [ ] **Step 5: Write the failing test `tests/test_cli.py`**

```python
from click.testing import CliRunner

from py_attest import __version__
from py_attest.cli.main import cli


def test_version_flag_prints_version_and_exits_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_bare_invocation_shows_help_and_exits_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, [])

    assert result.exit_code == 0
    assert "Usage" in result.output
```

(There is no code yet for this test to fail against in the usual red/green sense — this task creates the module and the test together, since the module *is* the deliverable. Skip the "run to see it fail" step here; go straight to running it green in Step 6.)

- [ ] **Step 6: Sync dependencies and run the test suite**

Run:
```bash
uv sync --all-extras
uv run pytest -q
```
Expected: both tests pass; coverage report shows ≥90% (only `py_attest/__init__.py` and `py_attest/cli/main.py` exist, and both are fully exercised by the two tests).

- [ ] **Step 7: Run ruff**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
```
Expected: both exit 0. If `ruff format --check` fails, run `uv run ruff format .` once and re-check (only for files created in this task).

- [ ] **Step 8: Verify the console script**

Run: `uv run attest --version`
Expected: prints `attest, version 0.0.0` (no git tags exist yet, so hatch-vcs falls back to `0.0.0`).

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml py_attest tests
git commit -m "feat: add package skeleton with --version-only CLI

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `pyproject.toml`'s `dev` dependency group and `all` extra from Task 1 (via `uv sync --all-extras`).

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Sync dependencies
        run: uv sync --all-extras

      - name: ruff check
        run: uv run ruff check .

      - name: ruff format --check
        run: uv run ruff format --check .

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
          python-version: ${{ matrix.python-version }}

      - name: Sync dependencies
        run: uv sync --all-extras

      - name: Run tests
        run: uv run pytest -q
```

- [ ] **Step 2: Validate the YAML parses**

Run:
```bash
uv run python -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yml'))"
```
Expected: exits 0, no output.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint and test workflows across Python 3.11-3.13

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Pre-commit config

**Files:**
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Write `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks

  - repo: https://github.com/commitizen-tools/commitizen
    rev: v3.29.1
    hooks:
      - id: commitizen
        stages: [commit-msg]
```

- [ ] **Step 2: Validate the YAML parses**

Run:
```bash
uv run python -c "import yaml, sys; yaml.safe_load(open('.pre-commit-config.yaml'))"
```
Expected: exits 0, no output.

- [ ] **Step 3: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "chore: add pre-commit config (ruff, gitleaks, commitizen)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Full verification and lockfile commit

**Files:**
- Create: `uv.lock` (generated by `uv sync`, not hand-written)

- [ ] **Step 1: Run the full DONE WHEN command chain**

Run:
```bash
uv sync --all-extras && uv run attest --version && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
```
Expected: every command exits 0; final output shows the version string, `2 passed`, and no ruff violations.

- [ ] **Step 2: Confirm `uv.lock` exists and is tracked**

Run: `git status --short uv.lock`
Expected: shows `uv.lock` as untracked (first sync) or unmodified (later syncs).

- [ ] **Step 3: Commit the lockfile**

```bash
git add uv.lock
git commit -m "chore: commit uv.lock

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Re-run the full DONE WHEN chain one more time from a clean state to confirm nothing regressed**

Run the same command as Step 1. Expected: identical success.

---

## Self-Review Notes

- **Spec coverage:** pyproject (hatchling+hatch-vcs, requires-python, deps, extras, console script, ruff/pytest/coverage config) → Task 1. `py_attest/__init__.py` with `__version__` → Task 1 Step 2. `cli/main.py` with `--version`-only group → Task 1 Step 4. CI matrix + lint/test jobs → Task 2. Pre-commit → Task 3. `uv.lock` committed → Task 4.
- **Zero-tests trap avoided:** `pytest -q` with zero collected tests exits 5, not 0 — the DONE WHEN command requires exit 0, so Task 1 adds two real smoke tests instead of relying on a `--co` collect-only guard.
- **Out of scope, confirmed absent from every task:** `py_attest/review`, `check`, `llm`, `standards`, `doctor`; any command beyond `--version`; any edit to `docs/` or `CLAUDE.md`.
