"""FEAT-141 — Obsidian Ontology Layer.

Push-sync pipeline: Postgres (ingested_* tables) -> vault entity notes,
organised as a linked knowledge graph (entities + [[wikilinks]] + MOCs)
rather than flat per-record notes.

Module map — each pass is one module, and the dependency direction is
strictly downward:

    pipeline.py      wiring + transaction boundaries (the only entry point)
      extract/       Pass 0 — per-domain DB readers + registry
      resolve.py     Pass 1 — stable identity, upsert, rename detection
      compose.py     Pass 2 — which rows become which notes
        render.py    Pass 2 — one row -> byte-deterministic note text
      diff.py        Pass 3 — local blob-SHA comparison (no network)
      vault_writer.py Pass 4 — the only GitHub-aware module
      runlog.py      Pass 5 — OntologySyncRun audit lifecycle

    paths.py         vault path policy        (pure)
    catalogue.py     MOC / index identities   (pure)
    identity.py      person identity          (pure)
    config.py        run tunables             (pure)
    models.py        shared dataclasses       (pure)

Everything marked pure imports neither SQLAlchemy nor httpx and is
testable with plain values.

This module stays import-free on purpose: ``pipeline`` pulls in Redis and
httpx clients, so importing it eagerly here would make a pure-module test
(``from ...ontology.paths import note_path``) require a configured
environment. The runner imports ``ontology.pipeline`` directly instead.
"""
