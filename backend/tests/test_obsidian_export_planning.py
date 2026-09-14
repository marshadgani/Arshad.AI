"""Tests for the outbound Obsidian exporter's planning/decision logic.

These are the modules that decide *what* gets written and *how far* the
watermark may move — export_planner.py, export_repository.advance_watermark,
client.py's RepoVisibility/raise_for_status, config.py's repo validation, and
domains.select_domains. All pure functions (no DB session, no HTTP), so they
run the same way the existing test_obsidian_export_renderers.py suite does:
no fixtures, no mocks beyond SimpleNamespace/httpx.Response construction.

Nothing here exercises export_service.export_notes() end-to-end (that needs
a real AsyncSession + GitHub transport and this repo has no async-DB test
fixtures/conftest for that yet) — these tests instead pin the exact
behaviours export_notes() is documented to rely on, so a regression in any
of them fails loudly before it ever reaches an integration test.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from src.services.obsidian.client import RepoVisibility, VaultFile, raise_for_status
from src.services.obsidian.config import _validated_repo
from src.services.obsidian.domains import EXPORT_DOMAINS, select_domains
from src.services.obsidian.export_planner import build_export_plan, render_rows
from src.services.obsidian.export_repository import advance_watermark
from src.services.obsidian.renderers import RenderedNote
from src.tools.base import ProviderReauthRequired, ToolError


def _domain(name: str = "calendar"):
    return next(d for d in EXPORT_DOMAINS if d.name == name)


def _row(row_id=None, **kwargs):
    defaults = dict(id=row_id or uuid.uuid4(), raw={})
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# export_planner.render_rows — per-record failure isolation + watermark freeze
# ---------------------------------------------------------------------------


class TestRenderRows:
    def test_happy_path_all_rows_rendered_none_failed(self):
        domain = _domain()
        rows = [_row() for _ in range(3)]
        cfg = object()
        renderer = lambda row, cfg: RenderedNote(path=f"p/{row.id}", content="x")
        domain = SimpleNamespace(name="calendar", renderer=renderer)

        result = render_rows(domain, rows, cfg)

        assert len(result.rendered) == 3
        assert result.failures == []
        assert result.frozen_rows == rows

    def test_one_bad_row_is_isolated_others_still_render(self):
        good1, bad, good2 = _row(), _row(), _row()

        def flaky_renderer(row, cfg):
            if row is bad:
                raise ValueError("missing required field 'title'")
            return RenderedNote(path=f"p/{row.id}", content="x")

        domain = SimpleNamespace(name="calendar", renderer=flaky_renderer)
        result = render_rows(domain, [good1, bad, good2], object())

        assert len(result.rendered) == 2
        assert [row for row, _ in result.rendered] == [good1, good2]
        assert len(result.failures) == 1
        assert result.failures[0].row_id == str(bad.id)
        assert "missing required field" in result.failures[0].error

    def test_watermark_freezes_at_first_failure_not_last_good_row(self):
        """REQ: a failed record must be retried next run, not silently
        skipped — so frozen_rows stops at the failure, even though a later
        row renders fine."""
        good1, bad, good2 = _row(), _row(), _row()

        def flaky_renderer(row, cfg):
            if row is bad:
                raise ValueError("boom")
            return RenderedNote(path=f"p/{row.id}", content="x")

        domain = SimpleNamespace(name="calendar", renderer=flaky_renderer)
        result = render_rows(domain, [good1, bad, good2], object())

        # good2 rendered successfully but must NOT be in frozen_rows: the
        # watermark can only safely advance past rows before the failure.
        assert result.frozen_rows == [good1]

    def test_all_rows_fail_frozen_rows_is_empty(self):
        rows = [_row(), _row()]
        domain = SimpleNamespace(
            name="calendar",
            renderer=lambda row, cfg: (_ for _ in ()).throw(ValueError("x")),
        )
        result = render_rows(domain, rows, object())
        assert result.rendered == []
        assert result.frozen_rows == []
        assert len(result.failures) == 2

    def test_empty_rows_no_crash(self):
        domain = SimpleNamespace(name="calendar", renderer=lambda row, cfg: None)
        result = render_rows(domain, [], object())
        assert result.rendered == []
        assert result.failures == []
        assert result.frozen_rows == []

    def test_as_dicts_shape(self):
        bad = _row()
        domain = SimpleNamespace(
            name="calendar",
            renderer=lambda row, cfg: (_ for _ in ()).throw(RuntimeError("bad row")),
        )
        result = render_rows(domain, [bad], object())
        dicts = result.as_dicts()
        assert dicts == [{"row_id": str(bad.id), "error": "bad row"}]


# ---------------------------------------------------------------------------
# export_planner.build_export_plan — hash-gate idempotency
# ---------------------------------------------------------------------------


class TestBuildExportPlan:
    def test_new_note_is_written_and_planned(self):
        row = _row()
        note = RenderedNote(path="Calendar/2026/09/x.md", content="hello")
        files, plans = build_export_plan([(row, note)], existing_by_path={})

        assert files == [VaultFile("Calendar/2026/09/x.md", "hello")]
        assert len(plans) == 1
        assert plans[0].changed is True
        assert plans[0].existing is None
        assert plans[0].row_id == row.id

    def test_unchanged_note_skips_file_write_but_still_plans(self):
        """REQ-143-B1 idempotency: re-running with identical content must
        not re-commit the file, but the plan (and thus watermark advance)
        still happens so the run doesn't get stuck reprocessing it."""
        row = _row()
        note = RenderedNote(path="Calendar/2026/09/x.md", content="hello")
        import hashlib

        existing = SimpleNamespace(content_hash=hashlib.sha256(b"hello").hexdigest())
        files, plans = build_export_plan(
            [(row, note)], existing_by_path={"Calendar/2026/09/x.md": existing}
        )

        assert files == [], "unchanged content must not produce a file to commit"
        assert len(plans) == 1
        assert plans[0].changed is False
        assert plans[0].existing is existing

    def test_changed_content_at_same_path_is_rewritten(self):
        row = _row()
        note = RenderedNote(path="Calendar/2026/09/x.md", content="new content")
        existing = SimpleNamespace(content_hash="deadbeef" * 8)  # stale hash

        files, plans = build_export_plan(
            [(row, note)], existing_by_path={"Calendar/2026/09/x.md": existing}
        )

        assert len(files) == 1
        assert files[0].content == "new content"
        assert plans[0].changed is True
        assert plans[0].existing is existing

    def test_mixed_batch_only_changed_notes_produce_files(self):
        import hashlib

        row1, row2 = _row(), _row()
        unchanged_note = RenderedNote(path="a.md", content="same")
        changed_note = RenderedNote(path="b.md", content="new")
        existing_unchanged = SimpleNamespace(
            content_hash=hashlib.sha256(b"same").hexdigest()
        )
        existing_changed = SimpleNamespace(content_hash="stale")

        files, plans = build_export_plan(
            [(row1, unchanged_note), (row2, changed_note)],
            existing_by_path={"a.md": existing_unchanged, "b.md": existing_changed},
        )

        assert [f.path for f in files] == ["b.md"]
        assert len(plans) == 2


