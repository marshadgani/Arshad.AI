#!/usr/bin/env bash
# PreToolUse Bash hook — blocks unambiguously destructive commands.
# Receives the tool call as JSON on stdin; exits 2 (with stderr message)
# to block, exits 0 to allow.
set -euo pipefail

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | python3 -c \
  'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("command",""))' \
  2>/dev/null || true)

# Patterns that have no plausible legitimate use in this repo.
DANGEROUS=(
  'rm[[:space:]]+-rf?[[:space:]]+/[[:space:]]*$'
  'rm[[:space:]]+-rf?[[:space:]]+~[[:space:]]*$'
  'rm[[:space:]]+-rf?[[:space:]]+\$HOME'
  'rm[[:space:]]+-rf?[[:space:]]+/\*'
  'dd[[:space:]]+.*of=/dev/(sd|nvme|disk)'
  'mkfs\.'
  '>[[:space:]]*/dev/(sda|sdb|nvme|disk)'
  'chmod[[:space:]]+-R[[:space:]]+777[[:space:]]+/'
  ':\(\)\s*\{\s*:\|:\&\s*\}\s*;\s*:'
)

for pattern in "${DANGEROUS[@]}"; do
  if echo "$CMD" | grep -qE "$pattern"; then
    echo "bash-guard: BLOCKED — command matches '$pattern'" >&2
    echo "Command: $CMD" >&2
    exit 2
  fi
done

exit 0
