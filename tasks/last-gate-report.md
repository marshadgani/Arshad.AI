# Merge-to-Main Gate Report — FEAT-143 (Password Login alongside OAuth)

**Branch:** `dev-team/feat-143-password-auth-halted-denylist`
**Diff base:** `claude/arshad-ai-e2e-testing-fdb9vc`
**Date:** 2026-09-14

## Verdict: ⚠️ WARN — fixed and ready for merge

The gate initially came back **BLOCKED** (a coverage FAIL plus a security-exception
WARN, which auto-upgrades to FAIL per this repo's rules). Both have been fixed and
verified in this branch. Everything remaining is WARN-level, non-blocking, and
listed as a checklist below for Arshad's discretion.

## What this feature is

Adds username/password login as a second auth method alongside the existing
Google/GitHub OAuth flow, on one combined login screen. This is the 3rd design
iteration — the first two were rejected by Architecture Critic (timing oracle,
untestable test, self-lockout rate limiter, silent scope change; then a rate-limit
topology claim that wasn't empirically checked). This 3rd design converged cleanly
and was then blocked only by the pipeline's own `backend/src/auth/` denylist —
Arshad reviewed and approved that exception directly (recorded in
`.claude/workflows/dev-team-pipeline.js`'s `DENY_EXCEPTIONS`, same precedent as
FEAT-120).

## Fixed in this gate cycle

### 1. Coverage FAIL → fixed (test-writer gate)
`lockout.py` — the actual brute-force defense for this feature — sat at ~35-40%
coverage; every existing test bypassed it via a fixture or only hit the
Redis-outage escape hatch. Added 10 tests covering the actual 429-at-threshold
enforcement, `record_failure`/`clear_failures` call verification with the
normalized email, the Redis pipeline itself, and the missed kill-switch sentinel
values (`"0"`, `"no"`). Commit `3078bd98`.

### 2. Security WARN → fixed (security-auditor: SEC-001; code-reviewer: W3)
The global rate-limit backstop (`identity="global"`, was `limit=10/min`) is a
single shared counter any anonymous caller could hold saturated indefinitely,
429-ing the real owner's login attempts too — while its own docstring claimed it
"cannot lock the owner out." Raised the limit to 100/min (a genuine-flood
threshold, not a casual-retry one) and corrected the docstring to state the
tradeoff honestly: it's a CPU backstop, not an account guard; the per-email
lockout is the real brute-force defense; OAuth is on a separate route/bucket and
stays available whenever this one saturates. Commit `b258268e`.

## Agent-by-agent results

| Agent | Verdict | Findings |
|---|---|---|
| code-reviewer | WARN | W1: `set_password.py` has no 128-char cap matching the login endpoint's `max_length`, so an over-length password locks the owner out with no diagnostic. W2: the 422 handler's `json.dumps` has no `default=`, latent crash if a future validator ever raises with a non-serializable `ctx` value. W3: **fixed above** (folded into SEC-001 fix). |
| security-auditor | WARN→fixed | SEC-001: **fixed above**. SEC-002–006: informational, no action needed — accepted tradeoffs already documented (self-DoS via targeted lockout, bcrypt cost/pre-hash design, `set_password.py` credential handling, JWT parity with OAuth, localStorage token storage). |
| debugger | WARN | Malformed `password_hash` in the DB crashes `bcrypt.checkpw` with an unhandled 500 instead of the clean 401 every other branch returns (also breaks the timing-oracle invariant on that one branch). `set_password.py` commits the new hash *before* its own post-write verification check, so a failed check reports "not confirmed set" when the write already landed. Plus 4 lower-severity suggestions (soft check-then-act race in the lockout counter, `ctx` audit note, import-time `_DUMMY_HASH` cost, `set_password.py` connection-error handling). |
| test-writer (coverage) | FAIL→fixed | **Fixed above.** |
| refactorer | WARN | Dead `_envelope()` helper in `routers.py` duplicates `http_error()` from `api/errors.py` (pre-dates this feature, not introduced by it — the new password-login code already uses `http_error()` correctly). Two low-severity clarity suggestions (a `lockout.py` docstring gap, a redundant double-`instanceof` ternary in `Login.tsx`). |
| doc-writer | WARN | Missing typed Pydantic response model on `POST /password/login` (returns raw `dict`), missing OpenAPI `responses=` annotation for the three distinct error codes, two minor comment gaps. The substantive design docstrings (timing-oracle rationale, lockout fail-closed rationale, `set_password.py` runbook) were called out as done well. |
| silent-failure-hunter | WARN | Redis-swallow points in `lockout.py` log a warning but emit no metric — sustained (not full-outage) Redis flakiness could erode the lockout guarantee without paging anyone; caught only by the manual post-deploy log check. One low-severity suggestion (unguarded `res.json()` on the frontend success path, inconsistent with the guarded error path next to it). |
| pr-test-analyzer (test quality) | Gap→fixed | Same lockout coverage gap as test-writer, **fixed above**. Confirmed both historical anti-patterns (wall-clock timing test, false-green kill-switch test) are genuinely resolved, not just renamed away. |

## Non-blocking checklist for Arshad (WARN-level, not auto-fixed per gate protocol)

- [ ] `set_password.py`: enforce the same 128-char password cap the login endpoint has, so an over-length password can't be set and then silently rejected at login.
- [ ] 422 handler in `main.py`: use `jsonable_encoder` on the scrubbed error list to avoid a latent crash if a future validator's `ctx` ever carries a non-JSON-serializable value.
- [ ] `password.py`: guard `bcrypt.checkpw`'s `ValueError` (malformed stored hash) and treat it as verification failure, so it returns the same clean 401 as every other branch instead of an unhandled 500.
- [ ] `set_password.py`: reorder so the post-write verification happens before `commit()`, or make the failure message accurate about the write already having landed.
- [ ] `routers.py`: remove the dead `_envelope()` helper, replace its call sites with `http_error()` (pre-existing duplication, not introduced by this feature).
- [ ] Add a typed `PasswordLoginResponse` model and `responses=` OpenAPI annotations to `POST /password/login`.
- [ ] Consider a metric (not just a log line) on `lockout.py`'s Redis-swallow points for real-time observability of sustained Redis flakiness.
- [ ] Guard `res.json()` on the frontend success path in `api/auth.ts` (currently only the error path is guarded).

None of these block the merge. They're real, worth doing, and left for Arshad to prioritize alongside the rest of the backlog.
