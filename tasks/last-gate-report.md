<!-- generated 2026-04-26T23:00:00Z; verified by clean-venv app boot, 35 live + 7 coming-soon (informational only) -->

# Gate Report — Phase H wave 4: Stack Overflow + Plaid + Upstox + Zerodha Kite

**Branch:** `claude/ai-personal-assistant-develop-AION` → `claude/ai-personal-assistant-main`
**Diff scope:** 3 modified + 4 new files

## ✅ GATE PASSED — verified by clean-venv app boot

```
Total: 42 integrations
Live:  35 (was 31)
Soon:   7 (was 11) — all "no public API" informational cards
```

## What this PR delivers

### 4 new real providers

| Provider | Slug | Class | Notes |
|---|---|---|---|
| Stack Overflow | `stack_overflow` | personal_apikey | Stack Exchange API v2.3, paste-access-token flow |
| Plaid | `plaid` | personal_apikey | US banking — accepts public_token (Link exchange) OR direct access_token |
| Upstox | `upstox` | personal_oauth | Indian broker — uses Phase H OAuth callback |
| Zerodha Kite | `zerodha_kite` | personal_oauth | Indian broker — custom token exchange (SHA256 checksum); paid Kite Connect required |

### Implementation highlights

- **Plaid**: dual-mode connect — `{public_token}` triggers /item/public_token/exchange, `{api_key}` stores a sandbox access_token directly. Sync calls /accounts/get and caches account list + balances. Frontend Link button arrives in Phase J.
- **Zerodha Kite**: Kite Connect's auth flow is non-standard — auth URL takes `api_key=` not `client_id=`, token endpoint requires `SHA256(api_key + request_token + api_secret)` as the checksum. The provider overrides `connect()` and `exchange_code()` to handle this, then falls back into the standard OAuthIntegrationProvider flow.
- **Upstox**: Standard OAuth2 via the Phase H base class. No scope param (Upstox doesn't use it).
- **Stack Overflow**: Public API supports a per-user access token. Uses the personal_apikey kind so each user pastes their own token.

### Coming-soon list reduced to 7

All remaining coming-soon cards are "No public API" informational ones:
- WhatsApp (personal), Instagram (personal), Facebook (personal)
- CRED, IndMoney
- Apple Health (web), iMessage

These will never be promoted because the APIs don't exist for personal/consumer use.

### Per-provider env vars added to .env.example

```
UPSTOX_CLIENT_ID / UPSTOX_CLIENT_SECRET
ZERODHA_KITE_CLIENT_ID / ZERODHA_KITE_CLIENT_SECRET
PLAID_CLIENT_ID / PLAID_SECRET / PLAID_ENV (sandbox/development/production)
```

## Verification

Boot-verified in clean venv: app imports cleanly, all 35 live + 7 coming-soon = 42 total registered, generic OAuth callback route mounts, /health returns 200.

## Verdict

**GATE PASSED.** Phase H is functionally complete. The remaining 7 cards are intentional placeholders for services without public APIs.

## Next phases (optional)

- **Phase I — frontend Plaid Link** (1-click bank connection instead of paste-public-token)
- **Phase J — Apple Health iOS Shortcuts webhook** (the only viable workaround)
- **Phase K — RAG over ingested_* tables** (cross-source semantic search)
