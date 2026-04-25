# Backend Phase C — OAuth + JWT Auth

**Date:** 2026-04-25
**Phase:** C of 6 (sequence: A → C → D → E → F → B; chat is last)
**Goal:** Multi-user OAuth login (Google + GitHub) with self-issued JWT bearer auth. Provider tokens encrypted at rest. Phase A's read endpoints become auth-gated.

---

## 1. What's in scope

| In | Out |
|---|---|
| `users`, `oauth_accounts`, `oauth_tokens` tables | Password signup (OAuth-only) |
| Alembic migration for the three tables | Token refresh logic (Phase D) |
| Google OAuth provider — `openid email profile calendar.events gmail.modify gmail.send` | Real Google/GitHub API calls (Phase D) |
| GitHub OAuth provider — `read:user user:email repo` (full) | Account deletion / admin tooling |
| AES-GCM encryption of access/refresh tokens at rest | JWT secret rotation (manual, out of scope) |
| HS256 JWT issuance (24h expiry, signed with `SECRET_KEY`) | Encryption key rotation (manual, out of scope) |
| `get_current_user` FastAPI dependency | HttpOnly cookie path (locked to localStorage + Bearer) |
| 6 endpoints: 2× `/login`, 2× `/callback`, `/me`, `/logout` | Mock-OAuth dev mode (real apps from day 1) |
| Auth gating on every Phase A endpoint | Multi-session/device JWT revocation |
| Frontend `AuthContext`, `Login`, `AuthCallback`, route guard, logout button | Email verification flow (provider-trusted) |
| `useFetch` sends `Authorization: Bearer` from localStorage | E2E tests (separate test-infra phase) |

---

## 2. Locked decisions

1. **Multi-user.** First successful OAuth login creates the user row. If a second provider returns a verified email matching an existing user, the new `oauth_accounts` row links to that user instead of creating a duplicate.
2. **Self-issued JWT (HS256, `SECRET_KEY`, 24h expiry).** Frontend stores in `localStorage`, sends as `Authorization: Bearer <jwt>`.
3. **Encrypted `oauth_tokens` table** — AES-GCM, key from `OAUTH_ENCRYPTION_KEY` env var (32-byte URL-safe base64).
4. **Real OAuth apps**, no mock path. User has registered both Google Cloud OAuth client and GitHub OAuth app.

---

## 3. Database schema (3 new tables)

### `users`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | `default=uuid.uuid4` |
| `email` | TEXT, unique, lowered | Single email per user — second-provider login keys here |
| `name` | TEXT, nullable | Display name from provider |
| `avatar_url` | TEXT, nullable | First non-null wins |
| `created_at` / `updated_at` | TIMESTAMP | Auto |

Index: unique on `lower(email)` (handled by storing email already lowered).

### `oauth_accounts`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → `users.id` ON DELETE CASCADE | |
| `provider` | TEXT, enum (`google`, `github`) | |
| `provider_user_id` | TEXT | Stable provider-side ID |
| `provider_email` | TEXT, lowered | What the provider returned (may differ from `users.email` over time) |
| `created_at` / `updated_at` | TIMESTAMP | |

Constraints:
- `UNIQUE(provider, provider_user_id)` — prevents duplicate linkage
- Index on `user_id`

### `oauth_tokens`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `oauth_account_id` | UUID FK → `oauth_accounts.id` ON DELETE CASCADE, **unique** | One token row per account |
| `encrypted_access_token` | BYTEA | AES-GCM ciphertext, includes nonce prefix |
| `encrypted_refresh_token` | BYTEA, nullable | Google only; GitHub OAuth Apps don't issue refresh tokens |
| `token_expires_at` | TIMESTAMP, nullable | NULL when provider doesn't expire (e.g. GitHub) |
| `scopes` | TEXT[] | Granted scopes, for diff/repair on next auth |
| `created_at` / `updated_at` | TIMESTAMP | |

> **No `sessions` table.** JWT is stateless. Logout is purely client-side (drop the localStorage entry). Documented trade-off: a stolen JWT is valid until expiry — accepted because expiry is short and the alternative (Redis session lookup on every call) doubles request latency.

---

## 4. Backend module layout

```
backend/src/auth/
├── __init__.py
├── crypto.py           ← AES-GCM encrypt/decrypt helpers (key from env)
├── jwt.py              ← encode_jwt(user_id) / decode_jwt(token)
├── providers/
│   ├── __init__.py
│   ├── base.py         ← OAuthProvider abstract class
│   ├── google.py       ← GoogleOAuthProvider
│   └── github.py       ← GitHubOAuthProvider
├── service.py          ← upsert_user_from_oauth() — the link/create logic
├── dependencies.py     ← get_current_user() FastAPI Depends
└── routers.py          ← /api/v1/auth/* endpoints
```

### Endpoints (all under `/api/v1/auth`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/google/login` | 302 to Google consent (state stored in Redis 5min TTL) |
| GET | `/google/callback?code&state` | Exchange → upsert user → issue JWT → 302 to frontend `/auth/callback#token=…` |
| GET | `/github/login` | 302 to GitHub consent |
| GET | `/github/callback?code&state` | Same shape as Google |
| GET | `/me` | Returns current user (auth required) |
| POST | `/logout` | 204; server-side noop (JWT stateless), exists so the frontend has a clear API surface |

CSRF: every `/login` generates a random `state`, stored in Redis as `oauth_state:<state> = "<provider>"` with 5-min TTL. Callback validates and consumes the key.

