#!/usr/bin/env bash
# update-skills.sh — pulls latest skill files from upstream GitHub repos
# Runs weekly via .claude/hooks/session-start.sh (async, background)
# To add a new skill source: add one entry to SKILL_SOURCES and SKILL_PATHS below.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/.claude/skills"
TMP_DIR="$(mktemp -d)"
TIMESTAMP_FILE="$SKILLS_DIR/.last-updated"
LOG_FILE="$SKILLS_DIR/.update-log"
CHANGED=0

cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# ── Skill Sources ──────────────────────────────────────────────────────────────
# Format: ["slug"]="git-url"
# The slug becomes the folder name under .claude/skills/
declare -A SKILL_SOURCES=(
  ["superpowers"]="https://github.com/obra/superpowers.git"
  ["ui-ux-pro-max"]="https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git"
  ["claude-mem"]="https://github.com/thedotmack/claude-mem.git"
)

# ── Skill Paths within each repo ───────────────────────────────────────────────
# Where inside the cloned repo the skill files live (relative to repo root)
declare -A SKILL_PATHS=(
  ["superpowers"]="skills"
  ["ui-ux-pro-max"]=".claude/skills"
  ["claude-mem"]="plugin/skills"
)

# ── Extra files to copy per source (space-separated, relative to repo root) ───
declare -A SKILL_EXTRAS=(
  ["superpowers"]=""
  ["ui-ux-pro-max"]=""
  ["claude-mem"]=".agent/rules/claude-mem-context.md"
)

log "=== Arshad.AI skill update starting ==="

for slug in "${!SKILL_SOURCES[@]}"; do
  url="${SKILL_SOURCES[$slug]}"
  skill_path="${SKILL_PATHS[$slug]}"
  extras="${SKILL_EXTRAS[$slug]}"
  clone_dir="$TMP_DIR/$slug"
  dest_dir="$SKILLS_DIR/$slug"

  log "Fetching $slug from $url ..."

  if ! git clone --depth=1 --quiet "$url" "$clone_dir" 2>>"$LOG_FILE"; then
    log "  ERROR: failed to clone $url — skipping $slug"
    continue
  fi

  src_dir="$clone_dir/$skill_path"
  if [ ! -d "$src_dir" ]; then
    log "  ERROR: expected skill path '$skill_path' not found in repo — skipping $slug"
    continue
  fi

  # Diff new vs current to detect changes
  if [ -d "$dest_dir" ]; then
    if diff -rq --exclude='.git' "$src_dir" "$dest_dir" >/dev/null 2>&1; then
      log "  $slug: no changes"
    else
      log "  $slug: changes detected — updating"
      rm -rf "$dest_dir"
      cp -r "$src_dir" "$dest_dir"
      CHANGED=1
    fi
  else
    log "  $slug: new source — installing"
    cp -r "$src_dir" "$dest_dir"
    CHANGED=1
  fi

  # Copy any extra files
  if [ -n "$extras" ]; then
    for extra in $extras; do
      src_extra="$clone_dir/$extra"
      dest_extra="$dest_dir/$(basename "$extra")"
      if [ -f "$src_extra" ]; then
        if ! diff -q "$src_extra" "$dest_extra" >/dev/null 2>&1; then
          cp "$src_extra" "$dest_extra"
          CHANGED=1
          log "  $slug: updated extra file $(basename "$extra")"
        fi
      fi
    done
  fi

  log "  $slug: done"
done

# ── Update timestamp ───────────────────────────────────────────────────────────
date +%s > "$TIMESTAMP_FILE"

# ── Commit if anything changed ─────────────────────────────────────────────────
if [ "$CHANGED" -eq 1 ]; then
  cd "$REPO_ROOT"
  git add .claude/skills/
  git diff --cached --quiet && log "Nothing to commit" || {
    git commit -m "chore: weekly skill update from upstream repos [$(date '+%Y-%m-%d')]

Sources updated:
$(for slug in "${!SKILL_SOURCES[@]}"; do echo "  - $slug: ${SKILL_SOURCES[$slug]}"; done)

https://claude.ai/code/session_016jYZijtrG5nE8T5HdiSP3A"
    git push -u origin "$(git branch --show-current)"
    log "Committed and pushed skill updates"
  }
else
  log "All skills up to date — no commit needed"
fi

log "=== Skill update complete ==="
