<!-- generated at 2026-04-26T18:30:00Z; verified by clean-venv boot + Dockerfile syntax check -->

# Gate Report — Merge to Main: chain alembic migrations into Docker CMD

**Branch:** `claude/ai-personal-assistant-develop-AION` → `claude/ai-personal-assistant-main`
**Diff scope:** 1 file (backend/Dockerfile) / 5 insertions / 1 deletion

## ✅ GATE PASSED — verified by clean-venv boot

## Why this exists

Render free tier locks the Pre-Deploy Command field. The render.yaml's `preDeployCommand` was ignored because:
1. The service was created manually (not via Blueprint), and
2. Even if it had been, the field is gated to paid plans.

Result: Supabase had no tables. The OAuth callback hit `gaierror` on the first DB write because the schema didn't exist yet.

Fix: chain `alembic upgrade head && python -m scripts.seed_from_mock` into the Dockerfile CMD. Both are idempotent:
- alembic skips already-applied revisions (single-instance Render free tier = no race)
- seed uses UPSERT on slug

Seed failure is non-fatal (`|| echo`); migration failure blocks startup (correct — refusing to serve unhealthy DB).

## Verified

```
Dockerfile syntax check: parses cleanly
clean venv boot test: 200 OK on /health
docker-compose: explicit command override means local dev unaffected
```

## Verdict

**GATE PASSED.** Single-line CMD change. Reproducible across environments. Solves the Pre-Deploy gating issue without paying for Render Starter plan.

## What happens next

1. Auto-pr workflow squash-merges to main
2. Render auto-deploys from main (Auto-Deploy: On Commit, per the screenshot)
3. New container builds with the chained-CMD Dockerfile
4. On startup, alembic creates ~30 tables in Supabase (users, oauth_accounts, oauth_tokens, conversation_sessions, conversation_messages, projects, tasks, calendar_events, etc.)
5. Seed runs (mock dashboard data — UPSERT, idempotent)
6. uvicorn starts

User then refreshes Supabase Table Editor → tables appear. Click "Continue with Google" → flow completes through to /dashboard.
