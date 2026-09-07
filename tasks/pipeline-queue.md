# Dev-Team Pipeline Queue

> Tracks every feature/change/bug that has gone through, or is waiting to go through,
> the `.claude/workflows/dev-team-pipeline.js` Workflow. Source of truth for resuming
> the pipeline in a NEW session — `resumeFromRunId` only works within the session that
> created the run, so a fresh session re-seeds from the artifacts referenced here
> instead of replaying already-completed stages.

## How to use this file (for Claude, every session)

1. On any user message describing a change, new feature, or bug — assign the next
   `FEAT_ID` from `tasks/.feature-counter` (increment it), and append a row below
   with `status: queued`.
2. If a workflow run is already active THIS session, resume it:
   `Workflow({ scriptPath: ".claude/workflows/dev-team-pipeline.js", resumeFromRunId: "<run_id>", args: { features: [...all queued + in-flight features...] } })`
   — completed features return instantly from cache; the new one interleaves.
3. If this is a NEW session (no active run_id), start a fresh run with `args.features`
   containing only the features still `queued` or `in_flight` in this file. Do NOT
   re-include `completed` features as full entries — their code is already committed;
   there's nothing to resume for them.
4. After each run completes (success, halt, or error), update this file: move the
   row to `completed`/`halted`/`error`, record the branch name and EA decision.
5. Never run two Workflow invocations concurrently against the same run_id from two
   different conversation turns — check `/workflows` or this file's `active_run_id`
   field first.
6. **Never launch a second, separate `Workflow` run while one is still active**, even
   for unrelated new features — the per-role mutex lives in that run's own script
   state and does NOT extend across separate invocations. If a run is active and a
   new feature comes in, add it to the Queue table as `queued` and either wait for
   the active run to settle before launching a combined resume, or let it sit for
   the hourly Routine to pick up together with whatever's still pending then.

## Active run

| Field | Value |
|---|---|
| active_run_id | wf_14899418-22d |
| session | session_01S3fJzZzJykfHRA9jhMycuk |
| started | 2026-09-06 |
| 15-feature batch | Settled 2026-09-07 — ALL halted. See Queue table for per-feature reasons. |
| convergence-test batch | Launched 2026-09-07 (task `wm5xz1tv5`): FEAT-119 + FEAT-121 only, testing a fix to the Architecture Critic redesign-loop prompt (added an explicit "Read the actual cited files" instruction and changed it to patch the previous SDD instead of regenerating from scratch). If these two converge, relaunch the other 9 Architecture-Critic-blocked halts (122,123,124,127,128,131,132,133,134) plus FEAT-120 in the same manner. FEAT-126/130 need their BPDD revised per EA's resubmission checklist first, not a code redesign. |

