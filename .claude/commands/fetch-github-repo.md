# /fetch-github-repo

Fetch and integrate an external GitHub repository into Arshad.AI. Extracts all
skills, agents, commands, hooks, and token-optimisation techniques, integrates
them into the codebase, updates the repo registry, and commits automatically.

## Usage
```
/fetch-github-repo <github-url>
```

## Auto-Trigger Rule
**This command runs automatically** whenever a GitHub URL (github.com/...) appears
in a user prompt. No need to type `/fetch-github-repo` explicitly — just paste the URL.

## What It Does

### 1. Clone
```bash
git clone --depth=1 <github-url>
```

### 2. Catalog (extract all components)
| Component | Detection | Destination |
|---|---|---|
| **Skills** | `SKILL.md` files, `skills/` dirs | `.claude/skills/<slug>/` |
| **Agents** | `agents/*.md`, `.claude/agents/*.md` | `backend/src/agents/<slug>_*.md` |
| **Commands** | `commands/*.md`, `.claude/commands/*.md` | `backend/src/commands/<slug>_*.md` |
| **Hooks** | `hooks/*.sh`, `.claude/hooks/*.sh` | `backend/src/hooks/<slug>_*.sh` |
| **Token optimisation** | Files matching `token.optim`, `prompt.cach`, `context.compress` | Logged in registry |

### 3. Register
Saves the repo URL, fetch timestamp, and all extracted components to:
- `.claude/github-repos.json` — machine-readable registry
- `CLAUDE.md § GitHub Repo Registry` — human-readable permanent memory

### 4. Commit
```
Integrated external repo: <REPO_NAME> on <DATE>
```

### 5. Weekly Re-fetch
Every Monday 00:00 UTC, `session-start.sh` re-fetches ALL repos in the registry
and applies upstream changes automatically. A new commit is created if anything changed.

## Saved Repo Registry

All repos that have been fetched are saved in `.claude/github-repos.json`.
The registry is the source of truth for weekly updates.

To view all saved repos:
```bash
cat .claude/github-repos.json
```

To manually re-fetch all repos:
```bash
./scripts/update-skills.sh      # re-fetches skill sources
# registry repos are re-fetched by session-start.sh weekly
```

To add a repo without running the full fetch:
Edit `.claude/github-repos.json` and add an entry — it will be fetched on next weekly run.

## Dry Run
```bash
./scripts/fetch-github-repo.sh https://github.com/author/repo.git --dry-run
```
Catalogs and logs what would be integrated without writing any files.

## Examples

```
/fetch-github-repo https://github.com/obra/superpowers.git
/fetch-github-repo https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git
/fetch-github-repo https://github.com/thedotmack/claude-mem.git
```
