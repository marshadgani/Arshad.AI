#!/usr/bin/env bash
set -euo pipefail

echo "==> pre-commit: running checks..."

# ── TypeScript type check ──────────────────────────────────────────────────────
if [ -f frontend/package.json ]; then
  echo "  [1/4] TypeScript check..."
  (cd frontend && npx tsc --noEmit) || {
    echo "  ✗ TypeScript errors — commit blocked"
    exit 1
  }
  echo "  ✓ TypeScript OK"
fi

# ── ESLint on staged .ts/.tsx files ───────────────────────────────────────────
STAGED_TS=$(git diff --cached --name-only --diff-filter=ACMR | grep -E '\.(ts|tsx)$' || true)
FRONTEND_TS=$(echo "$STAGED_TS" | grep "^frontend/" | sed 's|^frontend/||' || true)
if [ -n "$FRONTEND_TS" ] && [ -f frontend/package.json ] && (cd frontend && npx eslint --print-config src/index.tsx > /dev/null 2>&1); then
  echo "  [2/4] ESLint staged files..."
  (cd frontend && echo "$FRONTEND_TS" | xargs npx eslint --max-warnings 0) || {
    echo "  ✗ ESLint errors — commit blocked"
    exit 1
  }
  echo "  ✓ ESLint OK"
else
  echo "  [2/4] ESLint — skipping (no config or no staged .ts/.tsx files)"
fi

# ── Ruff on staged .py files (excluding third-party skill files) ──────────────
STAGED_PY=$(git diff --cached --name-only --diff-filter=ACMR | grep -E '\.py$' | grep -v '^\.claude/skills/' || true)
if [ -n "$STAGED_PY" ]; then
  echo "  [3/4] Ruff lint staged files..."
  echo "$STAGED_PY" | xargs ruff check || {
    echo "  ✗ Ruff errors — commit blocked"
    exit 1
  }
  echo "  ✓ Ruff OK"
else
  echo "  [3/4] Ruff — no staged .py files, skipping"
fi

# ── Secret scan on staged diff (excludes third-party .claude/skills/) ─────────
echo "  [4/4] Secret scan..."
SECRETS=$(git diff --cached -- ':!.claude/skills' | grep -iE "^\+.*(api_key|secret_key|password|auth_token)\s*=\s*['\"][^'\"]{8,}['\"]" || true)
if [ -n "$SECRETS" ]; then
  echo "  ✗ Possible secrets detected in diff — commit blocked"
  echo "$SECRETS"
  exit 1
fi
echo "  ✓ No secrets detected"

echo "==> pre-commit: all checks passed ✓"
