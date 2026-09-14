# Integration Disconnect — Architecture Decisions (FEAT-145)

This document records the module boundaries and two verified architectural
findings that shaped the FEAT-145 implementation, all of which must be
preserved as the codebase evolves.

---

## Module map — where each disconnect concern lives

| Concern | Module | Notes |
|---|---|---|
| Provider contract (revocation hooks + `revocation_kind`) | `integrations/base.py` | The ABC every provider inherits. Knows nothing about transactions or the credential tables. |
| Disconnect workflow (prepare → commit → revoke → scrub+flip → log) | `integrations/disconnect.py` | Also owns `DisconnectOutcome` / `RevocationKind` / `UpstreamRevocationResult`. Takes the provider structurally (`RevocableProvider` Protocol), so it never imports `base.py`. |
| Local credential destruction (the DML) | `services/integration_credentials.py` | Single site; adding a future credential table means one new statement here. |
| Who may disconnect a shared (`user_id IS NULL`) integration | `integrations/authz.py` | Pure decision (`allowed` / `unguarded` / `denied`), no FastAPI, no DB session. |
| HTTP contract (404 / 403 / response shape) | `integrations/routers.py` | Maps an `authz` decision onto `http_error`; owns no policy of its own. |

Dependency direction is one-way — `routers.py` → `base.py` →
`disconnect.py` → `services/integration_credentials.py` — with `authz.py`
a leaf. Keep it that way: pushing persistence or policy back up into
`base.py` re-couples the contract all 44 providers inherit to one concrete
teardown strategy, which is exactly what made the pre-FEAT-145
status-flip-only default impossible to fix in one place.

`base.py` re-exports the three disconnect types, so the long-standing
`from .base import DisconnectOutcome` in provider modules and tests stays
valid; import them from either module.

---

## Decision 1 — Shared-OAuth-Account Constraint

### Providers affected

`gmail`, `google_calendar`, `google_drive`, `google_tasks`, `google_youtube`,
`github`

### Finding

These six providers are built on `personal/_shared.py` helpers and **never
create a row in `integration_oauth_tokens` or `api_key_credentials`**. Their
tokens live in `oauth_accounts` / `oauth_tokens`, which have no foreign-key
path from `integrations.id`.

A `scrub_credentials(db, integration_id=<id>)` call for any of these
providers is therefore a **provable no-op**: the three bulk DML statements it
executes touch zero rows, and the function returns `ScrubCounts(0, 0, 0)`. The
Integration row itself survives (intentional — the UI keeps showing a
disconnected card so the user can reconnect later).

### Consequence for disconnect()

These providers correctly set `revocation_kind = 'no_credential'`. The
shared workflow still runs `scrub_credentials` (harmless no-op) and still
flips `integration.status = 'disconnected'` in the same atomic transaction.
The only thing that doesn't happen is an upstream revoke call — there is no
third-party token scoped to this integration to revoke.

### Consequence for the frontend

The list endpoint exposes `revocation_kind` per provider. The frontend renders
the `'no_credential'` dialog variant:

> "Disconnect {name}? This will stop {name} syncing. Your sign-in is
> unaffected — revoke access in your {name} account settings if needed."

This copy is accurate: disconnecting removes the Integration row's `connected`
status, but the underlying Google / GitHub OAuth grant is not touched.

### What would a future credential table require?

If a future feature gave these providers their own token row (e.g. per-scope
refresh tokens in a new `integration_scope_tokens` table), two edits are
needed:

1. Add a `DELETE integration_scope_tokens WHERE integration_id = ?` statement
   in `backend/src/services/integration_credentials.py` — the single
   credential-scrub site.
2. Change `revocation_kind` on the affected providers to `'revokes'` (or
   `'no_revoke'` if the provider has no revocation endpoint) so the frontend
   dialog copy updates automatically.

---

## Decision 2 — Project-ApiKey Authorization

### Affected integration kind

`project_apikey` rows have `user_id IS NULL` — they are shared deployment
infrastructure rather than personal credentials belonging to one user.

### The IDOR that existed before FEAT-145

`_find_user_integration` matched `(user_id == user.id) OR (user_id IS NULL)`.
Before FEAT-145, the disconnect endpoint only flipped a status flag, so any
authenticated user hitting a shared project-apikey integration had cosmetic
consequences at worst.

Once disconnect() started actually deleting `api_key_credentials` rows, this
predicate became an IDOR: any authenticated user could destroy shared
infrastructure credentials.

### The fix

`_find_user_integration_for_disconnect` (used **only** by the disconnect
endpoint — not by sync/status/list) reuses the same lookup and then, for
`user_id IS NULL` rows, consults
`integrations/authz.project_disconnect_decision()`:

- If `INTEGRATION_ADMIN_USER_IDS` **or** `INTEGRATION_ADMIN_EMAILS` is set,
  the calling user must be in the allowed set; otherwise the decision is
  `'denied'` and the router returns HTTP 403
  (`project_integration_admin_required`).
- If **both** env vars are unset (the default for this single-user
  deployment), the decision is `'unguarded'` — **allowed but logged at
  WARNING** — a fail-open fallback that prevents the admin from bricking
  their own Integrations page on a fresh deploy where neither var is
  configured yet.

The decision function is deliberately free of FastAPI and of the DB
session: the policy is one readable, independently testable unit, and the
router keeps sole ownership of the HTTP mapping.

### Why fail-open with WARNING instead of fail-closed?

This is a single-user personal assistant. There are no untrusted authenticated
users: the only authenticated user is Arshad. A fail-closed default (deny
until explicitly whitelisted) would make the disconnect button inoperable on a
fresh Render deploy without a configuration step that has no instructions yet.
Fail-open-with-logging was chosen as the safe middle ground: it prevents
silent abuse (the Render log viewer surfaces the WARNING) while not blocking
the legitimate single-admin use case.

### Env vars

| Variable | Format | Effect |
|---|---|---|
| `INTEGRATION_ADMIN_USER_IDS` | Comma-separated UUIDs | Allows disconnect for `user_id IS NULL` integrations |
| `INTEGRATION_ADMIN_EMAILS` | Comma-separated email addresses (case-insensitive) | Same as above, by email |

Both default to empty string (no restriction, WARNING logged on use).
