#!/usr/bin/env bash
# Lint the file passed as $1, dispatching by extension.
# Usage: lint-on-save.sh <filepath>
set -euo pipefail

FILE="${1:-}"
if [ -z "$FILE" ]; then
  echo "Usage: lint-on-save.sh <filepath>" >&2
  exit 1
fi

EXT="${FILE##*.}"

case "$EXT" in
  ts|tsx)
    echo "==> lint-on-save: ESLint $FILE"
    (cd frontend && npx eslint --max-warnings 0 "../$FILE") && echo "  ✓ OK" || echo "  ✗ ESLint issues"
    ;;
  py)
    echo "==> lint-on-save: Ruff $FILE"
    ruff check "$FILE" && echo "  ✓ OK" || echo "  ✗ Ruff issues"
    ;;
  sh)
    echo "==> lint-on-save: shellcheck $FILE"
    shellcheck "$FILE" && echo "  ✓ OK" || echo "  ✗ shellcheck issues"
    ;;
  *)
    # Silently skip unsupported types
    ;;
esac
