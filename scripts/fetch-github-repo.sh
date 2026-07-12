#!/usr/bin/env bash
# fetch-github-repo.sh — Clone, catalog, and integrate an external GitHub repo
# Usage: ./scripts/fetch-github-repo.sh <github-url> [--dry-run]
#
# Auto-triggered by session-start.sh weekly for all repos in .claude/github-repos.json
# Also triggered manually when a GitHub URL appears in a user prompt.
set -euo pipefail

REPO_URL="${1:-}"
DRY_RUN="${2:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGISTRY="$REPO_ROOT/.claude/github-repos.json"
LOG="$REPO_ROOT/.claude/skills/.update-log"
FETCH_DATE="$(date '+%Y-%m-%d %H:%M UTC')"
FETCH_DATE_SHORT="$(date '+%Y-%m-%d')"
TMP_DIR="$(mktemp -d)"

cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

# ── Validate input ─────────────────────────────────────────────────────────────
if [ -z "$REPO_URL" ]; then
  echo "Usage: $0 <github-url> [--dry-run]"
  echo "Example: $0 https://github.com/obra/superpowers.git"
  exit 1
fi

# Reject anything that isn't a github.com HTTPS URL. Blocks --upload-pack=...,
# file://, ssh remotes, and other vectors that would let a caller redirect
# `git clone` somewhere unexpected.
if [[ ! "$REPO_URL" =~ ^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(\.git)?/?$ ]]; then
  echo "ERROR: refusing to fetch '$REPO_URL'" >&2
  echo "Only https://github.com/<owner>/<repo>[.git] URLs are accepted." >&2
  exit 1
fi

# Normalise URL — ensure .git suffix
[[ "$REPO_URL" == *.git ]] || REPO_URL="${REPO_URL}.git"
REPO_NAME="$(basename "$REPO_URL" .git)"
REPO_SLUG="$(echo "$REPO_NAME" | tr '[:upper:]' '-' | sed 's/[^a-z0-9-]/-/g')"

log "=== fetch-github-repo: $REPO_URL ==="
[ "$DRY_RUN" = "--dry-run" ] && log "DRY RUN — no files will be written"

# ── Clone ──────────────────────────────────────────────────────────────────────
CLONE_DIR="$TMP_DIR/$REPO_SLUG"
log "Cloning $REPO_URL ..."
if ! git clone --depth=1 --quiet "$REPO_URL" "$CLONE_DIR" 2>>"$LOG"; then
  log "ERROR: failed to clone $REPO_URL"
  exit 1
fi
log "Cloned successfully"

# ── Catalog components ─────────────────────────────────────────────────────────
declare -a FOUND_SKILLS=()
declare -a FOUND_AGENTS=()
declare -a FOUND_COMMANDS=()
declare -a FOUND_HOOKS=()
declare -a FOUND_TOKEN_OPT=()

# Skills: look for SKILL.md files or skills/ directories
while IFS= read -r f; do
  dir="$(dirname "$f")"
  name="$(basename "$dir")"
  FOUND_SKILLS+=("$name")
done < <(find "$CLONE_DIR" -not -path '*/.git/*' -name "SKILL.md" 2>/dev/null || true)