# ---------------------------------------------------------------------------
# export_repository.advance_watermark — never rewind
# ---------------------------------------------------------------------------


class TestAdvanceWatermark:
    def test_first_advance_from_none(self):
        state = SimpleNamespace(last_exported_at=None, last_exported_id=None)
        ts = datetime(2026, 9, 14, tzinfo=timezone.utc)
        rid = uuid.uuid4()

        advance_watermark(state, ts, rid)

        assert state.last_exported_at == ts
        assert state.last_exported_id == rid

    def test_forward_advance_moves_watermark(self):
        old_ts = datetime(2026, 9, 1, tzinfo=timezone.utc)
        state = SimpleNamespace(last_exported_at=old_ts, last_exported_id=uuid.uuid4())
        new_ts = datetime(2026, 9, 14, tzinfo=timezone.utc)
        new_id = uuid.uuid4()

        advance_watermark(state, new_ts, new_id)

        assert state.last_exported_at == new_ts
        assert state.last_exported_id == new_id

    def test_older_timestamp_never_rewinds_watermark(self):
        """A `since` backfill must not push the stored watermark backward —
        otherwise every later scheduled run would re-scan history it had
        already passed."""
        current_ts = datetime(2026, 9, 14, tzinfo=timezone.utc)
        current_id = uuid.uuid4()
        state = SimpleNamespace(
            last_exported_at=current_ts, last_exported_id=current_id
        )
        earlier_ts = datetime(2026, 9, 1, tzinfo=timezone.utc)

        advance_watermark(state, earlier_ts, uuid.uuid4())

        assert state.last_exported_at == current_ts
        assert state.last_exported_id == current_id

    def test_none_new_ts_leaves_watermark_untouched(self):
        state = SimpleNamespace(last_exported_at=None, last_exported_id=None)
        advance_watermark(state, None, None)
        assert state.last_exported_at is None

    def test_equal_timestamp_still_updates_id(self):
        """Same-millisecond rows: the (ts, id) keyset tiebreak must still
        move forward when ts is unchanged but id advances."""
        ts = datetime(2026, 9, 14, tzinfo=timezone.utc)
        old_id = uuid.uuid4()
        new_id = uuid.uuid4()
        state = SimpleNamespace(last_exported_at=ts, last_exported_id=old_id)

        advance_watermark(state, ts, new_id)

        assert state.last_exported_id == new_id

    def test_naive_stored_timestamp_is_treated_as_utc_not_crash(self):
        """as_utc() coerces a naive stored datetime before comparison — a
        pre-migration row without tzinfo must not raise
        TypeError: can't compare offset-naive and offset-aware datetimes."""
        naive_ts = datetime(2026, 9, 1)  # no tzinfo
        state = SimpleNamespace(last_exported_at=naive_ts, last_exported_id=None)
        new_ts = datetime(2026, 9, 14, tzinfo=timezone.utc)

        advance_watermark(state, new_ts, uuid.uuid4())  # must not raise

        assert state.last_exported_at == new_ts


