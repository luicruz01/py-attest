#!/usr/bin/env sh
# PostToolUse hook: format/lint the Python file that was just edited. Reads the tool payload from stdin.
file=$(jq -r '.tool_input.file_path // empty' 2>/dev/null)
case "$file" in
  *.py) uv run ruff check --fix "$file" >/dev/null 2>&1; uv run ruff format "$file" >/dev/null 2>&1 ;;
esac
exit 0
