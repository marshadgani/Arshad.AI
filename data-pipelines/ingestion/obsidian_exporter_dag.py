"""Airflow DAG: arshad_ai_obsidian_exporter.

Local-dev-only. On-demand, mirroring calendar_dag.py exactly: no @daily
schedule — prod (Render) drives this dag_id through
backend/src/services/queue_worker.py, which polls dag_trigger_queue the
same way this sensor does. Triggered by POST /api/v1/obsidian/export
inserting a dag_trigger_queue row with dag_id='obsidian_exporter'.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from _ingestion_helpers import claim_one, mark_done, run_ingest_for_row
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

DAG_ID = "obsidian_exporter"

default_args = {
    "owner": "arshad-ai",
    "retries": 0,  # obsidian_export.py handles its own per-record failure isolation
    "retry_delay": timedelta(minutes=1),
    "email_on_failure": False,
}


with DAG(
    dag_id=f"arshad_ai_{DAG_ID}",
    description="On-demand Obsidian vault export — picks up dag_trigger_queue rows",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=4,
    default_args=default_args,
    tags=["arshad-ai", "obsidian"],
):
    sensor = PythonSensor(
        task_id="claim_pending_run",
        python_callable=claim_one,
        op_kwargs={"dag_id": DAG_ID},
        poke_interval=5,
        timeout=60 * 60,
        mode="reschedule",
    )

    export = PythonOperator(
        task_id="run_export",
        python_callable=run_ingest_for_row,
        op_kwargs={"dag_id": DAG_ID},
    )

    finalize = PythonOperator(
        task_id="mark_done",
        python_callable=mark_done,
        op_kwargs={"dag_id": DAG_ID},
        trigger_rule="all_done",
    )

    sensor >> export >> finalize
