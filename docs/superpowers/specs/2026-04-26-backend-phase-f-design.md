# Backend Phase F — Ingestion DAGs + Queue Worker + Event Bus

**Date:** 2026-04-26
**Phase:** F of 6 (sequence: A → C → D → E → F → B; chat is last)
**Goal:** Real ingestion of Calendar / Gmail / GitHub data into Postgres. The 4 `data_pipeline` Phase E placeholder agents become real triggers; ingestion happens in either Airflow (local docker-compose) or an in-process FastAPI worker (Render prod) — same Python code path.

---

## 1. What's in scope

| In | Out |
|---|---|
| `dag_trigger_queue` table — agents INSERT, workers poll-and-claim | Anthropic SDK / chat (Phase B) |
| 4 `ingested_*` tables (hybrid: typed + jsonb) | Periodic `@daily` schedule (locked: on-demand only) |
| `services/ingestion_runner.py` — single ingestion module shared by Airflow + in-process worker | Push notifications / webhooks |
| `services/event_bus.py` — Redis pub/sub publish + subscribe primitives | Direct REST API call to Airflow (locked: DB queue + sensor) |
| `services/queue_worker.py` — async background task; runs on Render via lifespan | Multi-tenant ingestion (single-user product) |
| Replace 4 Phase E `data_pipeline` agents with real INSERT-queue logic | Backfill / historical bulk load — first-run mode is "from now forward" |
| `GET /api/v1/agents/data_pipeline/runs/{run_id}` for status polling | Real-time SSE updates on run progress (Phase B's streamer) |
| 4 Airflow DAGs (thin wrappers calling ingestion_runner) | Cross-user analytics (per-user only) |

---

## 2. Locked decisions

1. **All 3 ingestors + analytics_processor**.
2. **Hybrid storage** — `user_id` (FK), `occurred_at` (timestamptz indexed), `provider_id` (string indexed), `raw jsonb`, `ingested_at` (timestamptz default now). UNIQUE(user_id, provider_id) for upsert idempotency.
3. **DB queue + sensor** — `dag_trigger_queue` row inserted by agent; both Airflow sensor and in-process worker `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1` from it.
4. **Redis pub/sub** — `services/event_bus.py` with `publish(channel, payload)` + `subscribe(channels)`. Each ingestor publishes a batch-completion event after a successful run.
5. **On-demand only** — no `@daily` schedule. Agent endpoint is the trigger. (DAGs can still be triggered manually from the Airflow UI for ops.)
6. **Dual-runner architecture (P)** — Airflow in docker-compose for local dev; FastAPI in-process worker on Render. Both call `services/ingestion_runner.run(dag_id, user_id, payload, db)`.

---

## 3. Database schema additions

### `dag_trigger_queue`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `dag_id` | TEXT | one of `calendar_ingestor`, `email_ingestor`, `github_ingestor`, `analytics_processor` |
| `user_id` | UUID FK → users.id ON DELETE CASCADE | which user's data to ingest |
| `payload` | JSONB | tool-specific args (e.g. `{full_refresh: bool}`) |
| `status` | TEXT, default `pending` | `pending` \| `picked` \| `completed` \| `failed` |
| `requested_at` | TIMESTAMPTZ default now() | |
| `picked_at` | TIMESTAMPTZ, nullable | set when worker claims |
| `completed_at` | TIMESTAMPTZ, nullable | |
| `error_text` | TEXT, nullable | populated on `failed` |
| `attempt` | INTEGER default 0 | retry counter; capped at 3 |

Indexes: `(status, requested_at)` for the worker poll, `(user_id, requested_at desc)` for the run-status endpoint.

### `ingested_calendar_events`, `ingested_gmail_threads`, `ingested_github_activity`, `ingested_analytics_summary`

All four follow the same hybrid shape:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users.id | |
| `occurred_at` | TIMESTAMPTZ | event start / message date / commit date / window end |
| `provider_id` | TEXT | provider's stable ID for upsert (`null` for analytics) |
| `kind` | TEXT, github only | `issue` \| `pr` |
| `metric_key` / `metric_value` | TEXT / NUMERIC, analytics only | window-bucketed metric name + value |
| `raw` | JSONB | provider's response or computation payload |
| `ingested_at` | TIMESTAMPTZ default now() | |

Constraints + indexes:
- UNIQUE(user_id, provider_id) on calendar / gmail / github (allows ON CONFLICT upsert)
- For github specifically: UNIQUE(user_id, kind, provider_id) since issue#3 and pr#3 share number space
- For analytics: UNIQUE(user_id, metric_key, occurred_at) — one bucket per user per metric per window
- Index on `(user_id, occurred_at desc)` per table for time-range queries

One Alembic migration adds all 5 tables.

---

## 4. Module layout

```
backend/src/
├── models/
│   ├── dag_trigger.py           ← DagTriggerQueue
│   └── ingested.py              ← IngestedCalendarEvent, IngestedGmailThread,
│                                  IngestedGitHubActivity, IngestedAnalyticsSummary
├── services/
│   ├── event_bus.py             ← Redis pub/sub publish + subscribe
│   ├── queue_worker.py          ← async loop polling dag_trigger_queue
│   └── ingestion/
│       ├── __init__.py
│       ├── runner.py            ← run(dag_id, user_id, payload, db) -> dispatch
│       ├── calendar.py          ← fetches via google_calendar client, upserts
│       ├── email.py             ← fetches via gmail client
│       ├── github.py            ← fetches via github client
│       └── analytics.py         ← reads ingested_* tables, computes metrics
└── agents/data_pipeline/
    ├── calendar_ingestor.py     ← REPLACE: INSERT queue row, return run_id
    ├── email_ingestor.py        ← same
    ├── github_ingestor.py       ← same
    └── analytics_processor.py   ← same

data-pipelines/ingestion/
├── calendar_dag.py              ← Airflow DAG; sensor → call runner.run(dag_id="calendar_ingestor")
├── email_dag.py
├── github_dag.py
└── analytics_dag.py
```

`backend/src/api/v1/data_pipeline.py` adds:
- `GET /api/v1/agents/data_pipeline/runs/{run_id}` — single run status
- `GET /api/v1/agents/data_pipeline/runs?status=...` — filtered list (for the future dashboard)

---

## 5. Worker contract

```python
# services/queue_worker.py
async def run_worker(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(DagTriggerQueue)
                .where(DagTriggerQueue.status == "pending")
                .order_by(DagTriggerQueue.requested_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                # nothing to do
                pass
            else:
                row.status = "picked"
                row.picked_at = datetime.now(timezone.utc)
                row.attempt += 1
                await db.commit()

                try:
                    await ingestion_runner.run(
                        dag_id=row.dag_id,
                        user_id=row.user_id,
                        payload=row.payload,
                        db=db,
                    )
                    row.status = "completed"
                    row.completed_at = datetime.now(timezone.utc)
                except Exception as exc:
                    row.status = "failed" if row.attempt >= 3 else "pending"
                    row.error_text = f"{type(exc).__name__}: {exc}"
                await db.commit()

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
```

Started from `main.py`'s `lifespan` if `ENABLE_INPROCESS_WORKER=true` (default `false` so docker-compose-Airflow-driven setups don't double-process).

