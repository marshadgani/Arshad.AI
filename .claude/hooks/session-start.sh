#!/usr/bin/env bash
# session-start.sh — runs async at session start; triggers weekly skill update
# Wired in .claude/settings.json as the "session-start" hook.
# Execution: async/background — zero delay to your first prompt.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TIMESTAMP_FILE="$REPO_ROOT/.claude/skills/.last-updated"
UPDATE_SCRIPT="$REPO_ROOT/scripts/update-skills.sh"
SEVEN_DAYS=604800   # seconds in 7 days

# ── Check if update is due ─────────────────────────────────────────────────────
if [ -f "$TIMESTAMP_FILE" ]; then
  LAST_UPDATED=$(cat "$TIMESTAMP_FILE")
  NOW=$(date +%s)
  ELAPSED=$(( NOW - LAST_UPDATED ))

  if [ "$ELAPSED" -lt "$SEVEN_DAYS" ]; then
    DAYS_REMAINING=$(( (SEVEN_DAYS - ELAPSED) / 86400 ))
    echo "[session-start] Skills are current — next update in ~${DAYS_REMAINING} day(s)"
    exit 0
  fi

  echo "[session-start] Skills last updated $(( ELAPSED / 86400 )) days ago — running update in background..."
else
  echo "[session-start] No skill timestamp found — running initial update in background..."
fi

# ── Run update async — does not block session ──────────────────────────────────
if [ ! -f "$UPDATE_SCRIPT" ]; then
  echo "[session-start] ERROR: update script not found at $UPDATE_SCRIPT"
  exit 0
fi

bash "$UPDATE_SCRIPT" >> "$REPO_ROOT/.claude/skills/.update-log" 2>&1 &
echo "[session-start] Skill update started in background (PID $!) — check .claude/skills/.update-log for progress"
