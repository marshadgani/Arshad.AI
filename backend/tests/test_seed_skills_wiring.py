"""Regression guards for the automated-invocation feature itself.

The BPDD requirement for this feature is not "does sync_from_manifest work"
(that is already covered by test_skills_service_integration.py) — it is
"is sync_from_manifest actually *invoked automatically* on every deploy,
with no manual step". That wiring lives in exactly two places:

  1. `backend/scripts/seed_from_mock.py::seed()` calls
     `sync_from_manifest(s)` and commits it.
  2. `backend/Dockerfile`'s CMD runs
     `python -m scripts.seed_from_mock` before `uvicorn` starts, on every
     container boot (Render has no separate migration/seed step for the
     web service).

Neither of those two facts was covered by any existing test. A future edit
that quietly drops the `sync_from_manifest(s)` call from `seed()`, or drops
`scripts.seed_from_mock` from the Dockerfile CMD, would pass every existing
test in this repo (they all exercise `sync_from_manifest` directly, in
isolation) while silently reintroducing the exact bug this feature fixes —
the Skills tab going empty again with no manual step to notice it.

REQ links: FR-1 ("automated invocation... so the Skills tab reflects
reality without manual intervention"), SC-1.

The DB-dependent tests (TC-W03, TC-W04) carry `@pytest.mark.requires_db`. That marker
is auto-skipped by backend/conftest.py unless `RUN_DB_TESTS` is set.
`DATABASE_URL` deliberately is NOT the gate: conftest.py always installs a
placeholder DSN via `os.environ.setdefault`, so a DATABASE_URL-based guard
never fires and the tests would attempt a real connection to localhost:5432
on every machine without Postgres.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


# ---------------------------------------------------------------------------
# Static wiring guards — no DB required, run in every CI stage
# ---------------------------------------------------------------------------


class TestDeployWiringStatic:
    def test_dockerfile_cmd_runs_seed_from_mock_before_uvicorn(self):
        """TC-W01: The Dockerfile CMD that Render executes on every boot must
        run `scripts.seed_from_mock` before starting uvicorn — this is the
        actual "automated invocation" the feature requires. Regression guard
        for someone trimming the CMD (e.g. to speed up boot) and silently
        dropping the only place the skills sync happens for the deployed
        service.
        """
        dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
        cmd_match = re.search(r"^CMD\s*\[(.*)\]", dockerfile, re.MULTILINE | re.DOTALL)
        assert cmd_match, "Dockerfile has no CMD instruction"
        cmd_line = cmd_match.group(1)
        assert "scripts.seed_from_mock" in cmd_line, (
            "Dockerfile CMD no longer runs scripts.seed_from_mock — the "
            "skills manifest sync will never run on Render deploys"
        )
        seed_pos = cmd_line.find("scripts.seed_from_mock")
        uvicorn_pos = cmd_line.find("uvicorn")
        assert 0 <= seed_pos < uvicorn_pos, (
            "seed_from_mock must run before uvicorn starts serving traffic"
        )

    def test_seed_from_mock_calls_sync_from_manifest_and_commits(self):
        """TC-W02: `seed()` must import and call `sync_from_manifest`, and
        must commit immediately after — as its own docstring documents
        ("Own commit so a skills-sync failure can never roll back the agent
        sync."). A static source check because the DB-backed test below is
        skipped in environments without RUN_DB_TESTS, and this wiring is
        exactly what regressed in the original bug report.
        """
        source = (BACKEND_ROOT / "scripts" / "seed_from_mock.py").read_text(
            encoding="utf-8"
        )
        assert "from src.skills.service import sync_from_manifest" in source
        assert re.search(r"skill_stats\s*=\s*await sync_from_manifest\(s\)", source), (
            "seed() no longer calls sync_from_manifest — the Skills tab "
            "will not stay in sync with .claude/skills/ on future deploys"
        )
        # The call must be followed (not just preceded) by a commit, or a
        # failed request after this point could roll the sync back away.
        call_idx = source.index("skill_stats = await sync_from_manifest(s)")
        tail = source[call_idx : call_idx + 200]
        assert "await s.commit()" in tail, (
            "sync_from_manifest() result is never committed in seed()"
        )


# ---------------------------------------------------------------------------
# Guard: nothing earlier in seed() may crash before the skills sync
# ---------------------------------------------------------------------------


class TestSeedReachesTheSkillsSync:
    """The skills sync is the *last* thing seed() does.

    Anything that raises earlier in the same function silently defeats this
    entire feature: the Dockerfile CMD swallows the failure with
    `|| echo '[startup] seed skipped/failed — non-fatal'`, uvicorn starts
    normally, and `skill_registry` is never populated. That is exactly what
    happened when FEAT-119 deleted the "kpis" key from the shopify domain
    while the seeding loop still did `d["kpis"]` — every deploy raised
    KeyError and the Skills tab stayed empty.

    These tests are DB-free on purpose. The end-to-end version below only
    runs with RUN_DB_TESTS, so without them a repeat of that regression
    would sail through CI.
    """

    OPTIONAL_DOMAIN_COLLECTIONS = ("kpis", "applications", "agents", "feed")

    def test_domain_collections_are_read_with_get_not_subscript(self):
        """TC-W05: The per-domain collections must be optional.

        A domain legitimately has no KPIs (shopify sources them live from
        GET /api/v1/shopify/dashboard). Reading them with `d["kpis"]` turns
        that legitimate state into a startup crash.
        """
        source = (BACKEND_ROOT / "scripts" / "seed_from_mock.py").read_text(
            encoding="utf-8"
        )
        for key in self.OPTIONAL_DOMAIN_COLLECTIONS:
            assert f'd["{key}"]' not in source, (
                f'seed() subscripts d["{key}"] — a domain without that key '
                "raises KeyError and the skills sync below never runs. "
                f'Use d.get("{key}", ()) instead.'
            )

    def test_every_seeded_domain_builds_without_raising(self):
        """TC-W06: Build the ORM rows for every DOMAINS entry, as seed() does.

        No database: SQLAlchemy models are instantiated, not persisted. This
        catches both the missing-key crash and a mock row carrying a column
        the model does not define.
        """
        import src.models.domain as dom
        from scripts.seed_from_mock import DOMAINS

        for d in DOMAINS:
            dom.Domain(
                slug=d["slug"],
                title=d["title"],
                emoji=d["emoji"],
                tagline=d["tagline"],
            )
            for ord_, kpi in enumerate(d.get("kpis", ())):
                dom.DomainKPI(domain_slug=d["slug"], ord=ord_, **kpi)
            for app in d.get("applications", ()):
                dom.DomainApplication(domain_slug=d["slug"], **app)
            for agent in d.get("agents", ()):
                dom.DomainAgent(domain_slug=d["slug"], **agent)
            for row in d.get("feed", ()):
                dom.DomainFeedRow(domain_slug=d["slug"], **row)

    def test_skills_sync_is_the_last_step_of_seed(self):
        """TC-W07: Documents the ordering the two tests above depend on —
        if the sync is ever moved, the "nothing may crash before it" framing
        needs revisiting."""
        source = (BACKEND_ROOT / "scripts" / "seed_from_mock.py").read_text(
            encoding="utf-8"
        )
        assert source.index("sync_agents_from_disk(s)") < source.index(
            "sync_from_manifest(s)"
        )


# ---------------------------------------------------------------------------
# End-to-end DB guard — proves the whole chain actually populates the table
# ---------------------------------------------------------------------------


class TestSeedFromMockEndToEnd:
    @pytest.mark.requires_db
    @pytest.mark.asyncio
    async def test_seed_populates_skill_registry_from_manifest(
        self, monkeypatch, tmp_path
    ):
        """TC-W03: Calling the real `seed()` entrypoint (the function the
        Dockerfile CMD invokes) populates `skill_registry` from the
        manifest, with no manual registration step. This is the actual
        success criterion (SC-1) exercised end-to-end rather than through
        `sync_from_manifest` called directly by a test.

        Requires a live Postgres: gated by `@pytest.mark.requires_db` / RUN_DB_TESTS.
        """
        import src.skills.manifest as manifest_mod
        from scripts.seed_from_mock import seed
        from src.models.database import AsyncSessionLocal, engine
        from src.skills import repository

        marker = f"wiring-e2e__{uuid.uuid4().hex[:8]}"
        rows = [
            {
                "skill_name": marker,
                "display_name": "Wiring E2E Skill",
                "description": "Populated purely by calling seed().",
                "source_repo": "test-repo",
                "category": "other",
            }
        ]
        mp = tmp_path / "manifest.json"
        mp.write_text(json.dumps(rows) + "\n", encoding="utf-8")
        monkeypatch.setattr(manifest_mod, "MANIFEST_PATH", mp)

        try:
            await seed()

            async with AsyncSessionLocal() as session:
                stored = await repository.get_by_name(session, marker)
        finally:
            # AsyncSessionLocal's engine pool is a module-level singleton
            # shared with every other test file. Connections opened on this
            # test's event loop must not outlive it, or the next test to use
            # the pool fails with "Future attached to a different loop".
            await engine.dispose()

        assert stored is not None, (
            "seed() ran but skill_registry has no row for the manifest "
            "entry — the automated invocation is not actually wired up"
        )
        assert stored.display_name == "Wiring E2E Skill"

    @pytest.mark.requires_db
    def test_cli_entrypoint_reports_skills_synced(self, tmp_path, monkeypatch):
        """TC-W04: `python -m scripts.seed_from_mock` — the exact command in
        the Dockerfile CMD — exits 0 and its own completion message mentions
        the skill sync count. Runs the literal command a fresh container
        executes, not a Python-level call into the module.

        Requires a live Postgres: gated by `@pytest.mark.requires_db` / RUN_DB_TESTS.
        """
        import os

        env = dict(os.environ)
        result = subprocess.run(
            [sys.executable, "-m", "scripts.seed_from_mock"],
            cwd=str(BACKEND_ROOT),
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert "skills synced" in result.stdout, (
            f"seed_from_mock did not report a skills sync — stdout was: "
            f"{result.stdout!r}"
        )