# Also check for skills/ directory at root
[ -d "$CLONE_DIR/skills" ] && {
  for d in "$CLONE_DIR"/skills/*/; do
    name="$(basename "$d")"
    [[ " ${FOUND_SKILLS[*]:-} " == *" $name "* ]] || FOUND_SKILLS+=("$name")
  done
}

# Agents: agent markdown files or agents/ directory
while IFS= read -r f; do
  name="$(basename "$f" .md)"
  FOUND_AGENTS+=("$name")
done < <(find "$CLONE_DIR" -not -path '*/.git/*' \( -path '*/agents/*.md' -o -path '*/.claude/agents/*.md' \) 2>/dev/null || true)

# Commands: command markdown files
while IFS= read -r f; do
  name="$(basename "$f" .md)"
  FOUND_COMMANDS+=("$name")
done < <(find "$CLONE_DIR" -not -path '*/.git/*' \( -path '*/commands/*.md' -o -path '*/.claude/commands/*.md' \) 2>/dev/null || true)

# Hooks: shell scripts in hooks directories
while IFS= read -r f; do
  name="$(basename "$f")"
  FOUND_HOOKS+=("$name")
done < <(find "$CLONE_DIR" -not -path '*/.git/*' \( -path '*/hooks/*.sh' -o -path '*/.claude/hooks/*.sh' \) 2>/dev/null || true)

# Token optimisation: files with relevant keywords
while IFS= read -r f; do
  name="$(basename "$f")"
  FOUND_TOKEN_OPT+=("$name")
done < <(grep -rl --include="*.md" --include="*.py" --include="*.ts" \
  -e "token.optim" -e "prompt.cach" -e "context.compress" \
  "$CLONE_DIR" 2>/dev/null | grep -v '/.git/' | head -10 || true)

log "Catalogued:"
log "  Skills: ${#FOUND_SKILLS[@]} — ${FOUND_SKILLS[*]:-none}"
log "  Agents: ${#FOUND_AGENTS[@]} — ${FOUND_AGENTS[*]:-none}"
log "  Commands: ${#FOUND_COMMANDS[@]} — ${FOUND_COMMANDS[*]:-none}"
log "  Hooks: ${#FOUND_HOOKS[@]} — ${FOUND_HOOKS[*]:-none}"
log "  Token optimisation refs: ${#FOUND_TOKEN_OPT[@]}"

# ── Integrate into .claude/skills/<slug>/ ──────────────────────────────────────
SKILL_DEST="$REPO_ROOT/.claude/skills/$REPO_SLUG"
CHANGED=0

if [ "$DRY_RUN" != "--dry-run" ]; then
  # Find the primary skill source path
  SKILL_SRC=""
  for candidate in "skills" ".claude/skills" "plugin/skills" "src/skills"; do
    [ -d "$CLONE_DIR/$candidate" ] && { SKILL_SRC="$CLONE_DIR/$candidate"; break; }
  done

  if [ -n "$SKILL_SRC" ]; then
    if [ -d "$SKILL_DEST" ]; then
      if ! diff -rq --exclude='.git' "$SKILL_SRC" "$SKILL_DEST" >/dev/null 2>&1; then
        rm -rf "$SKILL_DEST"
        cp -r "$SKILL_SRC" "$SKILL_DEST"
        CHANGED=1
        log "Updated .claude/skills/$REPO_SLUG/"
      else
        log "Skills unchanged — skip copy"
      fi
    else
      cp -r "$SKILL_SRC" "$SKILL_DEST"
      CHANGED=1
      log "Installed .claude/skills/$REPO_SLUG/"
    fi
  elif [ "${#FOUND_SKILLS[@]}" -gt 0 ]; then
    # Flat-layout fallback: SKILL.md files scattered around the repo (e.g. gstack
    # puts each skill at the repo root). Copy every directory containing a SKILL.md
    # into .claude/skills/<repo-slug>/<dir-name>/, and any root-level SKILL.md as
    # .claude/skills/<repo-slug>/SKILL.md. CHANGED is decided by git diff afterwards.
    mkdir -p "$SKILL_DEST"
    flat_copied=0
    while IFS= read -r src_skill_md; do
      src_dir="$(dirname "$src_skill_md")"
      if [ "$src_dir" = "$CLONE_DIR" ]; then
        cp "$src_skill_md" "$SKILL_DEST/SKILL.md"
        flat_copied=$((flat_copied + 1))
        continue
      fi
      name="$(basename "$src_dir")"
      # Skip non-skill directories that happen to contain a SKILL.md by accident
      case "$name" in
        node_modules|dist|build|.git|tests|test) continue ;;
      esac
      dest_dir="$SKILL_DEST/$name"
      rm -rf "$dest_dir"
      cp -r "$src_dir" "$dest_dir"
      flat_copied=$((flat_copied + 1))
    done < <(find "$CLONE_DIR" -not -path '*/.git/*' -name "SKILL.md" 2>/dev/null || true)
    if ! git -C "$REPO_ROOT" diff --quiet -- ".claude/skills/$REPO_SLUG" 2>/dev/null \
        || [ -n "$(git -C "$REPO_ROOT" status --porcelain ".claude/skills/$REPO_SLUG" 2>/dev/null)" ]; then
      CHANGED=1
      log "Installed .claude/skills/$REPO_SLUG/ (flat layout — $flat_copied skills)"
    fi
  fi

  # Prune bloat from any installed skill tree. Removes well-known non-skill
  # subdirectories that pad the repo (test fixtures, build artefacts, vendor)
  # and any single file >5MB. This applies to both structured and flat layouts.
  # gstack's browse skill ships a 28MB Haiku-benchmark JSON under test/ — that
  # was the catalyst for adding this prune step.
  if [ -d "$SKILL_DEST" ]; then
    pruned_dirs=0
    while IFS= read -r d; do
      rm -rf "$d"
      pruned_dirs=$((pruned_dirs + 1))
    done < <(find "$SKILL_DEST" \
        \( -type d -name test -o -type d -name tests \
           -o -type d -name node_modules -o -type d -name dist \
           -o -type d -name build -o -type d -name .git \) \
        -prune -print 2>/dev/null)
    pruned_files=0
    while IFS= read -r f; do
      rm -f "$f"
      pruned_files=$((pruned_files + 1))
    done < <(find "$SKILL_DEST" -type f -size +5M 2>/dev/null)
    if [ "$pruned_dirs" -gt 0 ] || [ "$pruned_files" -gt 0 ]; then
      log "Pruned $pruned_dirs bloat dir(s) and $pruned_files oversize file(s) from .claude/skills/$REPO_SLUG/"
      # Re-evaluate CHANGED so the prune diff gets committed
      if [ -n "$(git -C "$REPO_ROOT" status --porcelain ".claude/skills/$REPO_SLUG" 2>/dev/null)" ]; then
        CHANGED=1
      fi
    fi
  fi

  # Copy agent .md files → backend/src/agents/ (reference copies)
  for f in "${FOUND_AGENTS[@]+"${FOUND_AGENTS[@]}"}"; do
    src_file="$(find "$CLONE_DIR" -not -path '*/.git/*' -name "${f}.md" | head -1)"
    [ -f "$src_file" ] || continue
    dest_file="$REPO_ROOT/backend/src/agents/${REPO_SLUG}_${f}.md"
    if ! diff -q "$src_file" "$dest_file" >/dev/null 2>&1; then
      cp "$src_file" "$dest_file"
      CHANGED=1
      log "Installed backend/src/agents/${REPO_SLUG}_${f}.md"
    fi
  done

  # Copy command .md files → backend/src/commands/
  for f in "${FOUND_COMMANDS[@]+"${FOUND_COMMANDS[@]}"}"; do
    src_file="$(find "$CLONE_DIR" -not -path '*/.git/*' -name "${f}.md" | head -1)"
    [ -f "$src_file" ] || continue
    dest_file="$REPO_ROOT/backend/src/commands/${REPO_SLUG}_${f}.md"
    if ! diff -q "$src_file" "$dest_file" >/dev/null 2>&1; then
      cp "$src_file" "$dest_file"
      CHANGED=1
      log "Installed backend/src/commands/${REPO_SLUG}_${f}.md"
    fi
  done

  # Copy hook .sh files → backend/src/hooks/
  # Files are NOT marked executable: a human review + explicit chmod is required
  # before any external hook can run, mitigating supply-chain RCE risk.
  for f in "${FOUND_HOOKS[@]+"${FOUND_HOOKS[@]}"}"; do
    src_file="$(find "$CLONE_DIR" -not -path '*/.git/*' -name "$f" | head -1)"
    [ -f "$src_file" ] || continue
    dest_file="$REPO_ROOT/backend/src/hooks/${REPO_SLUG}_${f}"
    if ! diff -q "$src_file" "$dest_file" >/dev/null 2>&1; then
      cp "$src_file" "$dest_file"
      chmod 644 "$dest_file"
      CHANGED=1
      log "Installed backend/src/hooks/${REPO_SLUG}_${f} (mode 644 — review and chmod +x manually)"
    fi
  done
fi

# ── Update registry (.claude/github-repos.json) ────────────────────────────────
if [ "$DRY_RUN" != "--dry-run" ]; then
  SKILLS_JSON="$(printf '"%s",' "${FOUND_SKILLS[@]:-}" | sed 's/,$//')"
  AGENTS_JSON="$(printf '"%s",' "${FOUND_AGENTS[@]:-}" | sed 's/,$//')"
  COMMANDS_JSON="$(printf '"%s",' "${FOUND_COMMANDS[@]:-}" | sed 's/,$//')"
  HOOKS_JSON="$(printf '"%s",' "${FOUND_HOOKS[@]:-}" | sed 's/,$//')"

  # Use python to safely update JSON (avoids bash json juggling)
  python3 - <<PYEOF
import json, sys

registry_path = "$REGISTRY"
with open(registry_path) as f:
    reg = json.load(f)

reg["repos"]["$REPO_SLUG"] = {
    "url": "$REPO_URL",
    "name": "$REPO_NAME",
    "last_fetched": "$FETCH_DATE",
    "components": {
        "skills":   [x for x in """${FOUND_SKILLS[*]:-}""".split() if x],
        "agents":   [x for x in """${FOUND_AGENTS[*]:-}""".split() if x],
        "commands": [x for x in """${FOUND_COMMANDS[*]:-}""".split() if x],
        "hooks":    [x for x in """${FOUND_HOOKS[*]:-}""".split() if x],
        "token_optimization": [x for x in """${FOUND_TOKEN_OPT[*]:-}""".split() if x],
    }
}

with open(registry_path, "w") as f:
    json.dump(reg, f, indent=2)
print("Registry updated")
PYEOF
  log "Registry updated: .claude/github-repos.json"
fi

# ── Sync skills to DB (best-effort — non-fatal if DB not reachable) ───────────
if [ "$CHANGED" -eq 1 ] && [ "$DRY_RUN" != "--dry-run" ]; then
  REGISTER_SCRIPT="$REPO_ROOT/backend/scripts/register_skills.py"
  if [ -f "$REGISTER_SCRIPT" ]; then
    log "Syncing skills to DB via register_skills.py..."
    (cd "$REPO_ROOT/backend" && DATABASE_URL="${DATABASE_URL:-}" PYTHONPATH=. python3 "$REGISTER_SCRIPT" 2>&1) \
      && log "Skills DB sync complete" \
      || log "WARNING: skills DB sync failed (non-fatal — skills will sync on next app start)"
  fi
fi

# ── Commit if changed ──────────────────────────────────────────────────────────
if [ "$CHANGED" -eq 1 ] && [ "$DRY_RUN" != "--dry-run" ]; then
  cd "$REPO_ROOT"
  git add .claude/github-repos.json .claude/skills/ backend/src/agents/ backend/src/commands/ backend/src/hooks/ 2>/dev/null || true
  git diff --cached --quiet && log "Nothing new to commit" || {
    git commit -m "Integrated external repo: $REPO_NAME on $FETCH_DATE_SHORT

Source: $REPO_URL
Components:
  Skills: ${FOUND_SKILLS[*]:-none}
  Agents: ${FOUND_AGENTS[*]:-none}
  Commands: ${FOUND_COMMANDS[*]:-none}
  Hooks: ${FOUND_HOOKS[*]:-none}

https://claude.ai/code/session_016jYZijtrG5nE8T5HdiSP3A"
    git push -u origin "$(git branch --show-current)"
    log "Committed and pushed: Integrated external repo: $REPO_NAME"
  }
else
  [ "$DRY_RUN" = "--dry-run" ] && log "DRY RUN complete — no changes written"
  [ "$CHANGED" -eq 0 ] && log "No changes detected — nothing committed"
fi

log "=== fetch-github-repo complete: $REPO_NAME ==="
