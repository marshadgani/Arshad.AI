"""dag_trigger_queue processing, split by concern.

    drainer.py  — deployment policy (which drainer this environment runs)
                  and the Redis liveness heartbeat.
    worker.py   — the in-process claim-and-run polling loop.

Importers should reach for the narrowest module they need: request
handlers want `drainer` only, and must not pull the polling loop (and
through it the ingestion runner) into the request path.
"""
