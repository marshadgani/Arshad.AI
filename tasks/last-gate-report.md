# Arshad.AI Quality Gate Report

**Branch:** `obsidian-vault-render` -> `claude/ai-personal-assistant-main`
**Feature:** FEAT-166, Obsidian vault export (Slice 2). Renders public-visibility ontology entities and relationships as markdown notes and pushes them to `marshadgani/obsidian-vault`.
**Date:** 2026-10-05

## Gate Summary

| # | Agent | Result |
|---|---|---|
| 1 | code-reviewer | WARN, 0 Critical. Findings fixed (see below) |
| 2 | security-auditor | PASS on all core invariants. 4 minor findings: 2 fixed, 1 documented, 1 deferred |
| 3 | debugger | WARN, 0 crash-level bugs. Robustness items logged |
| 4 | test-writer | Reported FAIL on `obsidian_vault_repository.py`. HALLUCINATED -> manual: PASS. The agent ran without a database so the 2 query-layer tests errored. With a real Postgres they pass |
| 5 | refactorer | WARN, 0 Critical |
| 6 | doc-writer | WARN. Docstrings added to public functions, typo fixed |
| 7 | silent-failure-hunter | WARN. Empty-set wipe guarded; other items logged |
| 8 | pr-test-analyzer | WARN. Prune path covered only by fakes (logged) |

## Verdict: WARN, mergeable

**GATE PASSED WITH WARNINGS**

Manual verification: 131/131 vault tests pass against real Postgres 16, including the public-only query filter and tenant isolation. Full backend suite: 811 pass, 8 fail. The same 8 fail on the old dependency pins, so they predate this change (event-loop and env issues in auth and token tests).

**Diff scope note:** the squash-divergence merge briefly reverted some of main's newer vendored skill files (weekly-sync noise). They were restored from main, so this PR's diff is FEAT-166 code, tests, config and task files only (21 files).

## Fixed in this PR (from gate findings)

- Empty public set no longer wipes the vault. Export refuses unless the trigger payload sets `allow_empty_prune`.
- Case-insensitive filename collisions (`Foo` vs `foo`) get a stable hash suffix. Slash/dash collisions do too.
- Keys that sanitize to empty (non-ASCII) fall back to a hash filename instead of aborting the export.
- Frontmatter uses `ensure_ascii=True` so Unicode line separators cannot survive.
- Relationships carry a `visibility` field and the renderer refuses any non-public one.
- Git subprocess env forwards proxy and CA variables.
- `pyjwt` 2.13.0 -> 2.15.1 (SEC-001 from the pipeline's Security Auditor). `cryptography` stays at 49.0.0 (major bump left for its own change).
- Docstrings added; docstring typo fixed.

## Known limitations (documented)

- Git history keeps earlier versions of notes for entities later made private. Pruning removes only the tip, so the vault repo must stay private. Documented in `push_vault`.
- Hand-written notes under `People/` and `Projects/` in the vault repo are managed by the export and will be deleted if not generated.

## Follow-ups (non-blocking)

- [ ] Real bare-repo test for the prune path (pr-test-analyzer, rated 8)
- [ ] Mock-free unit test of repository SQL so coverage does not depend on `TEST_DATABASE_URL`
- [ ] Report skipped entity types and dropped edges in the export summary, not only in logs
- [ ] Cancellation: check the 900s deadline before the 60s retry sleep
- [ ] Optional: `core.quotePath=false` for pruning non-ASCII paths; push to an explicit `main` ref
- [ ] Operator action: create the fine-grained PAT (repo `marshadgani/obsidian-vault`, contents read+write) and set `OBSIDIAN_VAULT_REPO_TOKEN` in Render
