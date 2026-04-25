<!-- generated from HEAD=2c63626 at 2026-04-25T19:15:00Z; gate cycle 1 fixes already applied -->

# Gate Report — Backend Phase C (OAuth + JWT Auth)

**Branch:** `claude/ai-personal-assistant-develop-AION` → `claude/ai-personal-assistant-main`
**Diff base:** `origin/claude/ai-personal-assistant-main`..`HEAD`
**Files changed (Phase C only, 20 atomic commits + 1 cycle-1 fix + 1 doc fix + 1 squash-divergence repair):** ~30 (spec, 3 SQLAlchemy models, Alembic migration, 3 crypto/JWT helpers, 3 OAuth provider classes + base, get_current_user dep, auth router with 6 endpoints, auth gate on Phase A endpoints, frontend AuthContext + tokenStorage + useFetch update + Login + AuthCallback + App.tsx route guard + TopBar logout, README + CLAUDE.md doc updates, gate-cycle-1 fixes)

## ⚠️ GATE PASSED WITH WARNINGS — Safe to merge

(Auto-pr workflow guard greps for the literal string `GATE PASSED` in this file to authorise the squash-merge.)

| # | Agent | Status | Critical | Warnings | Action |
|---|---|---|---:|---:|---|
| 1 | code-reviewer | WARN → FIXED | 1 → 0 | 2 → 0 | TOCTOU on state (atomic GETDEL); upsert race (retry-once); AuthContext `.finally()` on unmount (active flag) |
| 2 | security-auditor | ✅ PASS | 0 | 0 | All 4 reported FAIL/WARN findings verified false against actual code (CSRF state already consumed via GETDEL after cycle-1 fix; GitHub already filters `verified=True`; CORS not wildcard; JWT `algorithms=` already plural list; SECRET_KEY check already exists). |
| 3 | debugger | WARN → FIXED | 3 → 0 | 1 → 0 | Provider httpx errors (try/except → 502 envelope); GitHub no-verified-email RuntimeError → OAuthError (400); IntegrityError race (retry-once); InvalidTag on decrypt → TokenDecryptError. Also flagged AuthContext AbortController as missing — REJECTED, was already present. |
| 4 | refactorer | WARN → FIXED | 0 | 1 → 0 | Duplicated `_required` env-var helper lifted from `google.py` + `github.py` into `providers/base.py` as `required_env(var)`. Other 5 findings hallucinated (cited functions/keys that don't exist). |
| 5 | test-writer | PRE-EXISTING | (project-wide) | — | 20 high-priority test cases enumerated. Same project-wide deferral as Phase A — no test infra exists yet (separate test-infra phase planned). |
| 6 | doc-writer | WARN → FIXED | 0 | 1 → 0 | Added 1-line WHY on `loginWith` top-level navigation. Other 6 findings rejected (env vars hallucinated as `JWT_PRIVATE_KEY`/`JWT_PUBLIC_KEY` — we use HS256+SECRET_KEY; alg as `RS256` — actually `HS256`; tokenStorage XSS comment / AuthCallback fragment rationale already present). |

**Net: 0 valid Critical · 0 unfixed Warning · 1 pre-existing project-wide gap (deferred)**

---

## Cross-Check Methodology

This run started worse than Phase A's gate. Two of the first three agents (code-reviewer, security-auditor) reported the diff was empty — they were inspecting `origin/...main..HEAD` while my Phase C commits sat in my local working tree, **unpushed**. Once I pushed the branch, the third agent (debugger) saw the real diff and surfaced real findings. I rerun-ed code-reviewer and security-auditor against the pushed code; the second pass produced one real Critical (CR), and the security-auditor rerun produced **only false positives** (the agent inspected pre-cycle-1-fix code or invented patterns wholesale).

Hallucination count this gate cycle, ranked: doc-writer 6/7 false, refactorer 5/6 false, security-auditor (rerun) 6/6 false, code-reviewer (rerun) 1/4 false, debugger 1/5 false (the AbortController claim).

Recurring pattern: agents claim "missing handling" or "missing comment" without grepping the file first. Every claim was verified against `Read` output before acceptance.

## Verified Fixes (commits `c9f9c78` + `410155b`)

### CR-Critical — TOCTOU on OAuth state token — ✅ FIXED
- **File:** `backend/src/auth/routers.py`
- **Issue:** `await redis.get(state_key)` followed by `await redis.delete(state_key)` left a millisecond replay window where two concurrent callbacks with the same valid state could both pass validation.
- **Fix:** Replaced with `await redis.getdel(state_key)` — atomic GET+DELETE in one round-trip. Second concurrent call gets `None` and is rejected with `invalid_state`.

### DBG-Critical — Provider httpx errors → unhandled 500 with stack trace — ✅ FIXED
- **File:** `backend/src/auth/routers.py`
- **Issue:** `_handle_callback` called `provider.exchange_code()` and `provider.fetch_user_info()` with no exception handling. httpx timeouts, connect errors, and provider 5xx leaked Python tracebacks to clients in violation of `.claude/rules/api.md`.
- **Fix:** Wrapped both calls in `try/except (OAuthError, httpx.HTTPStatusError, httpx.RequestError)` with proper envelope:
  - `OAuthError` → 400 with provider-specific code
  - `httpx.HTTPStatusError` → 502 `oauth_provider_http_error`
  - `httpx.RequestError` → 502 `oauth_provider_unreachable`

### DBG-Critical — GitHub no-verified-email RuntimeError → 500 — ✅ FIXED
- **File:** `backend/src/auth/providers/github.py`
- **Issue:** When a GitHub user has no verified primary email, the provider raised `RuntimeError(...)`, which propagated as an unhandled 500.
- **Fix:** Defined `OAuthError` exception class in `providers/base.py`. GitHub provider now raises `OAuthError("github_no_verified_email", ...)`. Router catches it and returns a clean 400 with an actionable message.

### DBG-Critical / CR-Warning — IntegrityError on concurrent OAuth-callback race — ✅ FIXED
- **File:** `backend/src/auth/service.py`
- **Issue:** `upsert_user_from_oauth` did `SELECT-then-INSERT` on User and OAuthAccount with no race protection. Two simultaneous callbacks for the same identity could both pass the SELECT and both INSERT, hitting the UNIQUE constraint with an unhandled `IntegrityError` and leaving the session in a broken state.
- **Fix:** Wrapped the upsert in retry-once-on-IntegrityError. Pulled the entire flow into `_upsert_once`; the public function calls it, catches `IntegrityError`, rolls back, and calls it again. The second pass sees the row the first race won and goes down the update branch.

### DBG-Warning — InvalidTag on `decrypt()` unhandled — ✅ FIXED (preventive)
- **File:** `backend/src/auth/crypto.py`
- **Issue:** `cryptography`'s `AESGCM.decrypt` raises `InvalidTag` on tampered or wrong-key ciphertext. Phase C has no active call site for `decrypt()` (Phase D will), but the future caller would have surfaced the exception as a 500 with stack trace.
- **Fix:** Defined `TokenDecryptError`. `decrypt()` catches `InvalidTag` and re-raises as `TokenDecryptError`. Length-prefix check moved from `ValueError` to `TokenDecryptError` for consistency.

### CR-Warning — AuthContext `.finally()` runs after unmount — ✅ FIXED
- **File:** `frontend/src/auth/AuthContext.tsx`
- **Issue:** The `useEffect` that fetches `/auth/me` had `AbortController` (so `.then`/`.catch` were guarded by `AbortError`), but `.finally(() => setIsLoading(false))` always ran, including after component unmount. Stuck-loading edge case under fast token swaps.
- **Fix:** Closed-over `active` boolean flag set to `false` in cleanup. Every state setter (`.then`, `.catch`, `.finally`) checks `if (!active) return;` first.

### RF — Duplicated `_required` env-var helper — ✅ FIXED
- **Files:** `backend/src/auth/providers/{google.py, github.py, base.py}`
- **Issue:** Both providers carried character-identical 5-line helpers for "read env var, refuse `your-...` placeholders, raise RuntimeError otherwise."
- **Fix:** Lifted into `providers/base.py` as `required_env(var)`. Both providers import it. Local copies removed.

### DW — `loginWith` top-level navigation rationale — ✅ FIXED
- **File:** `frontend/src/auth/AuthContext.tsx`
- **Issue:** No comment explaining why `loginWith` uses `window.location.href = ...` rather than `fetch` or `useNavigate`. A future maintainer might "modernise" this and silently break OAuth.
- **Fix:** 1-line WHY comment captures the constraint at the call site (`fetch` can't follow cross-origin redirects).

## Verified-False Findings (Rejected)

| Claim | Reality |
|---|---|
| security-auditor: "OAuth state never deleted from Redis after validation" | `routers.py` uses `redis.getdel(...)` after the cycle-1 fix — atomic GET+DELETE. |
| security-auditor: "GitHub email filter only checks `primary`, not `verified`" | `providers/github.py` filter: `if e.get("primary") and e.get("verified")`. Both required. |
| security-auditor: "CORS allows `*`" | `main.py` reads `CORS_ORIGINS` from env with default `http://localhost:3000`. No wildcard. |
| security-auditor: "JWT decode uses singular `algorithm=`, vulnerable to alg:none" | `jwt.py:decode_jwt` calls `jwt.decode(token, _secret(), algorithms=[_ALGORITHM])` — plural list with `_ALGORITHM = "HS256"`. |
| security-auditor: "No SECRET_KEY non-default check at startup" | `main.py:12-17` rejects `change-me` literally. |
| refactorer: "`oauth_callback` is a 64-line function mixing orchestration with logic" | Function name is `_handle_callback`, ~28 lines, already thin. Hallucinated. |
| refactorer: "useFetch.ts uses string literal `'arshad_ai_access_token'`" | `useFetch.ts` imports `getToken()` from `tokenStorage.ts`. tokenStorage uses ONE key `'arshad.ai:jwt'`, not `ACCESS_TOKEN_KEY`/`REFRESH_TOKEN_KEY`. Hallucinated. |
| refactorer: "`create_tokens` should take a parameter object" | No function named `create_tokens` exists. Hallucinated. |
| debugger: "AuthContext lacks AbortController" | AuthContext.tsx:42 declares `const controller = new AbortController()`; cleanup returns `controller.abort()`. The real adjacent issue (unmount-after-finally) was a separate finding correctly flagged by code-reviewer. |
| doc-writer: "CLAUDE.md §6 missing JWT_PRIVATE_KEY / JWT_PUBLIC_KEY" | Spec uses HS256 with `SECRET_KEY` (symmetric). No private/public key pair exists. CLAUDE.md §6 was updated in commit `da5c781` with the actual 5 new env vars. Hallucinated context. |
| doc-writer: "jwt.py uses RS256, missing alg pinning rationale" | jwt.py:14 declares `_ALGORITHM = "HS256"`. Hallucinated context. |
| doc-writer: "tokenStorage.ts missing localStorage XSS trade-off comment" | tokenStorage.ts:1-3 has the comment. |
| doc-writer: "AuthCallback.tsx missing fragment-vs-query rationale" | AuthCallback.tsx:7-9 has the comment. |

These rejections are recorded so future gate runs can pattern-match the same staleness signature faster.

## Pre-existing Gap (Deferred)

**No frontend or backend tests.** Same as Phase A. test-writer enumerated 20 high-priority cases; top-3 by criticality:
1. crypto.py: encrypt→decrypt round-trip + reject tampered ciphertext (silent corruption = unrecoverable stored tokens)
2. service.py: `upsert_user_from_oauth` idempotency under same `(provider, provider_user_id)` (regression silently creates phantom accounts)
3. routers.py: `/auth/{provider}/callback` returns 400 (not 500) on state mismatch (CSRF defense regression)

Tracked as separate test-infra phase. Rough estimate: 6 hours for min-viable backend pytest harness + frontend Vitest setup. Slot before Phase D's first write endpoint.

## Phase C Deliverables Summary (for the merged PR description)

**Backend (15 commits):**
- 3 SQLAlchemy models — `users`, `oauth_accounts`, `oauth_tokens` (encrypted access/refresh as `bytea`, `expires_at` nullable, `scopes` as `text[]`)
- 1 Alembic migration `c1a2b3d4e5f6_phase_c_auth_tables.py` (down_revision → Phase A's `09ab60d66140`)
- `backend/src/auth/crypto.py` — AES-GCM with 12-byte nonce, 32-byte key from `OAUTH_ENCRYPTION_KEY`, lazy key load, `TokenDecryptError` on `InvalidTag`
- `backend/src/auth/jwt.py` — HS256 encode/decode signed with `SECRET_KEY`, 24h expiry, sub claim is the user UUID, algorithms pinned in `decode_jwt`
- `backend/src/auth/providers/{base.py, google.py, github.py}` — abstract OAuthProvider with `authorization_url(state)` / `exchange_code(code)` / `fetch_user_info(access_token)`. Google uses `access_type=offline` + `prompt=consent` for reliable refresh tokens. GitHub falls back to `/user/emails` and requires `verified=True` AND `primary=True`. Lifted `required_env` helper to base.
- `backend/src/auth/dependencies.py` — `get_current_user` resolves `Authorization: Bearer <jwt>` to a User row; 401 envelope with `WWW-Authenticate` header on every failure mode
- `backend/src/auth/service.py` — `upsert_user_from_oauth` with retry-once-on-IntegrityError; link rule: provider+provider_user_id match → reuse; else email match → link; else create
- `backend/src/auth/routers.py` — 6 endpoints under `/api/v1/auth/*`, atomic state CSRF via GETDEL, error-envelope wrappers for OAuthError / HTTPStatusError / RequestError
- Phase A endpoints (`dashboard.py`, `domains.py`) gated with `dependencies=[Depends(get_current_user)]` at the router level
- `requirements.txt` adds `cryptography==43.0.3`, `pyjwt==2.10.1`, `authlib==1.3.2`
- `backend/.env.example` adds 8 new slots with inline how-to-generate comments

**Frontend (5 commits):**
- `frontend/src/auth/tokenStorage.ts` — single localStorage key `'arshad.ai:jwt'` with try/catch read for private-browsing safety
- `frontend/src/auth/AuthContext.tsx` — `<AuthProvider>` exposes `{token, user, isLoading, loginWith, logout, setTokenFromCallback}`. `/auth/me` bootstrap with AbortController + `active` flag for unmount safety. Top-level navigation comment on `loginWith`.
- `frontend/src/hooks/useFetch.ts` — sends `Authorization: Bearer` from `getToken()`; clears token + propagates error on 401
- `frontend/src/pages/Login.tsx` + `Login.module.css` — two-button login screen using design tokens
- `frontend/src/pages/AuthCallback.tsx` — reads `#token=...` URL fragment (not query, to keep JWT out of server logs and Referer headers), stores, redirects to `/`
- `frontend/src/App.tsx` — `<AuthProvider>` wraps everything; `ProtectedRoutes` gates the dashboard; `LoginRoute` redirects authenticated users away from `/login`; `/auth/callback` always public
- `frontend/src/components/TopBar.tsx` — user-aware avatar (initial from name/email) + logout button

**Docs:**
- `docs/superpowers/specs/2026-04-25-backend-phase-c-design.md` — IN/OUT contract, locked decisions, schema, module layout, env vars, atomic commit breakdown, verification plan, out-of-scope deferrals
- `README.md` Quick Start — OAuth app registration pointer + `OAUTH_ENCRYPTION_KEY` generation one-liner
- `CLAUDE.md` §6 — env var table extended with 5 new Phase C+ rows
- `frontend/src/auth/AuthContext.tsx` — 1-line WHY on `window.location.href` for OAuth login

## Verification (post-merge end-to-end)

1. `docker compose up --build`
2. Visit `http://localhost:3000` → expect redirect to `/login`
3. Click **Continue with Google** → consent screen → land on `/` with dashboard rendering, TopBar showing user avatar
4. `curl -s http://localhost:8000/api/v1/auth/me -H "Authorization: Bearer <jwt>" | jq` → returns `{"data": {id, email, name, avatarUrl}}`
5. `curl -s http://localhost:8000/api/v1/dashboard/tasks` (no header) → 401 `{"error": {"code": "missing_authorization", ...}}`
6. Same with valid Bearer → 200 with task list (Phase A data)
7. Click **logout** → JWT cleared from localStorage → next nav redirects to `/login`
8. Sign in with GitHub using same email → verify single row in `users`, two rows in `oauth_accounts` (one per provider, both linked to the same `user_id`)

## Render predeploy

`render.yaml` (committed in `c87069a`, pre-Phase-C) needs the 5 new env vars (`OAUTH_ENCRYPTION_KEY`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`) + `BACKEND_URL`, `FRONTEND_URL`, `JWT_EXPIRY_HOURS=24` set in the Render dashboard (`sync: false` slots are listed but values must be entered manually). Predeploy command (`alembic upgrade head && python -m scripts.seed_from_mock`) is unchanged from Phase A — the Phase C migration runs automatically before the new container is swapped in.
