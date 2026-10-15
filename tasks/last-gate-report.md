### ⚠️ GATE PASSED WITH WARNINGS — Ready for merge

**FEAT-180: Calendly source for the trip checker**

Eight agents ran: code-reviewer, security-auditor, debugger, test-writer, refactorer, doc-writer, silent-failure-hunter, pr-test-analyzer. No Critical findings. Every security finding was fixed in this push.

**Verdict: WARN.**

Fixed in this push:
- Timezone: trip days are now the user's local days. The window edges use the timezone saved with the Calendly profile and fall back to UTC. Before, a 01:00 meeting on day one in Riyadh was dropped and the verdict could be a false "go".
- SEC-001 and SEC-002: the Calendly user URI is stored once, in `Integration.config`, and no longer returned by the status endpoint.
- SEC-003: a rejected token during sync marks the integration expired, so the trip check asks for a reconnect.
- A missing token, a missing user URI and a token that cannot be decrypted now ask for a reconnect. Before, the last one was a 500 and broke the always-200 contract.
- Connect fails loudly if the account row is missing instead of skipping the save.
- Calendly time parameters are sent with a trailing `Z`.
- Frontend: not connected is a status note, an unreadable Calendly read is a severe alert, internal names no longer show in text, `calendly` added to the Integrations page names.
- Docs: route and service docstrings, `CalendlyFetchResult` field notes, `.claude/rules/api.md`.
- New tests: request shape sent to Calendly, caller and slug scoping of the lookup, timezone windows, undecryptable token, config merge, missing account row, expired status on rejected token.

Suites: backend targeted 329 passed. Full backend shows the same database-dependent baseline as main (9 failed, 55 errors). Frontend 513 passed, `tsc` clean. Ruff clean on changed files.

Deferred warnings:
- [ ] Only the first page of 100 meetings is read. A busy user over a long trip gets "unknown". Follow `next_page_token` with a page cap.
- [ ] A Calendly 403 marks the integration expired. A plan or permission 403 would also ask for a reconnect.
- [ ] The Calendly call runs before the Shopify and Calendar fetches, adding up to 15 seconds in the worst case. Run it concurrently.
- [ ] A meeting booked through Calendly and synced to Google Calendar shows twice.
- [ ] Per-request live call has no cache and no handling of Calendly rate limits.
- [ ] Refactors: share the Calendly API constant, the window helper, and the event-overlap loop with the Calendar path, align `partial_failure` with `partial_failures`.
- [ ] More tests: route branches for expired Shopify and Shopify fetch error, merge duplicate frontend test files, tighten loose assertions in `IntegrationsCalendly.test.tsx`.
- [ ] Neither Calendly nor the Booking.com source runs on real data until the owner connects them on the Integrations page.
