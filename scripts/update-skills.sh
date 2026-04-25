#!/usr/bin/env bash
# update-skills.sh — weekly sync of skills, agents, and commands from upstream GitHub repos
# Triggered by .claude/hooks/session-start.sh every 7 days (async, background)
# To add a new source: add one entry to SKILL_SOURCES, AGENT_SOURCES, or COMMAND_SOURCES below.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/.claude/skills"
AGENTS_DIR="$REPO_ROOT/.claude/agents"
COMMANDS_DIR="$REPO_ROOT/.claude/commands"
TMP_DIR="$(mktemp -d)"
TIMESTAMP_FILE="$SKILLS_DIR/.last-updated"
LOG_FILE="$SKILLS_DIR/.update-log"
CHANGED=0

cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# ── Skill Sources (SKILL.md-based repos) ──────────────────────────────────────
# Format: ["slug"]="git-url"   |  SKILL_PATHS: where skills/ lives in the repo
declare -A SKILL_SOURCES=(
  ["superpowers"]="https://github.com/obra/superpowers.git"
  ["ui-ux-pro-max"]="https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git"
  ["claude-mem"]="https://github.com/thedotmack/claude-mem.git"
  ["obsidian-skills"]="https://github.com/kepano/obsidian-skills.git"
  ["context7"]="https://github.com/upstash/context7.git"
  ["everything-claude-code"]="https://github.com/affaan-m/everything-claude-code.git"
)
declare -A SKILL_PATHS=(
  ["superpowers"]="skills"
  ["ui-ux-pro-max"]=".claude/skills"
  ["claude-mem"]="plugin/skills"
  ["obsidian-skills"]="skills"
  ["context7"]="skills"
  ["everything-claude-code"]=".agents/skills"
)
# Extra files to copy per skill source (space-separated, relative to repo root)
declare -A SKILL_EXTRAS=(
  ["superpowers"]=""
  ["ui-ux-pro-max"]=""
  ["claude-mem"]=".agent/rules/claude-mem-context.md"
  ["obsidian-skills"]=""
  ["context7"]=""
  ["everything-claude-code"]=""
)

# ── Agent Sources (agent .md file repos) ──────────────────────────────────────
# Agents go into .claude/agents/<slug>/ (namespaced to avoid conflicts)
declare -A AGENT_SOURCES=(
  ["n8n-mcp"]="https://github.com/czlonkowski/n8n-mcp.git"
  ["get-shit-done"]="https://github.com/gsd-build/get-shit-done.git"
  ["context7"]="https://github.com/upstash/context7.git"
)
declare -A AGENT_PATHS=(
  ["n8n-mcp"]=".claude/agents"
  ["get-shit-done"]="agents"
  ["context7"]="plugins/claude/context7/agents"
)

# ── Command Sources (slash command .md repos) ──────────────────────────────────
# Commands are merged directly into .claude/commands/ (prefixed with slug_)
declare -A COMMAND_SOURCES=(
  ["awesome-claude-code"]="https://github.com/hesreallyhim/awesome-claude-code.git"
  ["context7"]="https://github.com/upstash/context7.git"
)
declare -A COMMAND_PATHS=(
  ["awesome-claude-code"]=".claude/commands"
  ["context7"]="plugins/claude/context7/commands"
)

# ── Helper: sync a directory ───────────────────────────────────────────────────
sync_dir() {
  local src="$1" dest="$2" label="$3"
  if [ ! -d "$src" ]; then
    log "  WARN: $label source path not found — skipping"
    return 0
  fi
  if [ -d "$dest" ]; then
    if diff -rq --exclude='.git' "$src" "$dest" >/dev/null 2>&1; then
      log "  $label: no changes"
      return 0
    else
      log "  $label: changes detected — updating"
      rm -rf "$dest"
    fi
  else
    log "  $label: new — installing"
  fi
  cp -r "$src" "$dest"
  CHANGED=1
}

log "=== Arshad.AI weekly update starting ==="
log "Skills: ${!SKILL_SOURCES[*]}"
log "Agents: ${!AGENT_SOURCES[*]}"
log "Commands: ${!COMMAND_SOURCES[*]}"

