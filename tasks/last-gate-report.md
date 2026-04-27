<!-- generated at 2026-04-26T18:00:00Z; verified by clean-venv boot with simulated Supabase URL -->

# Gate Report — Merge to Main: Supabase pgbouncer compatibility

**Branch:** `claude/ai-personal-assistant-develop-AION` → `claude/ai-personal-assistant-main`
**Diff scope:** 2 files / runtime engine + alembic migration runner

## ✅ GATE PASSED — verified by clean-venv boot

When `DATABASE_URL` points at Supabase's session pooler (`*.pooler.supabase.com:6543`), asyncpg's automatic prepared statement cache breaks because each query may land on a different pgbouncer-upstream connection. This commit:

1. `backend/src/models/database.py` — detects `pooler.supabase.com` or `pgbouncer` in the URL and disables the statement cache via `connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0}`.
2. `backend/alembic/env.py` — same detection, same fix, so migrations run cleanly against Supabase too.

**Pre-existing behavior is unchanged** when the URL points at a non-pooler host (Render Postgres, local docker compose). The detection is host-substring based and only activates for known pooler hosts.

## Verified

```
DATABASE_URL=postgresql+asyncpg://postgres:test@aws-0-us-east-1.pooler.supabase.com:6543/postgres
→ engine.url = ...pooler.supabase.com:6543/postgres
→ pooler-aware config applied
→ TestClient(app).get('/health') → 200
```

## Verdict

**GATE PASSED.** Surgical change scoped to pooler URLs. Boot verified.
