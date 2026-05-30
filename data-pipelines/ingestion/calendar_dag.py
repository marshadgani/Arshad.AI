"""Airflow DAG: arshad_ai_calendar_ingestor.

Phase F locked decisions:
- on-demand only (no @daily schedule); the agent inserts a queue row
  and the sensor picks it up
- shared ingestion logic via backend/src/services/ingestion/runner.py
- DB queue at dag_trigger_queue with status pending|picked|completed|failed

The DAG runs three tasks:
  1. claim_one  — SELECT...FOR UPDATE SKIP LOCKED LIMIT 1 from queue
                  WHERE dag_id='calendar_ingestor' AND status='pending'
                  UPDATE status='picked'
  2. run_ingest — call ingestion_runner.run synchronously
  3. mark_done  — UPDATE status='completed' (or 'failed' on exception)

The sensor uses a short poke interval so newly-inserted rows are picked
up within ~5s.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from _ingestion_helpers import claim_one, mark_done, run_ingest_for_row
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

DAG_ID = "calendar_ingestor"

default_args = {
    "owner": "arshad-ai",
    "retries": 0,  # ingestion_runner handles its own retries via the queue's attempt counter
    "retry_delay": timedelta(minutes=1),
    "email_on_failure": False,
}


with DAG(
    dag_id=f"arshad_ai_{DAG_ID}",
    description="On-demand Calendar ingestion — picks up dag_trigger_queue rows",
    schedule=None,  # locked: on-demand only
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=4,
    default_args=default_args,
    tags=["arshad-ai", "ingestion", "calendar"],
):
    sensor = PythonSensor(
        task_id="claim_pending_run",
        python_callable=claim_one,
        op_kwargs={"dag_id": DAG_ID},
        poke_interval=5,
        timeout=60 * 60,
        mode="reschedule",
    )

    ingest = PythonOperator(
        task_id="run_ingest",
        python_callable=run_ingest_for_row,
        op_kwargs={"dag_id": DAG_ID},
    )

    finalize = PythonOperator(
        task_id="mark_done",
        python_callable=mark_done,
        op_kwargs={"dag_id": DAG_ID},
        trigger_rule="all_done",  # run even if ingest fails so we record the failure
    )

    sensor >> ingest >> finalize
