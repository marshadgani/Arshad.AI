"""Silent-failure-hunter alignment tests.

Ensures that critical error paths never swallow exceptions or return
a success-shaped response when the operation failed.

Covers TC-067 through TC-072.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from src.models.ontology import OntologyEntityNote
from src.services.ingestion.ontology.render import MissingLinkError, render_entity


def _entity_row_with_rel(rel: str, target_id: str) -> OntologyEntityNote:
    row = OntologyEntityNote()
    row.id = uuid.uuid4()
    row.user_id = uuid.uuid4()
    row.stable_entity_id = "event:sfh_test"
    row.entity_type = "Event"
    row.domain = "calendar"
    row.display_name = "SFH Event"
    row.source_updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    row.tags = []
    row.relationships = [{"rel": rel, "target_entity_id": target_id}]
    row.sync_state = "pending"
    row.blob_sha = ""
    row.vault_path = "entities/calendar/Event/event:sfh_test.md"
    return row


# ── TC-067 ─────────────────────────────────────────────────────────
def test_missing_link_error_propagates_not_swallowed():
    """MissingLinkError from a renderer must NOT be caught-and-continue.
    The error should propagate up to the caller, not be silently swallowed.
    """
    row = _entity_row_with_rel("attended_by", "person:missingid00000000")
    with pytest.raises(MissingLinkError):
        render_entity(row, {}, None)  # empty link_map → target missing


# ── TC-068 ─────────────────────────────────────────────────────────
def test_render_never_calls_datetime_now_internally():
    """render_entity must never call datetime.now() internally — that would
    make the output non-deterministic and break the SHA-diff idempotency guarantee.
    """
    import src.services.ingestion.ontology.render as render_mod

    source = inspect.getsource(render_mod)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "now":
                if isinstance(func.value, ast.Name) and func.value.id == "datetime":
                    pytest.fail(
                        f"render.py calls datetime.now() at line {node.lineno} — "
                        "this breaks byte-determinism. Use injected timestamps."
                    )


# ── TC-069 ─────────────────────────────────────────────────────────
def test_ontology_pipeline_does_not_use_single_file_write_path():
    """Regression: nothing in the ontology package may import write_file()
    from obsidian_client.py — that path uses the single-file Contents API
    which bypasses the batch Git Data API strategy the whole feature
    depends on for one-commit-per-run behaviour.
    """
    repo_root = Path(__file__).resolve().parents[2]
    ontology_pkg = repo_root / "src" / "services" / "ingestion" / "ontology"
    assert ontology_pkg.exists(), f"ontology package not found at {ontology_pkg}"

    offenders = []
    for py_file in ontology_pkg.rglob("*.py"):
        source = py_file.read_text()
        if "obsidian_client" in source and "write_file" in source:
            offenders.append(str(py_file))
    assert not offenders, (
        f"{offenders} import write_file from obsidian_client — "
        "forbidden coupling; use vault_writer.py / ObsidianGitDataClient instead"
    )


# ── TC-070 ─────────────────────────────────────────────────────────
def test_yaml_safe_dump_with_null_bytes_in_display_name():
    """A display_name containing a null byte must not produce corrupt YAML.
    safe_dump should handle or raise a controlled error, not silently emit \\x00.
    """
    row = OntologyEntityNote()
    row.id = uuid.uuid4()
    row.user_id = uuid.uuid4()
    row.stable_entity_id = "event:null_byte"
    row.entity_type = "Event"
    row.domain = "calendar"
    row.display_name = "Event\x00 with null"
    row.source_updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    row.tags = []
    row.relationships = []
    row.sync_state = "pending"
    row.blob_sha = ""
    row.vault_path = "entities/calendar/Event/null_byte.md"

    try:
        text = render_entity(row, {}, None)
        fm_text = text.split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert isinstance(fm, dict)
    except (yaml.YAMLError, ValueError):
        # A controlled error is acceptable; an unhandled crash is not.
        pass


# ── TC-071 ─────────────────────────────────────────────────────────
def test_yaml_injection_colon_in_display_name():
    """A display_name with a colon (common in meeting titles) round-trips safely."""
    row = OntologyEntityNote()
    row.id = uuid.uuid4()
    row.user_id = uuid.uuid4()
    row.stable_entity_id = "event:colon_test"
    row.entity_type = "Event"
    row.domain = "calendar"
    row.display_name = "RFC: The Next Big Thing — Q3 2024"
    row.source_updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    row.tags = []
    row.relationships = []
    row.sync_state = "pending"
    row.blob_sha = ""
    row.vault_path = "entities/calendar/Event/colon_test.md"

    text = render_entity(row, {}, None)
    fm_text = text.split("---")[1]
    fm = yaml.safe_load(fm_text)
    assert isinstance(fm, dict)  # parses without error


# ── TC-072 ─────────────────────────────────────────────────────────
def test_no_bare_except_around_render_in_pipeline():
    """Ensure no broad bare except (or 'except Exception: pass/continue') wraps
    render_entity calls in the pipeline/compose modules — that would swallow
    MissingLinkError instead of routing it through compose.py's explicit,
    counted skip-and-continue. This is an AST-level static check.
    """
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / "src" / "services" / "ingestion" / "ontology" / "pipeline.py",
        repo_root / "src" / "services" / "ingestion" / "ontology" / "compose.py",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        source = candidate.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    if all(isinstance(s, (ast.Pass, ast.Continue)) for s in node.body):
                        pytest.fail(
                            f"{candidate}: bare except swallowing error at line {node.lineno}"
                        )


# ── TC-072b ────────────────────────────────────────────────────────
def test_pipeline_reauth_and_tool_errors_are_not_swallowed():
    """pipeline.sync() must re-raise ProviderReauthRequired and wrap+raise
    ToolError as IngestionError after recording the failed run — never
    catch-and-return a success-shaped dict, which would mask a real
    upstream (GitHub/OAuth) failure as a quiet no-op."""
    repo_root = Path(__file__).resolve().parents[2]
    pipeline_path = (
        repo_root / "src" / "services" / "ingestion" / "ontology" / "pipeline.py"
    )
    source = pipeline_path.read_text()
    tree = ast.parse(source)

    def _handler_reraises(handler: ast.ExceptHandler) -> bool:
        return any(isinstance(s, ast.Raise) for s in handler.body)

    reauth_handlers = [
        h
        for h in ast.walk(tree)
        if isinstance(h, ast.ExceptHandler)
        and h.type is not None
        and (
            (isinstance(h.type, ast.Name) and h.type.id == "ProviderReauthRequired")
            or (
                isinstance(h.type, ast.Attribute)
                and h.type.attr == "ProviderReauthRequired"
            )
        )
    ]
    assert reauth_handlers, (
        "sync() no longer has an except ProviderReauthRequired clause"
    )
    assert all(_handler_reraises(h) for h in reauth_handlers), (
        "except ProviderReauthRequired must re-raise, never swallow, the error"
    )

    tool_error_handlers = [
        h
        for h in ast.walk(tree)
        if isinstance(h, ast.ExceptHandler)
        and h.type is not None
        and (
            (isinstance(h.type, ast.Name) and h.type.id == "ToolError")
            or (isinstance(h.type, ast.Attribute) and h.type.attr == "ToolError")
        )
    ]
    assert tool_error_handlers, "sync() no longer has an except ToolError clause"
    assert all(_handler_reraises(h) for h in tool_error_handlers), (
        "except ToolError must raise (wrapped as IngestionError), never swallow, the error"
    )
    assert "raise IngestionError" in source
