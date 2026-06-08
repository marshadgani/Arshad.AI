# Phase Z — AI Dev Team Orchestration System

Building a 9-agent dev pipeline that auto-triggers on feature requirements.

## Locked decisions

- Model: `claude-sonnet-4-6`
- Code destination: **live** — Developer/Bug Fixer write to actual repo, BUT every run creates a fresh `dev-team/FEAT-NNN-<slug>` branch and commits there. User merges manually.
- Path denylist (Developer + BugFixer cannot touch): `backend/src/main.py`, `backend/src/auth/*`, `backend/alembic/*`, `.github/workflows/*`, `render.yaml`, `vercel.json`, `Dockerfile*`, `CLAUDE.md`, `tasks/process-hierarchy.md`, `tasks/last-gate-report.md`, `tasks/lessons.md`
- Trigger: CLI only, auto-invoked by Claude Code per CLAUDE.md §21
- Confirmation gate: always (echo interpretation, wait for one word)
- Detection: heuristics first, Haiku classifier on borderline
- Process model: shell out per run
- Bug-fix max iterations: 5
- Domain inference: BA agent
- Feature ID: `FEAT-NNN` 3-digit, persisted in `tasks/.feature-counter`

## Build order

- [x] `tasks/todo.md` plan checklist (this file)
- [ ] `tasks/process-hierarchy.md` seed (header only)
- [ ] `tasks/pipeline-runs.md` seed (header + table schema)
- [ ] `tasks/.feature-counter` seed (`0`)
- [ ] `backend/src/dev_team/__init__.py`
- [ ] `backend/src/dev_team/artifacts.py` — Pydantic models for every artifact
- [ ] `backend/src/dev_team/feature_id.py` — atomic counter increment
- [ ] `backend/src/dev_team/storage.py` — write_artifact + read_artifact
- [ ] `backend/src/dev_team/process_hierarchy.py` — atomic parse / render / write
- [ ] `backend/src/dev_team/llm.py` — Anthropic structured-output wrapper
- [ ] `backend/src/dev_team/intent_classifier.py` — heuristics + Haiku fallback
- [ ] `backend/src/dev_team/prompts/` — 8 system prompt files
- [ ] `backend/src/dev_team/agents/base.py` — DevAgent ABC
- [ ] `backend/src/dev_team/agents/business_analyst.py`
- [ ] `backend/src/dev_team/agents/enterprise_architect.py`
- [ ] `backend/src/dev_team/agents/solution_architect.py`
- [ ] `backend/src/dev_team/agents/developer.py`
- [ ] `backend/src/dev_team/agents/process_organiser.py`
- [ ] `backend/src/dev_team/agents/test_script_writer.py`
- [ ] `backend/src/dev_team/agents/tester.py`
- [ ] `backend/src/dev_team/agents/bug_fixer.py`
- [ ] `backend/src/dev_team/pipeline.py` — orchestrator with bug-fix loop + EA post-build guard
- [ ] `backend/src/dev_team/cli.py` — entry point
- [ ] `CLAUDE.md` §21 auto-trigger rule
- [ ] Boot test (`python -c "from src.dev_team.pipeline import Pipeline"`)
- [ ] Smoke test with a tiny requirement

## Acceptance criteria

- Pipeline runs end-to-end without crashing on a tiny requirement
- All 9 agent outputs land at `tasks/agent-outputs/<agent>/<FEAT-NNN>_*.json`
- `tasks/process-hierarchy.md` contains the new feature row, no other changes
- `tasks/pipeline-runs.md` contains an append-only entry for this run
- EA post-build runs even if bug-fix loop hits MAX_ITERATIONS
- CLAUDE.md §21 references `python -m src.dev_team.cli`