### Auth dependency

```python
async def get_current_user(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User: ...
```

Raises `401` if header missing/malformed, JWT invalid/expired, or user no longer exists.

Phase A routers get a single line added: `dependencies=[Depends(get_current_user)]` on the router.

---

## 5. Frontend module layout

```
frontend/src/
├── auth/
│   ├── AuthContext.tsx     ← provider, exposes { user, token, login(provider), logout }
│   ├── useAuth.ts          ← consumer hook
│   └── tokenStorage.ts     ← localStorage helpers (single key: 'arshad.ai:jwt')
├── pages/
│   ├── Login.tsx           ← two big buttons (Sign in with Google / GitHub)
│   └── AuthCallback.tsx    ← reads #token=… fragment, stores, redirects to /
└── hooks/
    └── useFetch.ts         ← UPDATED to send Authorization header
```

`App.tsx` wraps everything in `<AuthProvider>` and adds a route guard:
- If no JWT → redirect to `/login`
- If on `/login` and JWT exists → redirect to `/`
- `/auth/callback` is always accessible

`TopBar.tsx` gains a logout button (right side, next to user avatar).

---

## 6. New env vars

| Var | Where set | Purpose |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | `.env` (local), Render dashboard (prod) | From Google Cloud Console → Credentials |
| `GOOGLE_OAUTH_CLIENT_SECRET` | same | |
| `GITHUB_OAUTH_CLIENT_ID` | same | From github.com/settings/developers |
| `GITHUB_OAUTH_CLIENT_SECRET` | same | |
| `OAUTH_ENCRYPTION_KEY` | same | 32-byte URL-safe base64. Generate: `python3 -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"` |
| `JWT_EXPIRY_HOURS` | same | Default `24` |
| `FRONTEND_URL` | same | For callback redirect (e.g. `http://localhost:3000` or `https://arshad-ai.vercel.app`) |
| `BACKEND_URL` | same | For provider redirect_uri construction (e.g. `http://localhost:8000` or `https://arshad-ai-backend.onrender.com`) |

`backend/.env.example` updated with all eight slots.

---

## 7. Atomic commit breakdown

20 commits (matching the granularity Phase A used). Order is dependency-correct — each commit compiles and passes pre-commit on its own.

| # | Title | Files |
|---|---|---|
| 1 | spec doc | this file |
| 2 | deps + env slots | `backend/requirements.txt`, `backend/.env.example` |
| 3 | User model | `backend/src/models/user.py`, `models/__init__.py` |
| 4 | OAuthAccount model | `backend/src/models/oauth_account.py` |
| 5 | OAuthToken model | `backend/src/models/oauth_token.py` |
| 6 | Alembic migration | `backend/alembic/versions/<hash>_phase_c_auth_tables.py` |
| 7 | crypto helpers | `backend/src/auth/crypto.py` |
| 8 | JWT helpers | `backend/src/auth/jwt.py` |
| 9 | Google provider | `backend/src/auth/providers/{base.py, google.py}` |
| 10 | GitHub provider | `backend/src/auth/providers/github.py` |
| 11 | get_current_user dep | `backend/src/auth/dependencies.py` |
| 12 | auth router | `backend/src/auth/{service.py, routers.py}`, `main.py` |
| 13 | gate Phase A endpoints | `backend/src/api/v1/{dashboard.py, domains.py}` |
| 14 | frontend AuthContext | `frontend/src/auth/{AuthContext.tsx, useAuth.ts, tokenStorage.ts}` |
| 15 | useFetch w/ bearer | `frontend/src/hooks/useFetch.ts` |
| 16 | Login + Callback pages + route guard | `frontend/src/pages/{Login.tsx, AuthCallback.tsx}`, `App.tsx` |
| 17 | logout button | `frontend/src/components/TopBar.tsx` |
| 18 | docs | `README.md`, `CLAUDE.md` |
| 19 | gate report | `tasks/last-gate-report.md` |
| 20 | push triggering auto-merge | (no file change beyond gate report) |

---

## 8. Verification plan (post-merge)

1. `docker compose up --build`
2. `http://localhost:3000` → expect redirect to `/login`
3. Click **Sign in with Google** → consent → land on `/` with dashboard rendering
4. `curl http://localhost:8000/api/v1/auth/me -H "Authorization: Bearer <jwt>"` → returns user JSON
5. `curl http://localhost:8000/api/v1/dashboard/tasks` (no header) → 401
6. Same with valid Bearer → 200 with task list
7. Click **Logout** → JWT cleared → redirected to `/login`
8. In a fresh browser, sign in with **GitHub** using the same email — verify only one row in `users`, two rows in `oauth_accounts`

---

## 9. Out of scope (surfaces in later phases)

- **Token refresh:** Phase D (when first 401 from Google API triggers refresh)
- **Scope expansion mid-session:** Phase D
- **Account deletion:** ad-hoc
- **Admin tooling:** ad-hoc
- **JWT revocation:** would require Redis lookup; deferred until a real threat model exists
- **Encryption key rotation:** documented runbook in a future ops phase

---

## 10. User-side prerequisites (already done by user)

- Google Cloud OAuth client created with redirect URIs:
  - `http://localhost:8000/api/v1/auth/google/callback`
  - `https://<render-backend>/api/v1/auth/google/callback`
- GitHub OAuth app(s) created — one for local, one for prod
- Credentials pasted into `backend/.env` (local) and Render dashboard (prod)
- `OAUTH_ENCRYPTION_KEY` generated and pasted into both
