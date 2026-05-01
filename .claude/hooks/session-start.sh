#!/usr/bin/env bash
# session-start.sh — runs async at session start
# 1. Weekly skill update from upstream GitHub repos (update-skills.sh)
# 2. Weekly re-fetch of all repos in .claude/github-repos.json (fetch-github-repo.sh)
# Execution: async/background — zero delay to your first prompt.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TIMESTAMP_FILE="$REPO_ROOT/.claude/skills/.last-updated"
UPDATE_SCRIPT="$REPO_ROOT/scripts/update-skills.sh"
FETCH_SCRIPT="$REPO_ROOT/scripts/fetch-github-repo.sh"
REGISTRY="$REPO_ROOT/.claude/github-repos.json"
LOG="$REPO_ROOT/.claude/skills/.update-log"
SEVEN_DAYS=604800

# ── Surface tasks/handoff.md to Claude (the /session-end half of the cycle) ──
# /session-end overwrites tasks/handoff.md at the end of every session with a
# tight "where we are / what's next / watch out for" snapshot. Printing it
# here folds the snapshot into Claude's session context so the next session
# starts in flow within seconds — the whole point of the pattern.
HANDOFF_FILE="$REPO_ROOT/tasks/handoff.md"
if [ -f "$HANDOFF_FILE" ]; then
  echo "[session-start] reading tasks/handoff.md (run /session-end at session end to refresh):"
  echo "----"
  cat "$HANDOFF_FILE"
  echo "----"
fi

# ── Check if weekly update is due ─────────────────────────────────────────────
if [ -f "$TIMESTAMP_FILE" ]; then
  LAST_UPDATED=$(cat "$TIMESTAMP_FILE")
  NOW=$(date +%s)
  ELAPSED=$(( NOW - LAST_UPDATED ))

  if [ "$ELAPSED" -lt "$SEVEN_DAYS" ]; then
    DAYS_REMAINING=$(( (SEVEN_DAYS - ELAPSED) / 86400 ))
    echo "[session-start] Skills current — next update in ~${DAYS_REMAINING} day(s)"
    exit 0
  fi

  echo "[session-start] Skills last updated $(( ELAPSED / 86400 )) days ago — running weekly update in background..."
else
  echo "[session-start] First run — running initial skill fetch in background..."
fi

# ── Run skill update async ─────────────────────────────────────────────────────
{
  # 1. Update .claude/skills/ from upstream skill repos
  if [ -f "$UPDATE_SCRIPT" ]; then
    echo "[session-start] Running update-skills.sh..." >> "$LOG"
    bash "$UPDATE_SCRIPT" >> "$LOG" 2>&1
  fi

  # 2. Re-fetch all repos registered in .claude/github-repos.json
  if [ -f "$REGISTRY" ] && [ -f "$FETCH_SCRIPT" ]; then
    REPO_URLS=$(python3 -c "
import json
with open('$REGISTRY') as f:
    reg = json.load(f)
for slug, data in reg.get('repos', {}).items():
    print(data['url'])
" 2>/dev/null || true)

    if [ -n "$REPO_URLS" ]; then
      echo "[session-start] Re-fetching $(echo "$REPO_URLS" | wc -l | tr -d ' ') registered repo(s)..." >> "$LOG"
      while IFS= read -r url; do
        [ -z "$url" ] && continue
        echo "[session-start] Re-fetching: $url" >> "$LOG"
        bash "$FETCH_SCRIPT" "$url" >> "$LOG" 2>&1 || echo "[session-start] WARNING: failed to re-fetch $url" >> "$LOG"
      done <<< "$REPO_URLS"
    fi
  fi

  echo "[session-start] Weekly update complete" >> "$LOG"
} &
BG_PID=$!
# Detach from the parent shell's job table so the harness doesn't count
# this as a tracked child process (avoids a phantom "1 agent running"
# indicator while the weekly skill refresh runs).
disown "$BG_PID" 2>/dev/null || true

echo "[session-start] Background update started (PID $BG_PID) — check .claude/skills/.update-log for progress"