# ── Update Skills ──────────────────────────────────────────────────────────────
for slug in "${!SKILL_SOURCES[@]}"; do
  url="${SKILL_SOURCES[$slug]}"
  skill_path="${SKILL_PATHS[$slug]}"
  extras="${SKILL_EXTRAS[$slug]:-}"
  clone_dir="$TMP_DIR/skills-$slug"
  dest_dir="$SKILLS_DIR/$slug"

  log "--- Skills: $slug ---"
  if ! git clone --depth=1 --quiet "$url" "$clone_dir" 2>>"$LOG_FILE"; then
    log "  ERROR: failed to clone $url"
    continue
  fi

  sync_dir "$clone_dir/$skill_path" "$dest_dir" "$slug"

  # Copy any extra files
  if [ -n "$extras" ]; then
    for extra in $extras; do
      src_extra="$clone_dir/$extra"
      dest_extra="$dest_dir/$(basename "$extra")"
      if [ -f "$src_extra" ]; then
        if ! diff -q "$src_extra" "$dest_extra" >/dev/null 2>&1; then
          cp "$src_extra" "$dest_extra"
          CHANGED=1
          log "  $slug: updated $(basename "$extra")"
        fi
      fi
    done
  fi
done

# ── Update Agents ──────────────────────────────────────────────────────────────
for slug in "${!AGENT_SOURCES[@]}"; do
  url="${AGENT_SOURCES[$slug]}"
  agent_path="${AGENT_PATHS[$slug]}"
  clone_dir="$TMP_DIR/agents-$slug"
  dest_dir="$AGENTS_DIR/$slug"

  log "--- Agents: $slug ---"
  if ! git clone --depth=1 --quiet "$url" "$clone_dir" 2>>"$LOG_FILE"; then
    log "  ERROR: failed to clone $url"
    continue
  fi

  sync_dir "$clone_dir/$agent_path" "$dest_dir" "$slug agents"
done

# ── Update Commands ────────────────────────────────────────────────────────────
for slug in "${!COMMAND_SOURCES[@]}"; do
  url="${COMMAND_SOURCES[$slug]}"
  cmd_path="${COMMAND_PATHS[$slug]}"
  clone_dir="$TMP_DIR/commands-$slug"
  src_dir="$clone_dir/$cmd_path"

  log "--- Commands: $slug ---"
  if ! git clone --depth=1 --quiet "$url" "$clone_dir" 2>>"$LOG_FILE"; then
    log "  ERROR: failed to clone $url"
    continue
  fi

  if [ ! -d "$src_dir" ]; then
    log "  WARN: $slug command path not found"
    continue
  fi

  # Merge commands with slug prefix to avoid overwriting project commands
  while IFS= read -r f; do
    fname="$(basename "$f")"
    dest_file="$COMMANDS_DIR/${slug}_${fname}"
    if [ ! -f "$dest_file" ] || ! diff -q "$f" "$dest_file" >/dev/null 2>&1; then
      cp "$f" "$dest_file"
      CHANGED=1
      log "  $slug: updated command $fname"
    fi
  done < <(find "$src_dir" -maxdepth 1 -name "*.md" 2>/dev/null || true)
done

# ── Update timestamp ───────────────────────────────────────────────────────────
date +%s > "$TIMESTAMP_FILE"
log "Timestamp updated"

# ── Commit if anything changed ─────────────────────────────────────────────────
if [ "$CHANGED" -eq 1 ]; then
  cd "$REPO_ROOT"
  git add .claude/skills/ .claude/agents/ .claude/commands/ 2>/dev/null || true
  git diff --cached --quiet && log "Nothing to commit" || {
    git commit -m "chore: weekly skill/agent/command update [$(date '+%Y-%m-%d')]

Sources updated:
Skills:   ${!SKILL_SOURCES[*]}
Agents:   ${!AGENT_SOURCES[*]}
Commands: ${!COMMAND_SOURCES[*]}

https://claude.ai/code/session_016jYZijtrG5nE8T5HdiSP3A"
    git push -u origin "$(git branch --show-current)"
    log "Committed and pushed weekly update"
  }
else
  log "All sources up to date — no commit needed"
fi

log "=== Weekly update complete ==="
