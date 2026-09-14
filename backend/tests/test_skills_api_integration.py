"""HTTP-layer integration tests for the AI Ecosystem skills endpoints:

    GET  /api/v1/ai-ecosystem/skills
    POST /api/v1/ai-ecosystem/skills/register

Driven through httpx.AsyncClient over the real FastAPI app against a live
Postgres. Every test carries `@pytest.mark.requires_db`, auto-skipped by
backend/conftest.py unless `RUN_DB_TESTS` is set — `DATABASE_URL` cannot be
the gate because conftest.py always installs a placeholder DSN.

Auth: `get_current_user` is overridden with a stub for the authenticated
tests. The two tests that assert a 401 remove the override for their
duration (see `_no_auth_client`) — otherwise they would silently pass
through the stub and assert nothing.

REQ links: FR-3, FR-4, NFR-1, NFR-2, SC-1, SC-7.
"""

from __future__ import annotations

import contextlib
import json
import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytestmark = pytest.mark.requires_db

SKILLS_URL = "/api/v1/ai-ecosystem/skills"
REGISTER_URL = "/api/v1/ai-ecosystem/skills/register"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeUser:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.email = "test@example.com"


@pytest_asyncio.fixture()
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client with auth bypassed.

    Function-scoped, and it disposes the app's engine pool on the way out.
    `src.models.database.engine` is a module-level singleton whose pooled
    asyncpg connections belong to whichever event loop first opened them;
    pytest-asyncio gives each test a fresh loop, so a connection left in the
    pool by the previous test resurfaces here and fails with
    "got Future attached to a different loop". Disposing per test returns a
    clean pool without any production code needing to know about tests.
    """
    from src.auth.dependencies import get_current_user
    from src.main import app
    from src.models.database import engine

    # Disposed on the way IN as well as out: any other test file that touched
    # AsyncSessionLocal in its own event loop (e.g. the seed wiring test)
    # leaves connections in this shared pool, and inheriting one of those here
    # fails with "got Future attached to a different loop".
    await engine.dispose()
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await engine.dispose()


@contextlib.asynccontextmanager
async def _no_auth_client() -> AsyncGenerator[AsyncClient, None]:
    """A client with the auth override *removed*, so 401s are real."""
    from src.auth.dependencies import get_current_user
    from src.main import app
    from src.models.database import engine

    saved = app.dependency_overrides.pop(get_current_user, None)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c
    finally:
        if saved is not None:
            app.dependency_overrides[get_current_user] = saved
        await engine.dispose()


def _register_body(**overrides) -> dict:
    return {
        "skill_name": f"api-test__{uuid.uuid4().hex[:8]}",
        "display_name": "API Test Skill",
        "description": "Created during API tests.",
        "source_repo": "test-repo",
        "category": "other",
    } | overrides


# ---------------------------------------------------------------------------
# POST /skills/register
# ---------------------------------------------------------------------------


class TestRegisterSkillEndpoint:
    @pytest.mark.asyncio
    async def test_register_new_skill_returns_201(self, app_client):
        """TC-068: Valid body → 201 + {skill_name, action='registered'}."""
        body = _register_body()
        resp = await app_client.post(REGISTER_URL, json=body)
        assert resp.status_code == 201
        data = resp.json()
        assert data["skill_name"] == body["skill_name"]
        assert data["action"] == "registered"

    @pytest.mark.asyncio
    async def test_register_same_skill_again_returns_updated(self, app_client):
        """TC-069: Second POST with the same skill_name → 201 + 'updated'."""
        body = _register_body()
        await app_client.post(REGISTER_URL, json=body)
        resp = await app_client.post(REGISTER_URL, json=body)
        assert resp.status_code == 201
        assert resp.json()["action"] == "updated"

    @pytest.mark.asyncio
    async def test_re_register_updates_fields_without_duplicating(self, app_client):
        """Re-registering refreshes the row rather than creating a second one."""
        body = _register_body(display_name="Before")
        await app_client.post(REGISTER_URL, json=body)
        await app_client.post(REGISTER_URL, json=body | {"display_name": "After"})

        resp = await app_client.get(SKILLS_URL, params={"q": body["skill_name"]})
        assert resp.status_code == 200
        rows = resp.json()["data"]
        assert len(rows) == 1
        assert rows[0]["display_name"] == "After"

    @pytest.mark.asyncio
    async def test_empty_skill_name_rejected_422(self, app_client):
        """TC-070: Empty skill_name → 422 validation error."""
        resp = await app_client.post(REGISTER_URL, json=_register_body(skill_name=""))
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_category_rejected_422(self, app_client):
        """TC-071: Unknown category value → 422."""
        resp = await app_client.post(
            REGISTER_URL, json=_register_body(category="not-a-category")
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_overlong_skill_name_rejected_422(self, app_client):
        """max_length=100 mirrors the DB column — rejected at the boundary,
        not surfaced as a 500 from a failed INSERT."""
        resp = await app_client.post(
            REGISTER_URL, json=_register_body(skill_name="x" * 101)
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self):
        """TC-072: Request without an Authorization header → 401."""
        async with _no_auth_client() as client:
            resp = await client.post(REGISTER_URL, json=_register_body())
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /skills
# ---------------------------------------------------------------------------


class TestListSkillsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200_with_data_and_total(self, app_client):
        """TC-073: GET returns 200 with the {data: [...], total: N} envelope."""
        resp = await app_client.get(SKILLS_URL)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["data"], list)
        assert isinstance(body["total"], int)

    @pytest.mark.asyncio
    async def test_default_limit_is_50(self, app_client):
        """TC-074: Default limit=50 → data length never exceeds 50."""
        resp = await app_client.get(SKILLS_URL)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) <= 50

    @pytest.mark.asyncio
    async def test_limit_1_returns_at_most_1_row(self, app_client):
        """TC-075: limit=1 → at most 1 row; total is still the full count."""
        await app_client.post(REGISTER_URL, json=_register_body())
        resp = await app_client.get(SKILLS_URL, params={"limit": 1})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["total"] >= 1

    @pytest.mark.asyncio
    async def test_limit_0_rejected_422(self, app_client):
        """TC-076: limit=0 is below the ge=1 minimum → 422."""
        resp = await app_client.get(SKILLS_URL, params={"limit": 0})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_101_rejected_422(self, app_client):
        """TC-077: limit=101 exceeds the le=100 maximum → 422."""
        resp = await app_client.get(SKILLS_URL, params={"limit": 101})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_negative_offset_rejected_422(self, app_client):
        """TC-078: offset=-1 → 422 (ge=0 constraint)."""
        resp = await app_client.get(SKILLS_URL, params={"offset": -1})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_offset_beyond_total_returns_empty_data(self, app_client):
        """TC-079: offset > total → data=[] while total keeps the true count."""
        total = (await app_client.get(SKILLS_URL, params={"limit": 1})).json()["total"]
        resp = await app_client.get(SKILLS_URL, params={"offset": total + 9999})
        assert resp.status_code == 200
        assert resp.json()["data"] == []
        assert resp.json()["total"] == total

    @pytest.mark.asyncio
    async def test_category_filter_valid(self, app_client):
        """TC-080: category='development' returns only development rows."""
        await app_client.post(REGISTER_URL, json=_register_body(category="development"))
        resp = await app_client.get(SKILLS_URL, params={"category": "development"})
        assert resp.status_code == 200
        rows = resp.json()["data"]
        assert rows
        assert all(r["category"] == "development" for r in rows)

    @pytest.mark.asyncio
    async def test_category_filter_invalid_rejected_422(self, app_client):
        """TC-081: category='bogus' → 422 (not a valid SkillCategory)."""
        resp = await app_client.get(SKILLS_URL, params={"category": "bogus"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_q_filter_is_case_insensitive(self, app_client):
        """TC-082: q matches skill_name and display_name case-insensitively."""
        suffix = uuid.uuid4().hex[:8]
        skill_name = f"search-test__{suffix}"
        await app_client.post(
            REGISTER_URL,
            json=_register_body(
                skill_name=skill_name, display_name=f"SearchTarget {suffix.upper()}"
            ),
        )
        resp = await app_client.get(SKILLS_URL, params={"q": suffix.upper()})
        assert resp.status_code == 200
        assert skill_name in [r["skill_name"] for r in resp.json()["data"]]

    @pytest.mark.asyncio
    async def test_q_percent_wildcard_treated_as_literal(self, app_client):
        """TC-083: q='100%' finds the literal '%', it does not match every row.

        An unescaped LIKE wildcard here would turn the search box into a
        full-table scan that returns everything.
        """
        suffix = uuid.uuid4().hex[:8]
        await app_client.post(
            REGISTER_URL,
            json=_register_body(display_name=f"Coverage 100% {suffix}"),
        )
        await app_client.post(REGISTER_URL, json=_register_body())

        filtered = (await app_client.get(SKILLS_URL, params={"q": "100%"})).json()
        unfiltered = (await app_client.get(SKILLS_URL, params={"limit": 1})).json()
        assert filtered["total"] >= 1
        assert filtered["total"] < unfiltered["total"]
        for row in filtered["data"]:
            assert "100%" in (row["skill_name"] + row["display_name"])

    @pytest.mark.asyncio
    async def test_q_underscore_treated_as_literal(self, app_client):
        """TC-084: q='a_b_c' matches a literal underscore, not any character."""
        suffix = uuid.uuid4().hex[:8]
        await app_client.post(
            REGISTER_URL, json=_register_body(display_name=f"a_b_c {suffix}")
        )
        await app_client.post(
            REGISTER_URL, json=_register_body(display_name=f"aXbXc {suffix}")
        )
        resp = await app_client.get(SKILLS_URL, params={"q": "a_b_c"})
        assert resp.status_code == 200
        rows = resp.json()["data"]
        assert rows
        for row in rows:
            assert "a_b_c" in (row["skill_name"] + row["display_name"]).lower()

    @pytest.mark.asyncio
    async def test_combined_category_and_q_filters(self, app_client):
        """TC-085: category and q compose — both must hold."""
        unique = uuid.uuid4().hex[:8]
        await app_client.post(
            REGISTER_URL,
            json=_register_body(
                skill_name=f"combo-security__{unique}",
                display_name=f"Security Combo {unique}",
                category="security",
            ),
        )
        # Same search token, different category — must be excluded.
        await app_client.post(
            REGISTER_URL,
            json=_register_body(
                skill_name=f"combo-other__{unique}",
                display_name=f"Other Combo {unique}",
                category="other",
            ),
        )
        resp = await app_client.get(
            SKILLS_URL, params={"category": "security", "q": unique}
        )
        assert resp.status_code == 200
        rows = resp.json()["data"]
        assert [r["skill_name"] for r in rows] == [f"combo-security__{unique}"]

    @pytest.mark.asyncio
    async def test_response_rows_ordered_by_category_then_display_name(
        self, app_client
    ):
        """TC-086: Rows sorted by (category, display_name, skill_name)."""
        for cat in ("security", "development", "other"):
            await app_client.post(REGISTER_URL, json=_register_body(category=cat))
        resp = await app_client.get(SKILLS_URL, params={"limit": 50})
        assert resp.status_code == 200
        keys = [
            (r["category"], r["display_name"], r["skill_name"])
            for r in resp.json()["data"]
        ]
        assert keys == sorted(keys)

    @pytest.mark.asyncio
    async def test_pagination_pages_are_disjoint(self, app_client):
        """TC-087: Offset-based paging returns non-overlapping pages."""
        for _ in range(10):
            await app_client.post(REGISTER_URL, json=_register_body())
        p1 = (await app_client.get(SKILLS_URL, params={"limit": 5, "offset": 0})).json()
        p2 = (await app_client.get(SKILLS_URL, params={"limit": 5, "offset": 5})).json()
        ids1 = {r["skill_name"] for r in p1["data"]}
        ids2 = {r["skill_name"] for r in p2["data"]}
        assert len(ids1) == 5
        assert ids1.isdisjoint(ids2)

    @pytest.mark.asyncio
    async def test_q_max_length_100_enforced(self, app_client):
        """TC-088: q longer than 100 characters → 422."""
        resp = await app_client.get(SKILLS_URL, params={"q": "a" * 101})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self):
        """TC-089: No auth header → 401 (router-level get_current_user)."""
        async with _no_auth_client() as client:
            resp = await client.get(SKILLS_URL)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_skills_tab_not_empty_after_sync(
        self, app_client, tmp_path, monkeypatch
    ):
        """TC-090: After sync_from_manifest runs, GET returns the synced row.

        This is the feature's headline success criterion (SC-1) checked
        through the exact endpoint the Skills tab calls: no manual
        registration step anywhere in the chain.
        """
        import src.skills.manifest as manifest_mod
        from src.models.database import AsyncSessionLocal
        from src.skills.service import sync_from_manifest

        marker = f"populate-test__{uuid.uuid4().hex[:8]}"
        mp = tmp_path / "manifest.json"
        mp.write_text(
            json.dumps(
                [
                    {
                        "skill_name": marker,
                        "display_name": "Populate Test Skill",
                        "description": "Added by TC-090.",
                        "source_repo": "test",
                        "category": "other",
                    }
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(manifest_mod, "MANIFEST_PATH", mp)

        async with AsyncSessionLocal() as session:
            await sync_from_manifest(session)
            await session.commit()

        resp = await app_client.get(SKILLS_URL, params={"q": marker})
        assert resp.status_code == 200
        assert [r["skill_name"] for r in resp.json()["data"]] == [marker]


# ---------------------------------------------------------------------------
# Schema validation — RegisterSkillRequest (no DB needed, but kept alongside
# the endpoint contract it backs)
# ---------------------------------------------------------------------------


class TestRegisterSkillSchema:
    def _make(self, **kwargs):
        from src.schemas.ai_ecosystem import RegisterSkillRequest

        defaults = {
            "skill_name": "schema-test",
            "display_name": "Schema Test",
            "description": "Tests schema validation.",
        }
        return RegisterSkillRequest(**(defaults | kwargs))

    def test_valid_minimal_request(self):
        """TC-091: Minimal valid request accepted; defaults applied."""
        req = self._make()
        assert req.category == "other"
        assert req.source_repo == "unknown"

    def test_all_four_categories_accepted(self):
        """TC-092: All four SkillCategory values are valid."""
        for cat in ("development", "security", "data", "other"):
            assert self._make(category=cat).category == cat

    def test_skill_name_over_100_chars_rejected(self):
        """TC-093: skill_name > 100 characters → ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(skill_name="x" * 101)

    def test_description_over_5000_chars_rejected(self):
        """TC-094: description > 5000 characters → ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(description="x" * 5001)

    def test_empty_display_name_rejected(self):
        """TC-095: Empty display_name → ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(display_name="")
