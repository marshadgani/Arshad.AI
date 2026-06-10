# FEAT-001 — Live Dashboard Data Integration — Deployment Guide

> **Feature:** Replaces mock data behind `GET /api/v1/dashboard/events` and
> `GET /api/v1/dashboard/briefing` with live Google Calendar, Gmail, and Claude AI.
> Falls back gracefully to seeded DB mock data on `TokenUnavailableError` or any
> upstream failure.
>
> **Operational risk:** LOW. No DB migration, no new dependencies, no infra changes.
> **Primary operational concern:** silent degradation — all failure paths return HTTP 200.

---

## 1. Pre-Deployment Checklist

### 1.1 Environment Variables

| Variable | Required | Failure mode if missing |
|---|---|---|
| `ANTHROPIC_API_KEY` | For live briefing | Briefing silently degrades to template summary; WARNING logged. App stays up. |
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | For live Calendar + Gmail | `TokenUnavailableError` → mock fallback. |
| `OAUTH_ENCRYPTION_KEY` | For token decryption | Token retrieval fails → mock fallback. |
| `DATABASE_URL` | Always | Hard failure — fallback path also needs DB. |

- [ ] `ANTHROPIC_API_KEY` present and valid in target environment secrets store.
- [ ] Google OAuth credentials present (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`).
- [ ] `OAUTH_ENCRYPTION_KEY` present and **unchanged** (rotation locks out all stored tokens).
- [ ] Confirm `ANTHROPIC_API_KEY` is not set to a placeholder/dev value.

### 1.2 OAuth Scope Verification (most likely silent failure)

The existing OAuth grant **must** include both Calendar read and Gmail read scopes. If
the user's stored grant predates this feature, it may lack the Gmail scope — Calendar
will work but Gmail unread count silently returns `None`.

- [ ] Verify OAuth consent screen / grant includes:
  - `https://www.googleapis.com/auth/calendar.events` (or broader)
  - `https://www.googleapis.com/auth/gmail.modify` (or narrower read-only)
- [ ] If scopes were added, the user must **re-consent** — existing tokens won't gain new scopes.

### 1.3 Seeded Mock Data (fallback dependency)

- [ ] `events` table has seeded rows (fallback for `/events`).
- [ ] `daily_briefings` table has ≥1 seeded row (fallback for `/briefing`).
  - `_singleton` raises `HTTPException(404)` if no row exists — the only non-200 path.

### 1.4 External Connectivity

- [ ] Egress to `www.googleapis.com:443` permitted from backend host.
- [ ] Egress to `gmail.googleapis.com:443` permitted.
- [ ] Egress to `api.anthropic.com:443` permitted.
- [ ] Confirm no outbound proxy strips the `Authorization` header.

### 1.5 Dependencies

- [ ] `anthropic==0.42.0` present in `requirements.txt` — no change needed.
- [ ] `httpx` present — no change needed.
- [ ] No migration to run (`alembic upgrade` not required for this feature).

### 1.6 Smoke Test (post-deploy)

- [ ] `GET /health` → 200.
- [ ] `GET /api/v1/dashboard/events` (authed, Google connected) → live events, `source: "Google"`.
- [ ] `GET /api/v1/dashboard/events` (authed, Google NOT connected) → mock events, 200.
- [ ] `GET /api/v1/dashboard/briefing` (authed, Google connected) → 200 with `greeting`/`date`/`summary`.
- [ ] `GET /api/v1/dashboard/briefing` (authed, Google NOT connected) → mock briefing, 200.
- [ ] Inspect logs: confirm no token or API-key values appear.

---

## 2. Monitoring & Observability

> **Why this matters more than usual:** every failure path returns **HTTP 200**.
> Standard 5xx error-rate dashboards will show this feature as 100% healthy even
> when fully degraded to mock data. Instrument the degradation signals explicitly.

### 2.1 Key Metrics

| Metric | Log signal | What it tells you |
|---|---|---|
| Live calendar fallback | `WARNING: Live calendar fetch failed` | Calendar API error or token problem |
| Live briefing calendar fail | `WARNING: Calendar fetch failed in briefing` | Same, inside briefing path |
| Live briefing Gmail fail | `WARNING: Gmail fetch failed in briefing` | Gmail scope missing or API error |
| Claude degradation | `WARNING: Claude briefing generation failed/timed out` | Anthropic outage, bad key, or timeout |
| Malformed event skipped | `WARNING: Skipping unparseable calendar event id=` | Corrupt Calendar API response |

The single most valuable signal is **unexpected WARNING frequency** — a sudden spike
means a real upstream outage hidden behind HTTP 200s.

### 2.2 Distinguishing "200 healthy" from "200 degraded"

- True live success: no WARNINGs, events have `source: "Google"`.
- Partial briefing: Gmail WARNING but briefing still generated (missing unread context).
- Full mock: `TokenUnavailableError` path — user has not connected Google.

---

## 3. Scaling Considerations

| Dimension | Current (v1) | When to revisit |
|---|---|---|
| Async fan-out | `asyncio.gather` for Calendar + Gmail — optimal | No change needed |
| HTTP client | Per-call `httpx.AsyncClient` | Move to shared lifespan client if request volume rises significantly |
| Claude cost | One call per `/briefing` request | **Add Redis caching (TTL ~5–15 min)** — Redis already provisioned; `compose_briefing` is pure so caching is a clean layer-on |
| DB load | Single `SELECT` per fallback; no N+1 | None |
| Rate limits | Google + Anthropic per-key quotas | Monitor for 429s; add backoff if observed |

---

## 4. Reliability & Rollback

### 4.1 Failure Behaviour

| Failure | Result | HTTP |
|---|---|---|
| Google not connected (`TokenUnavailableError`) | Seeded mock data | 200 |
| Calendar API error / timeout | Mock events (`/events`) / empty events in briefing | 200 |
| Gmail API error / timeout | Briefing without unread count (`unread=None`) | 200 |
| Claude error / timeout (8 s) | Template summary | 200 |
| One malformed calendar event | That event skipped, rest returned | 200 |
| **No seeded briefing row** | `HTTPException(404)` | **404** |

### 4.2 Rollback

Pure code change across 5 files, no DB migration — rollback is trivial:

1. Revert `backend/src/api/v1/dashboard.py` to the previous commit.
2. Delete the four new service files:
   - `backend/src/services/ai_client.py`
   - `backend/src/services/google_calendar.py`
   - `backend/src/services/gmail_client.py`
   - `backend/src/services/briefing.py`
3. No `alembic downgrade` required.
4. No data cleanup — feature writes nothing to the DB.

### 4.3 Safe Deploy Sequence

1. Deploy code (no migration step).
2. Run §1.6 smoke tests.
3. Watch WARNING log frequency for 15 min.
4. If unexpected WARNINGs appear → check OAuth scopes (§1.2) and `ANTHROPIC_API_KEY` before assuming a code problem.

---

## 5. Alerting Recommendations

| Alert | Condition | Severity |
|---|---|---|
| Claude degradation | `briefing generation failed` WARNING rate > 25% over 5 min | WARNING |
| Calendar/Gmail outage | Respective WARNING rate > 20% over 5 min | WARNING |
| Claude latency creep | `/briefing` p95 > 6 s | INFO (approaching 8 s timeout) |
| Briefing 404 | Any 404 from `/briefing` | HIGH — seeded fallback row missing |

> Because degradation is silent (HTTP 200), prefer **rate-based** alerts on
> WARNING log counters over HTTP status-code alerts.

---

## 6. Summary

- **Deploy risk:** LOW — no migration, no new deps, no infra change.
- **Rollback:** revert 5 files, no DB action.
- **Top operational watch item:** silent degradation behind HTTP 200 — watch WARNING logs.
- **Top follow-up:** Redis-cache the briefing to control per-request Claude cost.
- **Most common first-deployment silent failure:** OAuth grant missing the Gmail scope (§1.2).
