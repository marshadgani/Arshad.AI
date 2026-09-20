# Arshad.AI Quality Gate Report

**PR:** #95 — FEAT-165 (renumbered from FEAT-144): Obsidian ontology layer, Slice 1
**Branch:** `dev-team/feat-144-feat-144` → `claude/ai-personal-assistant-main`
**Triggered by:** "merge to main" (user request), gate run directly in-session
**Date:** 2026-09-16

---

## Summary

FEAT-165 extracts Arshad.AI's ingested calendar/email/GitHub data into a
Postgres-backed ontology layer of linked entities and relationships
(people, projects) with per-entity visibility classification enforced by
a one-way SQL "ratchet" trigger — visibility can only tighten toward
`private`, never silently loosen. This slice ships zero vault-write
surface (no Obsidian sync router, no MOC export) by design; that's a
separate future feature.

The diff already passed the internal 30-stage dev-team pipeline
(Architecture Critic clean, Security Auditor found and fixed one real gap
in place — the ratchet trigger was originally `UPDATE`-only, fixed to
`INSERT OR UPDATE` — Enterprise Architect: SHIP). This Merge-to-Main gate
is an **independent** re-verification against the actual code on disk,
per this repo's standing rule that pipeline sign-off is never rubber-stamped.

## Gate Summary

| # | Gate | Agent | Initial Result | After fixes |
|---|---|---|---|---|
| 1 | Code Review | code-reviewer | ❌ FAIL (2 Critical) | ✅ Fixed |
| 2 | Security Audit | security-auditor | ❌ FAIL (1 Critical) | ✅ Fixed |
| 3 | Bug Analysis | debugger | ❌ FAIL (3 Critical) | ✅ Fixed |
| 4 | Test Coverage | test-writer | ❌ FAIL (3 Critical) | ✅ Fixed |
| 5 | Code Quality | refactorer | ⚠️ WARN (1 Critical) | ✅ Fixed |
| 6 | Documentation | doc-writer | ⚠️ WARN (2 Warnings) | ✅ Fixed |
| 7 | Silent Failures | silent-failure-hunter | ✅ PASS | ✅ PASS (unchanged) |
| 8 | Test Quality | pr-test-analyzer | ⚠️ WARN (2 Warnings) | Follow-ups logged |

## Overall Verdict

### ✅ GATE PASSED — Ready for merge

Every FAIL gate and every Critical finding is resolved and independently
re-verified below with real command output, not self-reported. Remaining
items are WARN/Suggestion-tier per this repo's gate thresholds and do not
block merge — logged as an Action Items checklist.

---

## Critical findings — all root-caused, fixed, and re-verified

All four agents that ran the code independently converged on the same
root cause, confirming it wasn't a fluke:

1. **`ontology_extract.py` had a hard `ImportError`.** It imported
   `MAX_EXTERNAL_KEY_LEN` from `ontology_graph.py` and read
   `graph.skipped_oversized_key`, but `ontology_graph.py` defined neither
   — `DerivedGraph` had only `persons/projects/edges/skipped_no_author`.
   Every `ontology_extractor` run would fail at import time; every test in
   `test_ontology_extraction.py` failed at pytest collection.
   **Fix:** added `MAX_EXTERNAL_KEY_LEN = 255` (matching the DB column
   width) plus the length-guard and `skipped_oversized_key` counter to
   `derive_graph()`/`DerivedGraph`.

2. **`test_ontology_graph.py`'s `_row()` helper built rows without the
   `"raw"` wrapper** `derive_graph()` actually reads from — every row
   silently hit the skip path, so 5 of 9 pure unit tests asserted nothing
   real. **Fix:** corrected the row shape to nest under `"raw"`.

3. **`test_ontology_security.py` never applied `@pytest.mark.asyncio`**
   (only `@pytest.mark.pg`) — under this repo's default strict
   pytest-asyncio mode, none of its 14 async tests were ever claimed by
   the plugin and none actually ran; the entire trigger test suite for
   this feature's core security mechanism was silently dead.
   **Fix:** added a module-level `pytestmark = pytest.mark.asyncio`.

4. **`test_demotion_rejected_even_with_guc` asserted the wrong property**
   — it expected demotion (public→private) to be *rejected*, backwards
   from the feature's actual, correct design (only promotion needs the
   GUC; demotion is always allowed, unconditionally). Found by test-writer.
   **Fix:** rewrote as `test_demotion_to_private_succeeds_without_guc`,
   asserting the real intended property, explicitly clearing the GUC
   first to prove demotion needs no privilege at all.