`SELECT ... FOR UPDATE SKIP LOCKED` lets multiple worker instances coexist without claiming the same row twice — important if Render auto-scales the backend or both Airflow and the in-process worker run.

---

## 6. Ingestion runner contract

```python
# services/ingestion/runner.py
async def run(*, dag_id: str, user_id: uuid.UUID, payload: dict, db: AsyncSession) -> dict:
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise IngestionError("user_not_found", f"...")

    if dag_id == "calendar_ingestor":
        return await calendar.ingest(user=user, db=db, payload=payload)
    elif dag_id == "email_ingestor":
        return await email.ingest(user=user, db=db, payload=payload)
    elif dag_id == "github_ingestor":
        return await github.ingest(user=user, db=db, payload=payload)
    elif dag_id == "analytics_processor":
        return await analytics.compute(user=user, db=db, payload=payload)
    else:
        raise IngestionError("unknown_dag", f"...")
```

Each provider runner:
1. Calls the relevant Phase D tool (`calendar_list_events`, `gmail_search_threads`, etc.) to fetch a batch.
2. UPSERTs into the corresponding `ingested_*` table (`ON CONFLICT (user_id, provider_id) DO UPDATE SET raw = EXCLUDED.raw, ingested_at = now()`).
3. Publishes `events.<provider>.ingested` with `{user_id, count, dag_id}`.
4. Returns `{ingested_count, skipped_count}` for the agent's response payload.

Analytics runner:
1. Aggregates over `ingested_*` tables (e.g. "events this week", "PR open count").
2. UPSERTs into `ingested_analytics_summary`.
3. Publishes `events.analytics.computed`.

