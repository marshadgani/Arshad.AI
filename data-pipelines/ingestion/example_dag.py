from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "arshad-ai",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}


def ingest_data(**context) -> None:
    """Stub ingestion task — replace with real source logic."""
    execution_date = context["execution_date"]
    print(f"[arshad_ai_data_ingestion] Running for execution date: {execution_date}")
    # TODO: pull data from source, validate, write to postgres


with DAG(
    dag_id="arshad_ai_data_ingestion",
    description="Daily ingestion pipeline for Arshad.AI personal data sources",
    schedule="@daily",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["arshad-ai", "ingestion"],
) as dag:
    ingest = PythonOperator(
        task_id="ingest_data",
        python_callable=ingest_data,
    )
