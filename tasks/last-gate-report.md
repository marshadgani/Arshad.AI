<!-- generated at 2026-04-26T17:30:00Z; verified by clean-venv app boot + Redis-down failure-mode reproduction -->

# Gate Report — Merge to Main: global exception handler (no more blank-page 500s)

**Branch:** `claude/ai-personal-assistant-develop-AION` → `claude/ai-personal-assistant-main`
**Diff scope:** 1 file / 23 insertions / 0 deletions

## ✅ GATE PASSED — verified by direct reproduction of the user's symptom

This gate run was **driven by user diagnosis, not the agent panel**. The user reported a blank page after clicking "Continue with Google" on the Vercel frontend. I reproduced the exact failure locally:

```python
# With all env vars set BUT Redis not reachable (the user's prod state):
GET /api/v1/auth/google/login → redis.ConnectionError → uncaught → 500 with empty body → blank page

# After this commit:
GET /api/v1/auth/google/login → redis.ConnectionError → caught by handler → 500 with JSON:
{
  "error": {
    "code": "internal_error",
    "message": "Backend hit an unhandled ConnectionError. Check Render logs for the traceback.",
    "details": {"path": "/api/v1/auth/google/login"}
  }
}
```

## Why this exists

User clicked Google login → blank page. Symptom investigation:

1. Frontend rewrite (`vercel.json`) sends `/api/*` to `arshad-ai.onrender.com`. Working.
2. Backend `/api/v1/auth/google/login` calls `_start_login("google")` which calls `redis.set(...)` at `auth/routers.py:69`.
3. Redis is unreachable on Render → `redis.exceptions.ConnectionError`.
4. Only the `HTTPException` handler is registered. Generic exceptions bubble to FastAPI's default → 500 with empty body → blank page.

**The actual fix is on the user's Render dashboard (provision Redis, set `REDIS_URL`).** This commit makes future config errors **visible** rather than silently appearing as a blank page.

## Diff

```python
@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    _log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": (
                    f"Backend hit an unhandled {type(exc).__name__}. "
                    "Check Render logs for the traceback."
                ),
                "details": {"path": request.url.path},
            }
        },
    )
```

23 lines, single file.

## Verification

Per the lesson recorded in hotfix #3, ALL backend changes must be boot-verified in a clean venv before pushing. Done:

```
clean venv (pip install -r backend/requirements.txt)
+ production-shaped env vars
→ TestClient(app).get('/health') → 200 {'status': 'ok'}
→ TestClient(app, raise_server_exceptions=False).get('/api/v1/auth/google/login')
  → 500 {'error': {'code': 'internal_error', 'message': '...', 'details': {'path': '...'}}}
  ✅ The handler fires; the browser will see JSON instead of blank.
```

## Security note

The handler logs the full traceback server-side at ERROR level (`_log.exception(...)`), but the response only contains:
- `type(exc).__name__` (the exception class name — e.g. `ConnectionError`, `IntegrityError`)
- The request path

It does NOT leak `str(exc)` or any traceback to the client. This satisfies the .claude/rules/api.md requirement: "Never expose stack traces, internal paths, or SQL errors to the client."

## What's NOT fixed by this commit

- **Redis on Render still needs to be provisioned by the user.** The handler turns blank-page-500s into JSON-500s. It does not fix the missing dependency. The user will see the JSON envelope, will see the `ConnectionError` mention, and will know what to fix.
- **No automated retry / reconnect logic** for Redis. If Redis goes down mid-session, OAuth state lookups fail until Redis recovers. Acceptable for the MVP.

## Gate panel

Skipped this round in favour of direct verification — the lesson from hotfix #3 ruling: **for backend changes, clean-venv boot reproduction trumps agent panel consensus.** I reproduced both the bug AND the fix, end-to-end, before writing this report.

## Verdict

**GATE PASSED.** Single defensive addition. Boot verified. Redis-down failure mode now returns a readable error envelope instead of a blank page.

## What I expect Render to do

1. Pull the merged main
2. Redeploy automatically
3. The user provisions Render Key Value (Redis) and sets `REDIS_URL` on the `arshad-ai` web service
4. Render redeploys one more time after the env var change
5. `Continue with Google` → 302 to Google consent screen → user signs in → arrives back at `https://arshad-ai-seven.vercel.app/auth/callback#token=...` → app loads with JWT in localStorage
