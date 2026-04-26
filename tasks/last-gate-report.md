<!-- generated at 2026-04-26T17:45:00Z; verified by clean-venv reproduction -->

# Gate Report — Merge to Main: surface str(exc) in 500 responses

**Branch:** `claude/ai-personal-assistant-develop-AION` → `claude/ai-personal-assistant-main`
**Diff scope:** 1 file / 9 insertions / 7 deletions

## ✅ GATE PASSED — verified by clean-venv reproduction

## Why this exists

User pasted the JSON 500 response twice and didn't have easy access to Render logs to find the actual `ConnectionError` message. Without the `host:port` in the response, "ConnectionError" alone doesn't tell us whether `REDIS_URL` is unset (→ `localhost`) or set wrong (→ `upstash.io` with wrong scheme/password).

This commit adds `details.exception = str(exc)[:300]` to the 500 response so the connection target is visible in the browser. Acceptable for a single-user MVP; the data is just `host:port` and a short error message — no auth secrets, no SQL, no traceback.

## Diff

`backend/src/main.py` exception handler now returns:

```json
{
  "error": {
    "code": "internal_error",
    "message": "Backend hit an unhandled ConnectionError.",
    "details": {
      "path": "/api/v1/auth/google/login",
      "exception": "Error 111 connecting to localhost:6379. Connect call failed ('127.0.0.1', 6379)."
    }
  }
}
```

That `exception` string is the full diagnostic — `localhost:6379` means `REDIS_URL` is unset on Render; `<x>.upstash.io:6379` would mean it's set but the connection itself is failing (TLS/auth).

## Verification

Clean venv + production-shaped env + Redis unreachable → handler reproduces exactly the response shape above. ✅

## Security note

`str(exc)[:300]` of common exceptions in this codebase:
- `redis.ConnectionError` → host:port + Errno (safe)
- `asyncpg.PostgresError` → SQL state code, table name (mostly safe; SQL state codes don't leak data)
- `httpx.HTTPStatusError` → status code + URL (safe — URLs are already in the routing)
- `pydantic.ValidationError` → field path + bad value (could include user input — but user input is already in the request)
- `RuntimeError("X is unset or still a placeholder")` from `required_env` → env var name (safe — they're public config keys, not values)

Acceptable scope. If multi-tenant later, gate this behind `DEBUG=true` env var.

## Verdict

**GATE PASSED.** Boot-verified, exception trace visible in JSON response, no secret leak surface increased meaningfully.