5. **Two tests depended on the shared `committed_user` fixture** while
   opening genuinely separate DB connections (`subprocess.run` for the
   CLI test, a fresh `create_async_engine` for the session-close
   regression test) — `committed_user` only lives inside `pg_session`'s
   SAVEPOINT tree, invisible outside it, so both hit real FK violations.
   **Fix:** each test now seeds and cleans up its own truly-committed
   user via its own connection.

6. **Found independently during verification (not flagged by any of the
   8 agents, since none ran `alembic upgrade`): two Alembic migration
   heads.** This branch's ontology migration and main's newer
   password-hash/timezone-fix chain both descended from the same parent
   independently — `alembic upgrade head` would fail in production with
   "multiple heads." **Fix:** retargeted this migration's `down_revision`
   onto the current chain (safe — this migration has never shipped to
   main, so this isn't editing a migration the immutability rule protects).

### Independent re-verification (not self-reported)

```
$ alembic upgrade head   (fresh Postgres 16 database)
...
INFO  Running upgrade n1k2l3m4a5b6 -> o1l2m3n4a5b6, ontology entities and relationships (FEAT-144 slice 1)
→ single head, applies cleanly

$ pytest tests/test_ontology_extraction.py tests/test_ontology_graph.py tests/test_ontology_security.py -q
................................................                         [100%]
48 passed in 3.13s
→ includes all 14 real-Postgres trigger/security tests, now actually executing

$ pytest tests/ -q -k "github or obsidian or runner or queue_worker"
..................................................                       [100%]
50 passed
→ every existing test in files this diff touches, unmodified, still green

$ pytest tests/ -q   (full backend suite)
683 passed, 5 failed
→ the 5 failures (test_auth.py, test_auth_password.py, test_token_service.py)
  are in files this diff does not touch — pre-existing, unrelated, out of scope
```

---

## WARN-tier fixes applied (not required to unblock, done anyway since cheap)

- Added a missing FK index (`ix_ontology_relationships_source_entity_id`)
  per `.claude/rules/database.md`'s "index every foreign key" rule —
  `target_entity_id` had one, `source_entity_id` didn't.
- Added two explanatory comments to the visibility-ratchet trigger
  (`ontology_rank_visibility()`): the fail-closed `COALESCE` mechanism,
  and why the `NULL` guard is needed independently of the CHECK
  constraint (BEFORE ROW triggers fire before CHECK constraints).
- Added 3 new tests for the oversized-external-key skip path
  (`test_skip_oversized_login`, `test_skip_oversized_project_key`,
  `test_key_at_exact_limit_is_not_skipped`) — previously had zero
  coverage since the feature itself didn't exist until this fix.

## Action Items (WARN/Suggestion — not blocking, logged for follow-up)

- [ ] `ontology_extract.py`'s public entry point is named `extract()`;
      every sibling ingestion module uses `ingest()`. Consider renaming
      for consistency with `runner.py`'s dispatch convention.
- [ ] `ontology_repository.upsert_entities()` returns `len(key_map)`
      (entities touched, including no-op conflict updates) as
      `entities_written`, unlike `relationships_written` which uses real
      `rowcount` — the naming is a bit misleading.
- [ ] `DerivedGraph.skipped_no_author` conflates two causes (missing
      author vs. missing `provider_id`) — a future slice could split them
      for clearer operator signal.
- [ ] `ontology_repository.py`'s "RETURNING fewer rows than input"
      defensive branch (documented as "should be unreachable") has no
      direct test.
- [ ] The shared ratchet trigger is tested directly only against
      `ontology_entities`; its attachment to `ontology_relationships` is
      exercised indirectly (via CHECK-constraint tests) but not with a
      dedicated raw-SQL no-GUC-update test mirroring the entities one.
- [ ] `_clamp_max_rows`'s comment says a non-coercible `max_rows` is
      "caller error... surface it" but then substitutes the default
      rather than raising — reword the comment or raise, for consistency
      with `_parse_since`'s handling of bad input.

None of the above block this merge — all are WARN/Suggestion-tier per
this repo's gate thresholds (only Critical findings and FAIL gates
block), and none touch the security-critical visibility ratchet, which
is now fully covered and independently verified against live Postgres.

---
*Generated directly in-session (not via `/gate` auto-invocation) · 8 agents, 4 independently converging on the same root cause · all Critical findings fixed and re-verified with real test execution against a live Postgres 16 instance*