*(A run_id is only valid within the session that created it. If you're in a different session, ignore this field and start fresh per step 3 above — then update this table.)*

## Always-on continuation (standing Routine)

Per CLAUDE.md's "🔁 Always-On Pipeline" policy, this queue is checked and driven
forward automatically, not just when Arshad is actively chatting:

| Field | Value |
|---|---|
| routine_id | trig_018w2XJ9mHBfqUZ1uciMNqit |
| name | Dev-Team Pipeline Continuation |
| schedule | hourly (`create_new_session_on_fire: true`) |
| created | 2026-09-06 |

If this routine is ever missing (check `list_triggers`), recreate it — see CLAUDE.md.
Every firing reads this file, resumes/restarts any `queued`/`in_flight`/`error`
feature's Workflow run, and updates this file when it settles. It no-ops if the
queue below is empty.

## Queue

**2026-09-07 — the 15-feature combined run (`wf_14899418-22d`) completed. Every
single feature halted — none shipped.** Root causes: FEAT-118 hit a real
pre-existing security escalation (fixed directly, see below); 11 features hit
Architecture Critic still blocking after 2 redesign rounds (investigating —
found the redesign prompt never told Solution Architect to re-read the actual
cited files or patch its previous SDD instead of regenerating blind; fixed and
testing convergence on a small batch now); FEAT-120 hit a real denylist
violation (kept per decision, see notes); FEAT-126/130 halted earlier at EA
pre-build with resubmission checklists.

| FEAT_ID | Requirement (short) | Status | Branch | EA Decision | Notes |
|---|---|---|---|---|---|
| FEAT-118 | Chat window blocks screen (redesign) + app-wide mobile responsiveness | halted | — | — | Reached all the way to EA post-build and only halted on Security Auditor escalations (SEC-001: 41 dependency CVEs incl. 11 on pyjwt's exact jwt.decode() path; SEC-002: OAuth login CSRF/session fixation). **Both fixed directly** (commit `66cde24`), not through the pipeline — see `backend/requirements.txt` and `backend/src/auth/routers.py`. FEAT-118's own feature code hasn't been re-run since; needs a fresh security-auditor pass to formally close, since the fix landed outside the pipeline's `code` accumulator. |
| FEAT-119 | Shopify integration — live store confirmed to have real orders. | in_flight | dev-team/feat-119-* (TBD) | — | Was Architecture Critic-blocked (broken `connect()` signature, unpersisted `shop_domain`, timezone/throttling bugs) even after 2 redesign rounds. Now in the 2-feature convergence test (`wm5xz1tv5`) with the fixed redesign prompt (explicit Read-the-file instruction + patch-don't-regenerate). |
| FEAT-120 | Whoop + Apple Health for Health & Fitness. | halted | — | — | Denylist violation: an agent wrote `backend/src/middleware/rate_limit.py` directly to disk via its own Write tool, bypassing the script's JSON-based check. Content reviewed directly — safe, a legitimate Whoop-rate-limiter extraction now shared with the Apple Health ingest route. **Kept per explicit decision** (commit `c61ebe2`); the denylist enforcement gap itself is a known unresolved issue (script has no filesystem access to verify actual disk state — see note below). Not yet relaunched; needs its own redesign-loop retry once FEAT-119/121 confirm convergence. |
| FEAT-121 | Google Calendar auto-booking + time audit + Spotify focus-telemetry. | in_flight | — | — | Was Architecture Critic-blocked (crash-recovery-impossible schema, false-positive leaked-time detection, unstable evidence timestamps) even after 2 redesign rounds. Now in the 2-feature convergence test (`wm5xz1tv5`). |
| FEAT-122 | Gmail universal ingest bus + dropped-ball detector. | halted | — | — | Architecture Critic still blocking after 2 rounds (non-functional retry logic in `_retry.py`). Awaiting the convergence-test result before relaunching. |
| FEAT-123 | Google Drive permissions audit + knowledge_suggestions. | halted | — | — | Architecture Critic still blocking after 2 rounds (Alembic `down_revision` doesn't point at the actual head — verified against the real migration file). Awaiting the convergence-test result. |
| FEAT-124 | Zoom promise ledger + Obsidian filing. | halted | — | — | Architecture Critic still blocking after 2 rounds (new DAG ids never registered in the ingestion runner — dead code path). Awaiting the convergence-test result. |
| FEAT-125 | Shopify intelligence layer (builds on FEAT-119). | queued | — | — | Depends on FEAT-119 landing first — **do not launch until FEAT-119 shows `completed`**. |
| FEAT-126 | Zomato pre-staged cart + spend tracking + burnout chart (lowest priority). | halted | — | — | Halted earlier than the others — **EA pre-build rejected** (not Architecture Critic) with a resubmission checklist: resolve domain placement (calendar vs. new 'lifestyle' domain), inherit the standard OAuth base class, add missing FKs, route through `services/gateway.py`, use an ingested_* table naming pattern, and drop the burnout chart into its own separate FEAT entirely. Needs the BPDD itself revised, not just a code redesign — different fix path than the Architecture-Critic-blocked features. |
| FEAT-127 | Figma token-drift check + auto-diagrams. | halted | — | — | Architecture Critic still blocking after 2 rounds — ironically for building the Figma substrate anyway despite the requirement explicitly saying to flag back instead of building against nothing. Awaiting the convergence-test result. |
| FEAT-128 | Canva product creatives + monthly one-pager. | halted | — | — | Architecture Critic still blocking after 2 rounds (Shopify API version pinned outside its support window). Awaiting the convergence-test result. |
| FEAT-129 | Booking.com trip-feasibility checker (builds on FEAT-125). | queued | — | — | Depends on FEAT-125 — **do not launch until FEAT-125 shows `completed`**. |
| FEAT-130 | Calendly dynamic availability + single-use links + no-show scoring. | halted | — | — | Halted at **EA pre-build** (non-blocking refinement items: rate limiting on the public booking endpoint, URL-encoding edge case, a deployment-doc note, a dedup/idempotency requirement for the no-show DAG). Same different-fix-path note as FEAT-126 — revise the BPDD, not a code redesign. |
| FEAT-131 | Uber cost-of-attendance annotation + leave-by alarm. | halted | — | — | Architecture Critic still blocking after 2 rounds (`CREATE INDEX CONCURRENTLY` inside an Alembic migration — will fail at deploy since Alembic wraps migrations in a transaction). Awaiting the convergence-test result. |
| FEAT-132 | Render per-deploy regression verdict. | halted | — | — | Architecture Critic still blocking after 2 rounds (log level field discarded before the classification step that needs it). Awaiting the convergence-test result. |
| FEAT-133 | Supabase branch-per-feature + advisors-to-backlog. | halted | — | — | Architecture Critic still blocking after 2 rounds (step ordering contradicts the actual orchestrator.md sequence). Awaiting the convergence-test result. |
| FEAT-134 | Vercel toolbar-comment-to-pipeline bridge. | halted | — | — | Architecture Critic still blocking after 2 rounds ("poll get_runtime_errors" has no actual poller wired up). Awaiting the convergence-test result. |
| FEAT-135 | Coursera — verify personal progress data before building `/learning`. | queued (blocked) | — | — | Still gated on Arshad's reconnect — not launched. |

**Cross-feature dependencies — the script has no ordering between features in one batch, so this must be managed by NOT batching dependents with their prerequisites:**
- FEAT-125 (Shopify intelligence layer) needs FEAT-119 (base Shopify integration) to be `completed` first — its Solution Architect stage would otherwise design against Shopify code that doesn't exist yet. **Do not include FEAT-125 in the same `args.features` batch as FEAT-119.**
- FEAT-129 (Booking.com trip-feasibility) needs FEAT-125's runway data — same rule, one batch later again.
- Everything else in this queue (121-124, 126-128, 130-134) has no dependency on another queued feature and can go in the very next batch alongside FEAT-118/119/120's retry.

**Launch plan for the next resume (once `wf_14899418-22d`'s current run settles):** combine FEAT-118, 119, 120 (cached, replay instantly if already completed) with FEAT-121, 122, 123, 124, 126, 127, 128, 130, 131, 132, 133, 134 (12 new features) in ONE `args.features` array. Hold FEAT-125 and FEAT-129 out of that batch — queue them for the batch after FEAT-119 shows `completed`. Hold FEAT-135 (Coursera) out of every batch until Arshad confirms reconnect.

**Permanently excluded — nothing to add regardless of approval, because no concrete feature was ever proposed for these (a technical/legitimacy impossibility, not a value judgment the "approve all" instruction can override):**
- **PayPal, ProfileMaster** — Arshad explicitly said ignore.
- **Uber Eats** — the connector's tool surface is `search` + `publish_analytics` only; there is no order-history or order-status tool, so it structurally cannot provide the personal data any feature here would need.
- **Booking.com as a personal-data source** — the connector is authless (no identity), exposing only public accommodation/attraction search; it cannot return Arshad's own bookings. (Its one legitimate idea, trip-feasibility checking using Calendar/Shopify/Render data instead, is already FEAT-129.)
- **Lusha** — B2B contact/company enrichment; the analysis found no legitimate personal-life-dashboard use case, and force-fitting one would mean running third-party enrichment against people (e.g. store customers) who never consented to it.

Everything else that was ever a real proposal is now queued somewhere above — Spotify's idea folded into FEAT-121, Zomato's "burnout index" folded into FEAT-126, and Coursera moved from excluded to queued-but-blocked as FEAT-135.

**Important — concurrency constraint on launching:** Two or more features can only share the "same specialist role never runs concurrently" guarantee if they run inside the SAME `Workflow()` invocation (the `locks` object is local to one script execution, not shared across separate calls). Never start a second `Workflow` run while another is still active — wait for it to settle, then resume/restart with the full set of pending features in one `args.features` array.

**Known gap:** only 9 of the 28 roles CLAUDE.md documents have actual `.claude/agents/dev-team/*.md` files (`bug-fixer`, `business-analyst`, `developer`, `enterprise-architect`, `orchestrator`, `process-organiser`, `solution-architect`, `test-script-writer`, `tester`). The other ~19 conceptual roles have no dev-team-specific agent — the workflow script maps them to the closest existing agent in the full roster instead (e.g. `system-engineer` → `system-architect`, `senior-engineer` → `code-analyzer`). If a future stage errors with "agent type not found," check this mapping first before assuming it's a new bug.

## Completed

*(none yet — move rows here from Queue once a run finishes, with final branch + EA decision)*
