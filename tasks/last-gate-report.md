<!-- generated from HEAD=3f4497a at 2026-04-26T16:50:00Z; full 6-agent panel on council_chairman agent; 4 real WARN findings fixed inline -->

# Gate Report — Merge to Main: develop-AION → main (council_chairman agent)

**Branch:** `claude/ai-personal-assistant-develop-AION` → `claude/ai-personal-assistant-main`
**Diff base:** `origin/claude/ai-personal-assistant-main..HEAD` (post Step-0 squash-divergence repair)
**Diff scope (pre-fix):** 3 files / 351 insertions / 1 deletion
**Diff scope (post-fix):** 3 files / 376 insertions / 18 deletions

## ✅ GATE PASSED — Safe to merge

(Auto-pr workflow guard greps for the literal string `GATE PASSED` in this file to authorise the squash-merge.)

## What's in this PR

**New code:**
- `backend/src/agents/ai_core/council_chairman.py` — multi-model LLM panel + chairman synthesis agent (inspired by karpathy/llm-council)
- `backend/src/agents/ai_core/__init__.py` — registry import wiring
- `backend/src/services/chat.py` — `_tool_subset` for `general` intent now exposes the council to the chat layer

**Inline gate fixes (this report's commit):**
- `backend/src/agents/ai_core/council_chairman.py` — 4 WARN findings fixed (see Verified Fixes)
- `CLAUDE.md` §19 — `council-chairman` row added to ai-core agents table

## Agent verdicts

| # | Agent | Status | Real findings | Hallucinated |
|---|---|---|---|---|
| 1 | code-reviewer | RAN | 2 (all-fail synthesis, label boundary) — both **FIXED** | 0 |
| 2 | security-auditor | RAN | 2 design-level (rate limit + model allowlist) — already-deferred from prior gate | 0 critical |
| 3 | debugger | RAN | 1 (label boundary, dup of CR finding) — **FIXED**; 1 CRITICAL hallucinated | 1 (false `AgentError` import claim) |
| 4 | refactorer | RAN | 1 (text-extraction duplicated 3×) — **FIXED** | 0 |
| 5 | test-writer | RAN | 0 | Read a fabricated file with wrong field names; entire output discarded |
| 6 | doc-writer | RAN | 1 (CLAUDE.md §19 missing council-chairman) — **FIXED** | Also read a fabricated file with `consensus`/`dissenting_views` fields that don't exist |

**Net: 4 real WARN findings, all fixed inline. 0 unfixed Critical. 0 unfixed Warning.**

## Cross-check methodology

Every claim verified by `Read`/`grep` against the actual file before accepting. Hallucination rate this run: **multiple agents read entirely fabricated versions of the file** (test-writer and doc-writer described `CouncilInput.panelists`, `_extract_json`, `consensus`, `dissenting_views`, `confidence_score`, `synthesis_style` — none exist in the actual file). Pattern from prior 8 gate runs holds: 75-95% hallucination rate.

## Verified Fixes (4 inline)

### Fix 1 — code-reviewer: All-panelists-fail produces hallucinated synthesis ✅ FIXED

- **File:** `backend/src/agents/ai_core/council_chairman.py:298-303` (new lines)
- **Issue:** If every panelist's `_panelist_call` raised, all `PanelOpinion.error` were set, `_build_anonymised_block` returned `"(no answers — panel failed)"`, and the chairman synthesised a plausible-sounding but evidence-free answer.
- **Fix:** Added a guard right after Stage 1 — `if all(op.error for op in opinions): raise AgentError("all_panelists_failed", ...)`. Surfaces the real failure with a list of per-model errors instead of inventing an answer.

### Fix 2 — code-reviewer + debugger: `_label_for(idx≥26)` produces non-letter ✅ FIXED

- **File:** `backend/src/agents/ai_core/council_chairman.py:107-108` + `CouncilInput.panel_models`
- **Issue:** `chr(ord("A") + idx)` returns `[`, `\`, `]`, etc. for idx ≥ 26. `panel_models` had no upper bound, so a 27-model panel produced invalid labels in the chairman prompt.
- **Fix:**
  1. `_label_for` now falls back to `f"P{idx}"` for idx ≥ 26 (or < 0).
  2. `CouncilInput.panel_models` gained `min_length=1, max_length=10`.
- **Cross-check:** Smoke-tested both — 11-model panel raises `ValidationError`; `_label_for(99) = "P99"`.

### Fix 3 — refactorer: Text-extraction idiom duplicated 3× ✅ FIXED

- **File:** `backend/src/agents/ai_core/council_chairman.py:111-117` (new helper)
- **Issue:** Identical 4-line text-extraction block appeared at lines 122-126, 152-156, and 234-238 — once in each of `_panelist_call`, `_reviewer_call`, `_chairman_call`.
- **Fix:** Extracted `_extract_text(msg: dict[str, Any]) -> str` helper. All three call sites now use it. Net: -10 lines of duplication.

### Fix 4 — doc-writer: CLAUDE.md §19 ai-core table missing council-chairman ✅ FIXED

- **File:** `CLAUDE.md` §19 (line 761, new row)
- **Issue:** §19 ai-core domain table listed only the original 4 agents from the architecture decision (chat-orchestrator, tool-dispatcher, context-manager, response-streamer). The new council-chairman agent was not documented.
- **Fix:** Added a row noting the council is in-process (no agent branch since it post-dates the original 24-agent architecture), and citing both the chat-intent wiring and the REST endpoint.

## Verified-False Findings (Rejected)

| Claim | Reality |
|---|---|
| **debugger CRITICAL-1**: "`AgentError` not imported in `routers.py`; `except AgentError` raises `NameError` at runtime" | Line 43 of `routers.py`: `from .base import AgentError, AgentNotImplemented`. Line 143: `except (AgentError, ToolError) as exc:`. The import IS present. The agent fabricated a critical bug that does not exist. |
| **test-writer**: "`CouncilInput.panelists`, `_extract_json` regex parser, `ReviewResult.rationale`, etc." | The actual file has `CouncilInput.panel_models` (not `panelists`), no `_extract_json` (uses inline `find/rfind/json.loads`), `PanelRanking.rankings` is `list[dict[str, Any]]` (not `list[int]`). The agent read a completely different file from imagination. Output discarded. |
| **doc-writer**: "`CouncilOutput` has `consensus`, `dissenting_views`, `confidence_score`, `synthesis_style`, `models_used`, `token_usage` fields" | Actual `CouncilOutput`: `data: dict[str, Any]` + `summary: CouncilSummary`. None of the cited fields exist. The agent invented a different design. The one real claim (CLAUDE.md §19 table) was kept and fixed. |

## Acknowledged design-level concerns (deferred, not fixed)

### security-auditor: No rate limiting + no model allowlist on a 7-LLM-call endpoint

- **Concern:** The council fires up to 7 Anthropic SDK calls per invocation. An authenticated user spamming `POST /api/v1/agents/ai_core/council_chairman/run` could rack up significant API spend with no global throttle. Additionally, `panel_models` and `chairman_model` accept arbitrary strings — no allowlist of permitted Claude model IDs.
- **Why deferred:** This is a project-wide rate-limiting gap acknowledged in every prior gate report (Phases A/C/D/E/F/B + retroactive PR #13). Not introduced by this PR. Per-agent model allowlist is a related design concern that fits the same backlog.
- **Tracked in:** post-MVP backlog. The single-user MVP does not yet need it; multi-user deployments will.

## Pre-existing gap (unchanged)

**No frontend or backend tests.** Same project-wide deferral as all prior gates. The `test-writer` agent's output was discarded due to file hallucination, but the priority test cases for the council (stage error containment, all-fail guard now exists, JSON parse robustness, schema invariants) are obvious from the file structure.

## Verdict

**GATE PASSED.** 4 real WARN findings fixed inline:

1. All-panelists-fail now raises `AgentError("all_panelists_failed", ...)` instead of synthesising garbage.
2. `_label_for(idx≥26)` falls back to `"P{idx}"`; `panel_models` capped at 10.
3. Text-extraction logic deduplicated into `_extract_text` helper.
4. CLAUDE.md §19 ai-core table updated.

Hallucination rate this run: **2 of 6 agents read entirely fabricated versions of the file** (test-writer + doc-writer). Of the 4 agents that read the actual code, hallucination rate on actionable claims was lower than prior runs (1 false CRITICAL from debugger; everything else either real or known-deferred). The pattern continues: run the panel, cross-check every claim by Read, fix what's real.

Net real bugs found and fixed by this gate run: **4** (label boundary, all-fail guard, code dup, doc table).
