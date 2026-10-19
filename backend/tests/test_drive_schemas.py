"""Unit tests for src.schemas.drive Pydantic models.

Verifies the HTTP boundary contract: correct field names, types,
defaults, and that no private/email fields leak through.
"""

from __future__ import annotations

from src.schemas.drive import (
    DriveAuditResponse,
    DriveFile,
    KnowledgeSuggestionsResponse,
)


class TestDriveFile:
    def test_serialises_required_fields(self):
        f = DriveFile(
            id="file-1",
            name="doc.pdf",
            web_view_link="https://drive.google.com/x",
            modified_time="2026-01-01T00:00:00Z",
            permissions_visible=True,
        )
        d = f.model_dump()
        assert d["id"] == "file-1"
        assert d["name"] == "doc.pdf"
        assert d["web_view_link"] == "https://drive.google.com/x"
        assert d["modified_time"] == "2026-01-01T00:00:00Z"
        assert d["permissions_visible"] is True

    def test_anyone_with_link_defaults_to_none(self):
        f = DriveFile(
            id="f",
            name="n",
            web_view_link="",
            modified_time="",
            permissions_visible=False,
        )
        assert f.anyone_with_link is None
        assert f.stale_sharing is None

    def test_no_email_or_permission_detail_fields(self):
        f = DriveFile(
            id="f",
            name="n",
            web_view_link="",
            modified_time="",
            permissions_visible=True,
            anyone_with_link=True,
            stale_sharing=False,
        )
        d = f.model_dump()
        assert "emailAddress" not in d
        assert "email" not in d
        assert "permissions" not in d


class TestDriveAuditResponse:
    def test_serialises_all_six_keys(self):
        resp = DriveAuditResponse(
            data=[],
            total=0,
            connected=False,
            needs_reauth=False,
            truncated=False,
            partial_failures=[],
        )
        d = resp.model_dump()
        for key in (
            "data",
            "total",
            "connected",
            "needs_reauth",
            "truncated",
            "partial_failures",
        ):
            assert key in d

    def test_not_connected_example_matches_spec(self):
        """FN-104: default not-connected shape."""
        resp = DriveAuditResponse(
            data=[],
            total=0,
            connected=False,
            needs_reauth=False,
            truncated=False,
            partial_failures=[],
        )
        assert resp.connected is False
        assert resp.needs_reauth is False
        assert resp.data == []
        assert resp.total == 0

    def test_needs_reauth_example(self):
        resp = DriveAuditResponse(
            data=[],
            total=0,
            connected=True,
            needs_reauth=True,
            truncated=False,
            partial_failures=["google_drive: needs_reauth"],
        )
        assert resp.connected is True
        assert resp.needs_reauth is True


class TestKnowledgeSuggestionsResponse:
    def test_data_is_list_of_str(self):
        """FN-106: frontend contract — data must be list[str], not nested."""
        resp = KnowledgeSuggestionsResponse(
            data=["a.pdf", "b.docx"],
            total=2,
            connected=True,
            needs_reauth=False,
            truncated=False,
            partial_failures=[],
        )
        d = resp.model_dump()
        assert isinstance(d["data"], list)
        assert all(isinstance(x, str) for x in d["data"])

    def test_total_is_top_level_int(self):
        resp = KnowledgeSuggestionsResponse(
            data=["x"],
            total=1,
            connected=True,
            needs_reauth=False,
            truncated=False,
            partial_failures=[],
        )
        d = resp.model_dump()
        assert isinstance(d["total"], int)
        # total is NOT nested inside data
        assert not isinstance(d["data"], dict)

    def test_additive_keys_present(self):
        """FN-106: new flags are additive top-level keys."""
        resp = KnowledgeSuggestionsResponse(
            data=[],
            total=0,
            connected=False,
            needs_reauth=False,
            truncated=False,
            partial_failures=[],
        )
        d = resp.model_dump()
        for key in ("connected", "needs_reauth", "truncated", "partial_failures"):
            assert key in d
