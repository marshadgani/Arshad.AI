#!/usr/bin/env bash
# PostToolUse hook for Edit/Write — best-effort autoformat the file Claude just touched.
# Exits 0 silently if the formatter is missing or fails; never blocks the tool result.
set -euo pipefail

INPUT=$(cat)
FILE=$(printf '%s' "$INPUT" | python3 -c \
  'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("file_path",""))' \
  2>/dev/null || true)

[ -n "$FILE" ] && [ -f "$FILE" ] || exit 0

REPO_ROOT="$(git -C "$(dirname "$FILE")" rev-parse --show-toplevel 2>/dev/null || pwd)"
REL="${FILE#$REPO_ROOT/}"

case "$FILE" in
  *.py)
    if command -v ruff >/dev/null 2>&1; then
      ruff format "$FILE" >/dev/null 2>&1 || true
      ruff check --fix --quiet "$FILE" >/dev/null 2>&1 || true
    fi
    ;;
  *.ts|*.tsx)
    if [[ "$REL" == frontend/* ]] && [ -d "$REPO_ROOT/frontend/node_modules/.bin" ]; then
      (cd "$REPO_ROOT/frontend" && \
        npx --no-install eslint --fix "../$REL" >/dev/null 2>&1) || true
    fi
    ;;
esac

exit 0
