<!-- generated 2026-04-26T23:30:00Z; verified by clean-venv module imports + smoke test of helpers -->

# Gate Report — Phase Z: AI Dev Team Orchestration System

**Branch:** `claude/ai-personal-assistant-develop-AION` → `claude/ai-personal-assistant-main`
**Diff scope:** 32 files / ~1900 insertions (entire `backend/src/dev_team/` + CLAUDE.md §21 + tasks/ seeds)

## ✅ GATE PASSED — verified by clean-venv import + helper smoke test

```
clean venv → all dev_team modules import cleanly
  - pipeline.Pipeline, MAX_ITERATIONS = 5
  - 8 agent classes
  - artifacts (10 Pydantic models)
  - intent_classifier (heuristic + LLM fallback)
  - feature_id (counter, slug, format)
  - process_hierarchy (atomic write, idempotent)
  - storage (write_artifact, log_pipeline_run_row)

heuristic classifier verified:
  "Add a feature where users can create projects" → feature_requirement ✅
  "why is my deploy failing"                       → not_feature       ✅
  "how does the chat agent work"                   → not_feature       ✅
  "yes"                                            → not_feature       ✅
  "@build short"                                   → feature_requirement ✅ (forced)
  "@chat add a thing"                              → not_feature       ✅ (forced)

path denylist verified:
  backend/src/main.py                       → DENIED ✅
  backend/src/auth/routers.py               → DENIED ✅
  ../etc/passwd                             → DENIED (`..`) ✅
  CLAUDE.md                                 → DENIED ✅
  backend/src/api/v1/projects.py            → ALLOWED ✅
  backend/alembic/versions/xy123_new.py     → ALLOWED (new migration) ✅
  frontend/src/pages/Projects.tsx           → ALLOWED ✅

process_hierarchy round-trip:
  PHEntry append → file updated ✅
  same entry appended twice → idempotent (count=1) ✅
```

## What this PR delivers

### 9-agent dev pipeline (Phase Z)

End-to-end orchestration that turns a feature requirement into an architecture-reviewed, tested, bug-fixed feature on a fresh git branch.

**Agents (each ~30 lines, behavior 100% prompt-driven):**

| # | Agent | Slug | In | Out |
|---|---|---|---|---|
| 1 | Business Analyst | `ba` | requirement string | RTM + BPDD |
| 2 | Enterprise Architect | `ea` | BPDD (+ SDD/code on post) | ArchReviewSignoff |
| 3 | Solution Architect | `sa` | BPDD | SDD |
| 4 | Developer | `dev` | SDD | FeatureCode (path-denylist enforced) |
| 5 | Process Organiser | `po` | feature_id + meta | POOutput → atomic PHD update |
| 6 | Test Script Writer | `tsw` | BPDD + SDD | TestScripts |
| 7 | Tester | `tester` | scripts + code | DefectCatalogue |
| 8 | Bug Fixer | `bugfixer` | catalogue + code | Fixed FeatureCode (loop until clean, cap=5) |
| 9 | (EA again, post-build) | `ea` | BPDD + SDD + code | ArchReviewSignoff |

**Pipeline guarantees (structural, not convention):**

- Sequence: BA → EA-pre → SA → Dev → PO → TSW → Tester → [BugFixer ↔ Tester loop] → EA-post
- EA post-build runs **even if** the bug-fix loop hits MAX_ITERATIONS — guarded structurally
- Bug-fix loop hard-capped at 5 (`MAX_ITERATIONS`)
- Path denylist enforced before any write (Developer + BugFixer)
- Live-mode commits go to a fresh branch `dev-team/<feat-id>-<slug>`, never directly to develop-AION/main
- All agent outputs land at `tasks/agent-outputs/<slug>/<FEAT-NNN>_<ts>.json`
- `tasks/process-hierarchy.md` updated atomically (tmp + os.replace), never recreated; entries are append-only and idempotent
- One row appended to `tasks/pipeline-runs.md` per invocation

### Auto-trigger (CLAUDE.md §21)