---

## 7. Replaced agents

Each of the 4 Phase E `data_pipeline` placeholders becomes a thin INSERT-queue agent:

```python
async def run(self, *, user, db, payload):
    row = DagTriggerQueue(
        dag_id="calendar_ingestor",
        user_id=user.id,
        payload=payload.model_dump(),
        status="pending",
    )
    db.add(row)
    await db.commit()
    return CalendarIngestorOutput(
        data={"run_id": str(row.id), "status": "pending"},
        summary={"run_id": str(row.id), "status": "pending"},
    )
```

The agent returns immediately. Status is polled via `GET /api/v1/agents/data_pipeline/runs/{run_id}`.

---

## 8. Event-bus channels

| Channel | Payload |
|---|---|
| `events.calendar.ingested` | `{user_id, dag_id, run_id, ingested_count, skipped_count}` |
| `events.email.ingested` | same shape |
| `events.github.ingested` | same shape (+ `kind`-bucketed counts) |
| `events.analytics.computed` | `{user_id, dag_id, run_id, metric_count}` |

Phase B chat may subscribe to these for "your last sync finished" notifications. Not yet a consumer; channels are emitted regardless.

---

## 9. New env vars

| Var | Required | Description |
|---|---|---|
| `ENABLE_INPROCESS_WORKER` | Phase F+ | `"true"` to start the in-process queue worker on FastAPI lifespan. Default `"false"`. Set to `"true"` on Render (no Airflow); leave `"false"` in docker-compose where Airflow handles it. |
| `QUEUE_POLL_INTERVAL_SECONDS` | Phase F+ | Worker poll interval; default `5`. |
| `MAX_INGEST_BATCH_SIZE` | Phase F+ | Per-DAG row limit per run; default `100`. Caps memory + provider quota. |

Added to `backend/.env.example`. CLAUDE.md §6 env table updated.

---

## 10. Atomic commit breakdown

20 commits.

| # | Title |
|---|---|
| 1 | spec |
| 2 | DagTriggerQueue + 4 ingested_* models + Alembic migration |
| 3 | services/event_bus.py |
| 4 | services/ingestion/runner.py skeleton |
| 5 | services/ingestion/calendar.py |
| 6 | services/ingestion/email.py |
| 7 | services/ingestion/github.py |
| 8 | services/ingestion/analytics.py |
| 9–12 | replace 4 data_pipeline agents |
| 13 | runs status endpoint |
| 14 | services/queue_worker.py + lifespan wiring |
| 15–18 | 4 Airflow DAGs |
| 19 | docs |
| 20 | gate report + push |

---

## 11. Verification (post-merge end-to-end)

1. Sign in. Trigger calendar ingest:
   ```bash
   curl -X POST https://arshad-ai.onrender.com/api/v1/agents/data_pipeline/calendar_ingestor/run \
     -H "Authorization: Bearer $JWT" -d '{}'
   ```
   → 200 `{data: {run_id: "...", status: "pending"}}`.
2. Poll status:
   ```bash
   curl https://arshad-ai.onrender.com/api/v1/agents/data_pipeline/runs/<run_id> -H "Authorization: Bearer $JWT"
   ```
   → progresses `pending` → `picked` → `completed`.
3. Query ingested rows directly via Postgres → see N upserted events with `raw jsonb` populated.
4. Subscribe to `events.calendar.ingested` (e.g. `redis-cli SUBSCRIBE 'events.calendar.ingested'`) — see one message per successful run.
5. Trigger analytics: `POST /api/v1/agents/data_pipeline/analytics_processor/run -d '{"window_days": 7}'`. After completion, `ingested_analytics_summary` rows exist for that window.
6. **Local dev with Airflow**: same agent endpoint, but the Airflow UI at `localhost:8080` shows a triggered run for the matching DAG. The `ENABLE_INPROCESS_WORKER=false` (default) prevents double-processing.

---

## 12. Out of scope (deferred)

- **Anthropic SDK** → Phase B
- **Backfill / historical bulk load** — first run is "from now forward"; if you need 30-day backfill, manually post a `{full_refresh: true, since: "..."}` payload (the runner respects it but doesn't auto-paginate beyond `MAX_INGEST_BATCH_SIZE`)
- **Push notifications / webhooks** — pull-based only
- **Cross-user analytics** — single-user product
- **Tests** — same project-wide deferral
- **`@daily` automation** — locked decision; user/chat triggers explicitly
