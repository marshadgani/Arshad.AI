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
# Each entry is a regex matched against the joined Bash command string.
DANGEROUS=(
  # ── Filesystem destruction ─────────────────────────────────────────
  'rm[[:space:]]+-rf?[[:space:]]+/[[:space:]]*$'              # rm -rf /
  'rm[[:space:]]+-rf?[[:space:]]+~[[:space:]]*$'              # rm -rf ~
  'rm[[:space:]]+-rf?[[:space:]]+\$HOME'                      # rm -rf $HOME
  'rm[[:space:]]+-rf?[[:space:]]+/\*'                         # rm -rf /*
  'find[[:space:]]+/[[:space:]]+.*-delete'                    # find / ... -delete
  'find[[:space:]]+/[a-z]+[[:space:]]+.*-delete'              # find /etc ... -delete

  # ── Block-device wipes ────────────────────────────────────────────
  'dd[[:space:]]+.*of=/dev/(sd|nvme|disk)'                    # dd of=/dev/sda
  'mkfs\.'                                                    # mkfs.* — format anything
  '>[[:space:]]*/dev/(sda|sdb|nvme|disk)'                     # >/dev/sda
  'shred[[:space:]]+-[a-z]*[uz]'                              # shred -u/-z (unrecoverable wipe)

  # ── System-path overwrites ────────────────────────────────────────
  '>[[:space:]]*/etc/'                                        # > /etc/anything
  '>[[:space:]]*/usr/(bin|sbin|lib)'                          # > /usr/bin/anything
  '>[[:space:]]*/boot/'                                       # > /boot/anything

  # ── Permission catastrophes ───────────────────────────────────────
  'chmod[[:space:]]+-R[[:space:]]+777[[:space:]]+/[[:space:]]*$'  # chmod -R 777 /
  'chmod[[:space:]]+-R[[:space:]]+777[[:space:]]+~'           # chmod -R 777 ~
  'chown[[:space:]]+-R[[:space:]]+[^[:space:]]+[[:space:]]+/[[:space:]]*$'  # chown -R x /

  # ── Fork bomb ─────────────────────────────────────────────────────
  ':\(\)\s*\{\s*:\|:\&\s*\}\s*;\s*:'

  # ── Accidental package publication (registry side-effect) ────────
  'npm[[:space:]]+publish'                                    # npm publish
  'yarn[[:space:]]+publish'                                   # yarn publish
  'pnpm[[:space:]]+publish'                                   # pnpm publish
  '(twine[[:space:]]+upload|python[[:space:]]+-m[[:space:]]+twine[[:space:]]+upload)'  # PyPI upload
  'cargo[[:space:]]+publish'                                  # cargo publish
  'gem[[:space:]]+push'                                       # rubygems push

  # ── Force-push to protected branches ─────────────────────────────
  'git[[:space:]]+push[[:space:]]+.*--force([[:space:]]|$).*[[:space:]](main|master)\b'
  'git[[:space:]]+push[[:space:]]+.*-f([[:space:]]|$).*[[:space:]](main|master)\b'

  # ── Credential exfiltration shapes ───────────────────────────────
  'curl[[:space:]]+.*\.env[[:space:]]+'                       # curl uploading .env
  'cat[[:space:]]+\.env[[:space:]]*\|[[:space:]]*(curl|nc|wget)'  # cat .env | curl|nc|wget
)

# Strip heredoc bodies + quoted-string content from $CMD before matching.
# Without this, a commit message that QUOTES a dangerous pattern in a
# heredoc trips the guard even though no dangerous command runs. The
# helper script (.claude/hooks/_sanitize_bash.py) handles both heredocs
# and ' '/" " quoted argument bodies. Falls back to raw $CMD if the
# helper is missing or python3 is unavailable — fail-closed on the
# dangerous-pattern check, fail-open on the sanitizer.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SANITIZED=$(printf '%s' "$CMD" | python3 "$SCRIPT_DIR/_sanitize_bash.py" 2>/dev/null) \
  || SANITIZED="$CMD"

for pattern in "${DANGEROUS[@]}"; do
  if echo "$SANITIZED" | grep -qE "$pattern"; then
    echo "bash-guard: BLOCKED — command matches '$pattern'" >&2
    echo "Command: $CMD" >&2
    exit 2
  fi
done

exit 0
