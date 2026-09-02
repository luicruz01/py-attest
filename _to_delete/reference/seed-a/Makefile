.PHONY: setup test lint secrets secrets-diff audit gate eval-run eval

.NOTPARALLEL: gate eval-run

PYTHON := $(shell command -v python3.12 2>/dev/null || command -v python3.11 2>/dev/null || command -v python3 2>/dev/null)
VERSION ?= v2
PROMPT ?= $(VERSION)
EVAL_BRANCHES := feature/lessons-pagination feature/score-validation fix/mobile-sync-visibility feature/support-context feature/email-reminders feature/streaks feature/analytics-archive fix/progress-percentage

setup:
	@PYTHON_BIN="$(PYTHON)"; \
	if [ -z "$$PYTHON_BIN" ]; then \
		echo "Error: Python 3.11 or newer is required, but no python3 interpreter was found." >&2; \
		exit 1; \
	fi; \
	if ! "$$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then \
		PYTHON_VERSION=$$("$$PYTHON_BIN" --version 2>&1 || true); \
		echo "Error: Python 3.11 or newer is required (found $$PYTHON_VERSION at $$PYTHON_BIN)." >&2; \
		exit 1; \
	fi; \
	echo "Using $$("$$PYTHON_BIN" --version) at $$PYTHON_BIN"; \
	"$$PYTHON_BIN" -m venv .venv
	.venv/bin/python -m pip install -r requirements.txt

test:
	.venv/bin/python -m pytest --cov=app --cov-report=term-missing

lint:
	.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .

# Install the gitleaks binary on macOS with: brew install gitleaks
secrets:
	gitleaks git --redact --verbose --log-opts=HEAD .

# Local audit uses environment mode (macOS-safe, covers transitive deps); CI audits requirements.txt via the official action.
audit:
	.venv/bin/python -m pip_audit --cache-dir /tmp/student-progress-pip-audit-cache

# The preflight writes the standard BLOCK report on a leak and never invokes the LLM.
secrets-diff:
	@test -n "$(BRANCH)" || (echo "Error: BRANCH is required (for example, make gate BRANCH=feature/streaks)." >&2; exit 2)
	.venv/bin/python tools/quality_gate/review.py --branch "$(BRANCH)" --base "$(or $(BASE),main)" --out "$(or $(OUT),reports/)" --secrets-only

# Usage: make gate BRANCH=feature/streaks (optional: BASE=main OUT=reports/)
gate: lint test secrets-diff
	@test -n "$(BRANCH)" || (echo "Error: BRANCH is required (for example, make gate BRANCH=feature/streaks)." >&2; exit 2)
	.venv/bin/python tools/quality_gate/review.py --branch "$(BRANCH)" --base "$(or $(BASE),main)" --out "$(or $(OUT),reports/)"

eval-run:
	@case "$(VERSION)" in ""|"."|".."|*[!A-Za-z0-9._-]*) echo "Error: VERSION must be a non-empty slug." >&2; exit 2 ;; esac; \
	runs_dir="eval/runs_$(VERSION)"; \
	temp_root=$$(mktemp -d "$${TMPDIR:-/tmp}/student-progress-eval.XXXXXX"); \
	trap 'rm -rf "$$temp_root"' EXIT; \
	mkdir -p "$$runs_dir"; \
	for branch in $(EVAL_BRANCHES); do \
		safe_name=$$(printf '%s' "$$branch" | tr '/' '-'); \
		branch_out="$$temp_root/$$safe_name"; \
		mkdir -p "$$branch_out"; \
		echo "Reviewing $$branch with prompt $(PROMPT)..."; \
		reviewer_exit=0; \
		.venv/bin/python tools/quality_gate/review.py --branch "$$branch" --base main --prompt-version "$(PROMPT)" --out "$$branch_out" || reviewer_exit=$$?; \
		if [ ! -f "$$branch_out/$$safe_name.json" ]; then \
			echo "Error: reviewer produced no JSON artifact for $$branch (exit $$reviewer_exit)." >&2; \
			exit 2; \
		fi; \
		if [ "$$reviewer_exit" -ne 0 ] && [ "$$reviewer_exit" -ne 2 ]; then \
			echo "Error: reviewer failed for $$branch (exit $$reviewer_exit)." >&2; \
			exit "$$reviewer_exit"; \
		fi; \
		target_json="$$runs_dir/$$branch.json"; \
		target_markdown="$$runs_dir/$$branch.md"; \
		mkdir -p "$$(dirname "$$target_json")"; \
		cp "$$branch_out/$$safe_name.json" "$$target_json"; \
		cp "$$branch_out/$$safe_name.md" "$$target_markdown"; \
	done

eval:
	@case "$(VERSION)" in ""|"."|".."|*[!A-Za-z0-9._-]*) echo "Error: VERSION must be a non-empty slug." >&2; exit 2 ;; esac
	@.venv/bin/python tools/quality_gate/eval_metrics.py --runs-dir "eval/runs_$(VERSION)" --label "$(VERSION)" --output "eval/metrics_$(VERSION).md"

.PHONY: hooks
hooks:
	.venv/bin/pre-commit install --install-hooks --hook-type pre-commit --hook-type commit-msg
