# Arshad.AI Quality Gate Report

**Branch:** `dev-team/feat-125-feat-125` -> `claude/ai-personal-assistant-main`
**Change:** FEAT-125, Shopify intelligence layer, built by the dev-team pipeline (run wf_fa9f62a9-d89, Enterprise Architect approved). Most of it merged earlier in PR 122. This push carries the last pipeline fixes plus the findings from the 8-agent gate. The feature adds days-of-cover with stockout alerts tied to multi-day all-day Calendar events, a discount-code simulator that rejects codes below cost, and a service-debt tracker that matches never-answered Gmail threads to Shopify orders.
**Date:** 2026-10-10

### ⚠️ GATE PASSED WITH WARNINGS — Ready for merge

## Gate Summary

| # | Agent | Result |
|---|---|---|
| 1 | code-reviewer | PASS. No Critical or Warning. Name de-dup and field masks verified against the callers |
| 2 | security-auditor | PASS after a fix. All routes need auth and rate limiting, data is scoped to the user, variant_id is validated, regex input is escaped. The merchant shop domain no longer reaches the logs |
| 3 | debugger | PASS. The Gmail and Calendar field masks keep every field the code reads |
| 4 | test-writer | PASS. Changed lines are covered. A test now checks the field masks are sent and that duplicate customer names match the first order |
| 5 | refactorer | WARN. Whitespace in customer names is now normalised. The Gmail and Calendar parsers still share a copied dispatch block and the two truncation signals differ in shape. Both deferred |
| 6 | doc-writer | WARN. The Gmail rule is now described correctly (never-replied threads, not last-sender), plus the 90-day look-ahead, return values and cache note |
| 7 | silent-failure-hunter | WARN. A malformed Google reply now flags a partial failure instead of a 500, and a not-connected result is no longer cached. Gmail reauth sharing the top-level flag, 403 scope errors and a null body are deferred |
| 8 | pr-test-analyzer | WARN. Added failure-path tests for the discount, service-debt and cover routes and for the discount simulator screen. Remaining gaps are deferred |

## Verdict: WARN, mergeable

Backend: 1219 pass, 9 fail and 55 errors. The same failures and errors occur without these changes, because they need a database or auth setup. Frontend: `tsc` is clean and 434 tests pass.

## Fixed in this push

- A malformed or undecodable Google reply no longer returns a 500 from the always-200 endpoints.
- Not-connected Gmail or Calendar results are not cached, so a fresh connect shows at once.
- Shopify failure logs carry the exception type and HTTP status only.
- Customer names with extra spaces match again.
- New tests: discount expired, throttled, HTTP error, GraphQL error and malformed price. Cover and service-debt degraded responses are not cached. Safe maximum discount never lands below cost. The simulator screen never shows "Margin OK" for a failed, unconnected or unknown lookup.

## Deferred (non-blocking)

- [ ] Add `gmail_needs_reauth` so the UI can tell Gmail reauth from Shopify reauth.
- [ ] Report a Google 403 for missing scope as a reconnect request.
- [ ] Treat a null provider body as a failure and not as an empty result.
- [ ] Use one convention for Gmail and Calendar truncation.
- [ ] Frontend tests for the remaining Inventory Cover and Service Debt states, the wiring test for the Intelligence panel, and tests for 422 and abort handling in the discount hook.
- [ ] Route tests for the 401 and rate limit paths, and merging duplicate tests between the two backend files.
- [ ] Shopify shop domain no longer logged. The 120 second Redis cache of Gmail snippets stays, and is documented as acceptable.
