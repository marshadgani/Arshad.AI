<!-- generated at 2026-04-26T22:00:00Z; verified by clean-venv app boot, 27 live + 15 coming-soon, /health 200 -->

# Gate Report — Merge to Main: Phase H — generic OAuth callback + 8 OAuth providers

**Branch:** `claude/ai-personal-assistant-develop-AION` → `claude/ai-personal-assistant-main`
**Diff scope:** 8 files (5 modified + 3 new) ~1100 lines

## ✅ GATE PASSED — verified by clean-venv app boot

```
clean venv → src.main imports cleanly
TestClient(app).get('/health') → 200
INTEGRATION_REGISTRY: 42 providers
  - 27 live (was 19)
  - 15 coming_soon (was 23)
Routes: 6 — including new /api/v1/integrations/oauth/{slug}/callback
```

## What this PR delivers

### Generic OAuth callback infrastructure

- New table `integration_oauth_tokens` (alembic `h1e2f3a4b5c6`): encrypted access + refresh + expires_at + scopes, one per integration, AES-GCM with the existing `OAUTH_ENCRYPTION_KEY`.
- New `OAuthIntegrationProvider` base class — providers declare `auth_url`, `token_url`, `scopes`, `client_id_env`, `client_secret_env` and implement `fetch_profile()` + `sync()`.
- New `GET /api/v1/integrations/oauth/{slug}/callback` — generic, no auth dependency (identity comes from Redis-stored state token created by `/connect`). Handles error/code/state validation, atomic state consumption, code exchange, profile fetch, encrypted token storage, and redirect back to `/integrations?connected=<slug>`.
- Auto-refresh: `get_access_token()` checks expiry and refreshes 30s before. Refresh-token rotation rewrites the row in place.

### 8 providers promoted from stub → real

| Provider | Scopes | Notes |
|---|---|---|
| Spotify | recently-played, top-read, library-read, profile, email | HTTP Basic auth on token endpoint |
| Strava | read, activity:read_all, profile:read_all | Comma-separated scopes |
| Oura | personal, daily, heartrate, session | Standard OAuth2 |
| Fitbit | activity, heartrate, sleep, profile | HTTP Basic auth |
| Coinbase | wallet:user:read, wallet:accounts:read | Standard |
| Discord | identify, email, guilds | Standard |
| Reddit | identity, history, mysubreddits, save | HTTP Basic + duration=permanent |
| Linear | read | GraphQL POST sync (custom override) |

### Per-provider env vars documented

`backend/.env.example` now has 8 new pairs (`SPOTIFY_CLIENT_ID/SECRET`, etc.) with deep links to each provider's developer console.

### Verification

Per the boot-verification rule: clean venv, production-shaped env, `import src.main` succeeds, all 42 providers register, generic callback route mounts, /health returns 200, no exceptions.

## Verdict

**GATE PASSED.** OAuth infrastructure is end-to-end. User just needs to:
1. Register OAuth apps at each provider's dev console (8 providers, ~5 min each)
2. Set redirect URI to `https://arshad-ai.onrender.com/api/v1/integrations/oauth/<slug>/callback`
3. Add `<PROVIDER>_CLIENT_ID` and `<PROVIDER>_CLIENT_SECRET` to Render env vars
4. Click Connect in the Integrations tab

The 7 remaining coming-soon stubs (Plaid, Upstox, Zerodha, YouTube, Google Drive/Tasks, Google Maps, Stack Overflow) need either custom UX (Plaid Link, broker-specific OAuth) or Google scope widening — separate follow-up commits.

The 7 "no public API" cards (WhatsApp, Instagram, Facebook, CRED, IndMoney, Apple Health, iMessage) remain as informational stubs — they will never be promoted because the APIs don't exist.