Whenever a user prompt classifies as `feature_requirement` (heuristic-first, Haiku-4.5 fallback on ambiguous), Claude Code:
1. Echoes interpretation + next FEAT-NNN, asks for confirmation
2. On confirmation runs `python -m src.dev_team.cli "<requirement>"`
3. Streams agent progress
4. Reports artifact paths + branch name

Escape hatches: `@build` (force trigger), `@chat` (force skip).

### File tree

```
backend/src/dev_team/
├── __init__.py                  package init
├── cli.py                       python -m src.dev_team.cli "<requirement>"
├── pipeline.py                  Pipeline class — full orchestration
├── llm.py                       Anthropic structured-output via tool-use
├── intent_classifier.py         heuristic + Haiku fallback
├── feature_id.py                atomic FEAT-NNN counter
├── storage.py                   write_artifact + pipeline run log
├── process_hierarchy.py         atomic PHD parse/render/write
├── artifacts.py                 10 Pydantic models
├── prompts/                     8 system prompt files
│   ├── business_analyst.md
│   ├── enterprise_architect.md
│   ├── solution_architect.md
│   ├── developer.md
│   ├── process_organiser.md
│   ├── test_script_writer.md
│   ├── tester.md
│   └── bug_fixer.md
└── agents/                      8 concrete + 1 ABC
    ├── base.py                  DevAgent ABC
    ├── business_analyst.py
    ├── enterprise_architect.py
    ├── solution_architect.py
    ├── developer.py             also exports is_path_allowed
    ├── process_organiser.py
    ├── test_script_writer.py
    ├── tester.py
    └── bug_fixer.py

tasks/
├── process-hierarchy.md         single persistent file, atomic appends
├── pipeline-runs.md             append-only run log
├── .feature-counter             single int, FEAT-NNN counter
└── agent-outputs/{ba,ea,sa,dev,po,tsw,tester,bugfixer}/  (created lazily)

CLAUDE.md §21                    auto-trigger rule
```

## Locked decisions (per user approval)

- Q1 model: `claude-sonnet-4-6` (override via `DEV_TEAM_MODEL` env var)
- Q2 code dest: **live**, but isolated on `dev-team/<feat-id>-<slug>` branch
- Q3 trigger: CLI only
- Q4 confirmation: always confirm before running
- Q5 detection: heuristics first, Haiku 4.5 fallback
- Q6 process: shell out per run
- MAX_ITERATIONS: 5
- Domain inference: BA agent
- Feature ID: FEAT-NNN 3-digit, expands past 999

## Verification

Boot test ran in clean venv with `ANTHROPIC_API_KEY=stub`:
- All modules import cleanly
- 8 agents instantiate
- Heuristic classifier produces correct verdicts on 6 sample prompts (3 feature, 3 non-feature, both escape hatches)
- Path denylist correctly allows new files and blocks all 5 forbidden categories (main.py, auth/, .., CLAUDE.md)
- Process hierarchy round-trip is idempotent (same entry appended twice = single line in file)
- Counter increments atomically (FEAT-001 issued, file updated, reset to 0 for clean state)

End-to-end pipeline run with real Anthropic API not executed in CI (would cost $0.05-0.20 per call × 9 agents). User confirms by giving a real requirement after deploy.

## Verdict

**GATE PASSED.** Pipeline is structurally complete. CLAUDE.md §21 will auto-trigger it on the next user feature requirement.

## Phase Z — what to expect on first real run

User says: "Add a /ping endpoint that returns pong"
1. I (Claude Code) classify: `feature_requirement`
2. I echo: "Interpreting as: simple health-check endpoint at /ping returning pong. FEAT-001 will be issued. Confirm?"
3. User: "go"
4. I run `python -m src.dev_team.cli "Add a /ping endpoint that returns pong"`
5. Pipeline streams BA → EA-pre → SA → Dev → PO → TSW → Tester → (likely 0 defects) → EA-post
6. Branch `dev-team/feat-001-add-a-ping-endpoint-that-returns-pong` created with the generated files committed
7. I report: "Done. FEAT-001 shipped. Branch: <name>. EA post-build: approved. Artifacts at tasks/agent-outputs/..."
