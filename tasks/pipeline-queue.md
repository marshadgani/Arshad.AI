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
| relaunched | 2026-09-06 with 15 features: FEAT-118 (fixed metadata), FEAT-119, FEAT-120 (amended to forbid persisting biometrics at rest, per Arshad's decision), FEAT-121-124, 126-128, 130-134. |

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

| FEAT_ID | Requirement (short) | Status | Branch | EA Decision | Notes |
|---|---|---|---|---|---|
| FEAT-118 | Chat window blocks screen (redesign) + app-wide mobile responsiveness | in_flight | dev-team/feat-118-* (TBD) | — | Fixed the seeded metadata (domain: `Infrastructure`, sub_section: `Frontend` — an established category, not the invented `ui-layout-shell`) and relaunched in the 15-feature combined run below. |
| FEAT-119 | Shopify integration — live store confirmed to have real orders. Populate `/shopify` domain page (currently a stub) with real KPIs (revenue, order count, conversion rate, low-stock count) and a live order feed, per the connector-analysis recommendation. New OAuth-backed integration provider following the Whoop pattern. | in_flight | dev-team/feat-119-* (TBD) | — | Previous Architecture Critic blocking findings (broken `connect()` signature, unpersisted `shop_domain`, 4 HIGH + 6 MEDIUM issues) will be fed back automatically — added a redesign loop to the pipeline script (`archIter`, capped at 2 extra rounds): a blocking verdict now sends the findings back to Solution Architect for a corrected SDD and re-reviews, only halting for real if still blocking after that. Relaunched in the 15-feature combined run below. |
| FEAT-120 | Connect Whoop and Apple Fitness/Health data to populate the Health & Fitness dashboard section. Whoop already has partial backend integration (`backend/src/api/v1/whoop.py`, `backend/src/integrations/personal/oauth_providers.py`) — this feature should audit/complete it and add the missing Apple Health side. | in_flight | dev-team/feat-120-* (TBD) | — | **Arshad's decision recorded**: biometrics stay live-only, NOT persisted at rest — the requirement text now hard-constrains this explicitly, reversing nothing. The Apple Health ingest-token delivery bug (B1) will be fed back through the same redesign loop as FEAT-119. Relaunched in the 15-feature combined run below. |
| FEAT-121 | Google Calendar: auto-book focus blocks sized to real `tasks/pipeline-queue.md` backlog depth (title them with the actual FEAT-IDs, auto-delete when the queue drains); flag any booked-but-uncommitted focus block as leaked time. Plus a one-time 12-month time audit — classify past events into the 6 CLAUDE.md business domains and compare against stated priorities. Plus (folded in per Arshad's approve-all, low priority): poll Spotify `get_currently_playing` during booked focus blocks as a weak-but-free signal of whether the block was actually used — booked-vs-observed. | in_flight | — | — | Per connector-ideation pass 2. Spotify's own report explicitly said this only makes sense as a small side-effect of something else, never its own feature — folded into this one rather than given a separate FEAT_ID. |
| FEAT-122 | Gmail as universal ingest bus: an Airflow DAG that parses confirmation/notification emails from Shopify, Render, Vercel, Zomato, Uber, Booking.com (sender/subject pattern match + Claude field extraction) into Postgres, feeding PersonalFinance/Travel/ShopifyStore pages with zero new OAuth. Plus a "dropped-ball" detector (auto-label threads where Arshad is the last-reply blocker for 72h+) and populate the Dashboard `decisions`/`notifications` widgets. | in_flight | — | — | Merges report-1's Gmail recommendation with report-2's ingest-bus idea into one feature — do not split, they share the same DAG. |
| FEAT-123 | Google Drive: a permissions audit (`get_file_permissions` across recent/searched files) surfacing files shared "anyone with the link" or with stale collaborators, with one-click revoke. Plus populate the Dashboard `knowledge_suggestions` widget from recent Drive activity. | in_flight | — | — | Per connector-ideation pass 2 + report-1. |
| FEAT-124 | Zoom: a "promise ledger" — extract commitments Arshad made in meetings from transcripts/summaries, cross-check each against Gmail sent mail / GitHub commits+PRs / Calendar to flag broken promises. Feed extracted action items into the Dashboard `tasks` widget (add a `zoom` source value) and file meeting notes into the Obsidian page. Requires a new Zoom OAuth app (no existing provider). | in_flight | — | — | Per connector-ideation pass 2 + report-1. |
| FEAT-125 | Shopify intelligence layer (builds on FEAT-119's base integration): inventory expressed as days-of-cover with stockout alerts escalated when the projected date falls inside a Calendar/Booking.com travel window; a discount-code simulator that rejects codes that can't mathematically break even on margin; a customer-service debt tracker joining orders against Gmail threads for unanswered 24h+ inquiries. | queued | — | — | Depends on FEAT-119 landing first (same OAuth/data layer) — sequence after it. |
| FEAT-126 | Zomato: pre-staged lunch cart automation — when Calendar shows no 20+ minute gap between 12:00-15:00, build the usual order via `create_cart` and send one confirm-to-checkout notification (never auto-checkout). Plus categorize food-delivery spend into the PersonalFinance page. Plus (folded in per Arshad's approve-all, lowest priority in this feature): the late-night-order × late-night-commit "burnout index" correlation chart — the report called this a toy with near-zero real value, so treat it as the last thing built here, not the reason to build the feature. | in_flight | — | — | Per connector-ideation pass 2. |
| FEAT-127 | Figma: a scheduled diff between Figma `get_variable_defs` and `frontend/src/styles/tokens.css`, opening an issue on drift. Plus auto-regenerated architecture diagrams (FigJam) from the domain/agent map in CLAUDE.md whenever it changes. | in_flight | — | — | Conditional per the report: only valuable if Arshad actually maintains a Figma file for the design system — verify before building. |
| FEAT-128 | Canva: batch-generate on-brand product creatives for Shopify SKUs via `create-design-from-brand-template` + `export-design`, using real product data/pricing. Plus a monthly personal-ops one-pager (revenue, deploy health, learning hours, time audit) rendered to a brand template and emailed via Gmail on the 1st. | in_flight | — | — | Per connector-ideation pass 2. |
| FEAT-129 | Booking.com: a trip-feasibility checker run BEFORE booking — cross-references a proposed travel window against Shopify stockout projections, Render/Supabase migration/cron windows, Calendar commitments, and Calendly availability; outputs a single go/no-go with specific conflicts listed alongside accommodation pricing. | queued | — | — | Depends on FEAT-125 (Shopify runway data) — sequence after it. |
| FEAT-130 | Calendly: workload-driven dynamic availability (narrows/widens bookable hours based on `tasks/pipeline-queue.md` depth and calendar load); single-use scheduling links generated into drafted Gmail replies instead of circulating the permanent link; no-show reliability scoring per contact. | in_flight | — | — | Per connector-ideation pass 2 — flagged as the most novel idea in that pass. |
| FEAT-131 | Uber: annotate recurring in-person calendar events with round-trip cost/time-of-attendance (fare × monthly occurrences); a dynamic leave-by alarm accounting for live traffic/surge instead of a static reminder offset. | in_flight | — | — | Per connector-ideation pass 2. |
| FEAT-132 | Render: automatic per-deploy regression verdict — join `list_deploys` timestamps against `list_logs` error rates and `get_metrics` CPU/memory/latency (before vs. after window), post a regression/neutral/improvement verdict as a PR comment. Automates the manual protocol in CLAUDE.md §23. | in_flight | — | — | Per connector-ideation pass 2. |
| FEAT-133 | Supabase: provision an ephemeral Supabase branch per dev-team-pipeline FEAT_ID (`create_branch`/`apply_migration`/`merge_branch`), so schema migrations run against isolated real data and only merge after the quality gate passes. Plus a scheduled `get_advisors` → `scripts/backlog_add.py` feed (autonomous for mechanical findings like missing index, manual review for security-sensitive ones). | in_flight | — | — | The branch-per-feature piece is the largest single build in this whole batch — flagged as substantial complexity in the report. |
| FEAT-134 | Vercel: a toolbar-comment-to-pipeline-feature bridge — a watcher on `list_toolbar_threads`/`get_toolbar_thread` that turns a visual comment on the deployed frontend into a `FEAT-{N}` row in `tasks/pipeline-queue.md` (with deployment URL, element context, screenshot), and replies + resolves the thread with the PR link once the pipeline ships it. Plus poll `get_runtime_errors` into the Dashboard `notifications` widget. | in_flight | — | — | Per connector-ideation pass 2 — Claude's own top pick from that report. |
| FEAT-135 | Coursera: once reconnected, verify whether the connector actually exposes Arshad's own enrollments/progress/streak or only the public course catalogue (the `execute_analytics_query`/`list_enterprise_organizations` tools look enterprise-org scoped, not personal-learner scoped — confirm before building). If personal progress data is real, drive the `/learning` page from Arshad's own defect history instead of a generic catalogue: mine `tasks/last-gate-report.md` and recurring specialist-agent findings (async correctness, N+1 queries, missing indexes, OWASP findings) for weak spots, and surface targeted `search_courses`/`search_videos` results against those specific gaps. | queued (blocked) | — | — | Per Arshad's approve-all — moved from excluded to queued, but still gated: do NOT include in any launch batch until Arshad confirms the reconnect AND the Code Explorer/Solution Architect stages have verified personal progress data is actually retrievable. If it turns out to be catalogue-only, flag back to Arshad rather than building a page against data that doesn't exist. |

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
