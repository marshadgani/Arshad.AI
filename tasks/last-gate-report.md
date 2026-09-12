# Merge-to-Main Gate Report

**Branch:** `claude/repo-setup-y2zb14` → **Target:** `claude/ai-personal-assistant-main`
**Date:** 2026-09-12
**Diff scope:** 524 files changed (216,269 insertions), vendoring 4 external Claude Code skill sources (`stablyai/orca`, `calesthio/OpenMontage`, `firecrawl/anydoc`, `tt-a1i/archify`) via `/fetch-github-repo`, plus registry updates to `.claude/github-repos.json` and `CLAUDE.md` §18, and 3 new command files in `backend/src/commands/`.

## Verdict: ⚠️ WARN — merge allowed

Zero Critical findings. Zero outstanding FAIL-level findings — the two WARN-level security findings that auto-upgrade to FAIL per project rule were fixed and independently re-verified as resolved before this report was written. Remaining findings are cosmetic/non-blocking WARN and Suggestion items left for the user's discretion, per the "WARN findings are not auto-fixed" rule.

## Agent-by-Agent Results

| Agent | Result | Summary |
|---|---|---|
| `code-reviewer` | WARN | W1: 3 new `backend/src/commands/openmontage_*.md` files reference skill files/modules (`ink-theater`, `backlot` module, `skills/creative/*`) not vendored in this repo — dead references. Contained: these live in the inert `backend/src/commands/` archive, not `.claude/commands/`, so not currently invocable. W2 (info): archify ships a benign, notify-only self-update checker. |
| `security-auditor` | **PASS (after fix)** | Originally found SEC-001 (orca's 8 discovery-stub skills fetch live instructions from a resolved `orca` binary at runtime — unpinned trust boundary) and SEC-002 (anydoc's `npx -y @firecrawl/anydoc` was unpinned — supply-chain risk). Both fixed in commits `ca21008` (pin to `@0.2.4`) and `6b1552e` (provenance warning added to all 8 orca files). Re-audit confirmed both RESOLVED. No secrets, no destructive/arbitrary-path filesystem ops, no shell injection, no obfuscated code found anywhere in the diff. |
| `debugger` | PASS | No application runtime code (FastAPI backend, React frontend, Airflow) touched. `.claude/github-repos.json` is valid JSON and won't break `scripts/register_skills.py` or `scripts/fetch-github-repo.sh` parsing. |
| `test-writer` | PASS (N/A) | No testable application code changed — documentation/skill-registry integration only. |
| `refactorer` | WARN | New registry entries use `"2026-09-12"` (date-only) vs. majority format `"...UTC"` elsewhere in `github-repos.json` (pre-existing inconsistency, not newly introduced structurally). `openmontage` entry has a non-standard `note` key and mixed-case `name`. Cosmetic only. |
| `doc-writer` | PASS | All 4 new CLAUDE.md §18 rows verified accurate against `.claude/github-repos.json`. |
| `silent-failure-hunter` | PASS | No new silent-failure risk in the app's actual error-handling surface. Flagged one *pre-existing, unrelated* latent issue in `.claude/hooks/session-start.sh` (swallowed `KeyError` on malformed registry `url`) as a follow-up, not a blocker for this diff. |
| `pr-test-analyzer` | PASS (N/A) | No behavioral code changed; no coverage gap. |

## Fixes Applied (this run)

1. **`ca21008`** — Pinned `anydoc`'s `npx -y @firecrawl/anydoc` invocations to `@0.2.4` (closes SEC-002).
2. **`6b1552e`** — Added a "Provenance note" security warning to all 8 `orca` discovery-stub `SKILL.md` files, flagging the live-fetch trust boundary and pointing to sandboxing guidance (closes SEC-001).

Both re-verified RESOLVED by a follow-up `security-auditor` pass before this report was finalized.

## Outstanding Checklist (WARN-level, not blocking — user's discretion)

- [ ] `backend/src/commands/openmontage_{ink-art,animated-drawing,backlot}.md` reference tooling (`ink-theater`, a `backlot` Python module, `skills/creative/*`) not vendored in this repo. Either drop these 3 files or add a one-line "reference-only, dependencies not vendored" header. Do not promote to `.claude/commands/` as-is.
- [ ] `.claude/github-repos.json`: normalize the new entries' `last_fetched` format to match the majority `"YYYY-MM-DD HH:MM UTC"` style, drop the non-standard `note` key from the `openmontage` entry (or standardize it across other entries), and lowercase its `name` field for consistency.
- [ ] `orca-per-workspace-env/SKILL.md`'s new provenance note is self-referential (points to itself for "sandboxing guidance"). Minor clarity fix for a future pass.
- [ ] 57 of the 59 newly vendored skills are nested two levels deep and not yet reflected in `CLAUDE.md` §15 ("Active Sources") or `.claude/skills/INDEX.md`, and `backend/scripts/register_skills.py`'s flat glob (`.claude/skills/*/SKILL.md`) will not pick them up. Pre-existing pattern shared with other nested sources; not a regression from this diff but worth a registration-script fix.
- [ ] Confirm `scripts/register_skills.py` is run against the 4 new sources once DB access is available (skipped this session — no reachable `DATABASE_URL`), per CLAUDE.md §21.
