"""Airflow DAG: arshad_ai_analytics_processor.

Aggregates ingested_* tables into ingested_analytics_summary. Same shape
as the 3 ingestor DAGs — only dag_id differs. Typically chained AFTER
the ingestor DAGs by the chat-orchestrator (Phase B): ingest first, then
recompute analytics.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from _ingestion_helpers import claim_one, mark_done, run_ingest_for_row
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

DAG_ID = "analytics_processor"

default_args = {
    "owner": "arshad-ai",
    "retries": 0,
    "retry_delay": timedelta(minutes=1),
    "email_on_failure": False,
}


with DAG(
    dag_id=f"arshad_ai_{DAG_ID}",
    description="On-demand analytics aggregation — picks up dag_trigger_queue rows",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=4,
    default_args=default_args,
    tags=["arshad-ai", "ingestion", "analytics"],
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
        trigger_rule="all_done",
    )

    sensor >> ingest >> finalize
