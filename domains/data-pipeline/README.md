# data-pipeline Domain

Airflow data ingestion — ETL from Calendar, Gmail, GitHub into Postgres

## Agents

- [calendar-ingestor](agents/calendar-ingestor/README.md)
- [email-ingestor](agents/email-ingestor/README.md)
- [github-ingestor](agents/github-ingestor/README.md)
- [analytics-processor](agents/analytics-processor/README.md)

## Application

PipelineApp — Airflow DAG status viewer and ingestion logs

## Branch

`domain/data-pipeline` — integration branch for all data-pipeline agents.
Merge path: `agent/data-pipeline/*` → `domain/data-pipeline` → `develop` → `main`