# ---------------------------------------------------------------------------
# client.RepoVisibility — fail-closed security gate (FEAT-141 control)
# ---------------------------------------------------------------------------


class TestRepoVisibilityFailClosed:
    def test_private_is_export_safe(self):
        assert RepoVisibility.PRIVATE.is_export_safe() is True

    def test_public_is_not_export_safe(self):
        assert RepoVisibility.PUBLIC.is_export_safe() is False

    def test_unknown_is_not_export_safe(self):
        """SECURITY: an inconclusive visibility check (network error, non-200,
        missing field) must never be treated as safe — this is the primary
        control preventing PII (calendar/email) from reaching a repo whose
        privacy could not be confirmed."""
        assert RepoVisibility.UNKNOWN.is_export_safe() is False


# ---------------------------------------------------------------------------
# client.raise_for_status — GitHub error -> vault error vocabulary
# ---------------------------------------------------------------------------


def _resp(status_code: int, json_body: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_body or {},
        request=httpx.Request("GET", "https://api.github.com/repos/x/y"),
    )


class TestRaiseForStatus:
    def test_200_does_not_raise(self):
        raise_for_status(_resp(200), "ctx")  # must not raise

    def test_401_raises_provider_reauth_required(self):
        with pytest.raises(ProviderReauthRequired):
            raise_for_status(_resp(401), "ctx")

    def test_404_raises_obsidian_not_found(self):
        with pytest.raises(ToolError) as exc:
            raise_for_status(_resp(404), "fetch_blob(x.md)")
        assert exc.value.code == "obsidian_not_found"

    def test_403_raises_github_forbidden(self):
        with pytest.raises(ToolError) as exc:
            raise_for_status(_resp(403), "ctx")
        assert exc.value.code == "github_forbidden"

    def test_500_raises_generic_api_error(self):
        with pytest.raises(ToolError) as exc:
            raise_for_status(_resp(500), "ctx")
        assert exc.value.code == "obsidian_api_error"

    def test_422_also_raises_generic_api_error(self):
        with pytest.raises(ToolError) as exc:
            raise_for_status(_resp(422), "ctx")
        assert exc.value.code == "obsidian_api_error"


# ---------------------------------------------------------------------------
# domains.select_domains
# ---------------------------------------------------------------------------


class TestSelectDomains:
    def test_none_returns_all_in_registry_order(self):
        result = select_domains(None)
        assert [d.name for d in result] == ["calendar", "email", "github"]

    def test_empty_list_returns_all(self):
        result = select_domains([])
        assert [d.name for d in result] == ["calendar", "email", "github"]

    def test_explicit_subset_filters(self):
        result = select_domains(["github"])
        assert [d.name for d in result] == ["github"]

    def test_caller_order_ignored_registry_order_wins(self):
        result = select_domains(["github", "calendar"])
        assert [d.name for d in result] == ["calendar", "github"]

    def test_unknown_domain_name_silently_dropped(self):
        result = select_domains(["calendar", "bogus"])
        assert [d.name for d in result] == ["calendar"]

    def test_all_unknown_returns_empty(self):
        result = select_domains(["bogus", "also-bogus"])
        assert result == []


# ---------------------------------------------------------------------------
# config._validated_repo — GitHub API path-injection guard
# ---------------------------------------------------------------------------


class TestValidatedRepo:
    def test_valid_owner_repo_accepted(self):
        assert _validated_repo("marshadgani/obsidian-vault", "src") == (
            "marshadgani/obsidian-vault"
        )

    def test_empty_string_rejected(self):
        with pytest.raises(ToolError) as exc:
            _validated_repo("", "src")
        assert exc.value.code == "obsidian_not_configured"

    def test_path_traversal_rejected(self):
        with pytest.raises(ToolError):
            _validated_repo("../../etc/passwd", "src")

    def test_extra_path_segments_rejected(self):
        """A repo string interpolated straight into a GitHub API path must
        never carry a third segment — that could redirect requests to an
        unintended endpoint."""
        with pytest.raises(ToolError):
            _validated_repo("owner/repo/extra", "src")

    def test_bare_owner_without_repo_rejected(self):
        with pytest.raises(ToolError):
            _validated_repo("owner", "src")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ToolError):
            _validated_repo("   ", "src")
