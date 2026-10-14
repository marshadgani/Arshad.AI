"""FEAT-179 infrastructure findings: pure _infrastructure_findings unit tests."""

from datetime import datetime, timedelta, timezone

from src.services.shopify.trip_feasibility import (
    INFRA_STALENESS_HOURS,
    _infrastructure_findings,
    _snapshot_flags,
)

AS_OF = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
SYNCED_NOW = AS_OF.isoformat()
SYNCED_STALE = (AS_OF - timedelta(hours=INFRA_STALENESS_HOURS + 1)).isoformat()


def _render_cfg(services=None, synced_at=SYNCED_NOW, truncated=False):
    return {
        "services": services if services is not None else [],
        "synced_at": synced_at,
        "services_truncated": truncated,
    }


def _supabase_cfg(projects=None, synced_at=SYNCED_NOW):
    return {
        "projects": projects if projects is not None else [],
        "synced_at": synced_at,
    }


# ── TC-019: no integrations connected → all flags false, empty conflicts ──


def test_no_infra_all_disconnected():
    conflicts, flags, unreadable = _infrastructure_findings(
        None, None, None, None, as_of=AS_OF
    )
    assert conflicts == []
    assert not flags["render_connected"]
    assert not flags["supabase_connected"]
    assert unreadable == []


# ── TC-020: render only connected, healthy service ────────────────────────


def test_render_healthy_no_conflict():
    cfg = _render_cfg(
        [{"name": "api", "suspended": "not_suspended", "latest_deploy_status": "live"}]
    )
    conflicts, flags, unreadable = _infrastructure_findings(
        cfg, None, "connected", None, as_of=AS_OF
    )
    assert conflicts == []
    assert flags["render_connected"]
    assert unreadable == []


# ── TC-021: service with no deploys (deploy=None) is NOT unreadable ──────


def test_render_no_deploys_not_unreadable():
    """A brand-new not_suspended service with no deploys is healthy, not unreadable."""
    cfg = _render_cfg(
        [
            {
                "name": "new-svc",
                "suspended": "not_suspended",
                "latest_deploy_status": None,
            }
        ]
    )
    conflicts, flags, unreadable = _infrastructure_findings(
        cfg, None, "connected", None, as_of=AS_OF
    )
    assert conflicts == []
    assert "render_health" not in unreadable


# ── TC-022: suspended service → conflict ──────────────────────────────────


def test_render_suspended_yields_conflict():
    cfg = _render_cfg(
        [{"name": "api", "suspended": "suspended", "latest_deploy_status": "live"}]
    )
    conflicts, flags, unreadable = _infrastructure_findings(
        cfg, None, "connected", None, as_of=AS_OF
    )
    assert len(conflicts) == 1
    assert conflicts[0].type == "infrastructure"
    assert conflicts[0].provider == "render"
    assert conflicts[0].infra_state == "suspended"


# ── TC-023: failed deploy → conflict ─────────────────────────────────────


def test_render_failed_deploy_yields_conflict():
    cfg = _render_cfg(
        [
            {
                "name": "api",
                "suspended": "not_suspended",
                "latest_deploy_status": "build_failed",
            }
        ]
    )
    conflicts, flags, unreadable = _infrastructure_findings(
        cfg, None, "connected", None, as_of=AS_OF
    )
    assert len(conflicts) == 1
    assert conflicts[0].infra_state == "build_failed"


# ── TC-024: unknown suspended state → render_health unreadable ───────────


def test_render_unknown_suspended_is_unreadable():
    cfg = _render_cfg(
        [{"name": "api", "suspended": "unknown_state", "latest_deploy_status": "live"}]
    )
    conflicts, flags, unreadable = _infrastructure_findings(
        cfg, None, "connected", None, as_of=AS_OF
    )
    assert "render_health" in unreadable


# ── TC-025: supabase INACTIVE project → conflict ─────────────────────────


def test_supabase_inactive_yields_conflict():
    cfg = _supabase_cfg([{"ref": "a", "name": "mydb", "status": "INACTIVE"}])
    conflicts, flags, unreadable = _infrastructure_findings(
        None, cfg, None, "connected", as_of=AS_OF
    )
    assert len(conflicts) == 1
    assert conflicts[0].provider == "supabase"
    assert conflicts[0].infra_state == "INACTIVE"


# ── TC-026: supabase ACTIVE_HEALTHY → no conflict ────────────────────────


def test_supabase_healthy_no_conflict():
    cfg = _supabase_cfg([{"ref": "a", "name": "mydb", "status": "ACTIVE_HEALTHY"}])
    conflicts, flags, unreadable = _infrastructure_findings(
        None, cfg, None, "connected", as_of=AS_OF
    )
    assert conflicts == []
    assert "supabase_health" not in unreadable


# ── TC-027: supabase project with no status → supabase_health unreadable ─


def test_supabase_missing_status_is_unreadable():
    cfg = _supabase_cfg([{"ref": "a", "name": "mydb"}])
    conflicts, flags, unreadable = _infrastructure_findings(
        None, cfg, None, "connected", as_of=AS_OF
    )
    assert "supabase_health" in unreadable


# ── TC-028: stale render snapshot → render_stale=True ────────────────────


def test_render_stale_flag():
    cfg = _render_cfg(synced_at=SYNCED_STALE)
    conflicts, flags, unreadable = _infrastructure_findings(
        cfg, None, "connected", None, as_of=AS_OF
    )
    assert flags["render_stale"]


# ── TC-029: never-synced render snapshot → render_needs_sync=True ─────────


def test_render_never_synced():
    cfg = {"services": []}
    conflicts, flags, unreadable = _infrastructure_findings(
        cfg, None, "connected", None, as_of=AS_OF
    )
    assert flags["render_needs_sync"]


# ── TC-030: sync_error flag from status field ──────────────────────────────


def test_render_sync_error_flag():
    cfg = _render_cfg()
    conflicts, flags, unreadable = _infrastructure_findings(
        cfg, None, "error", None, as_of=AS_OF
    )
    assert flags["render_sync_error"]


# ── TC-031: truncated flag ─────────────────────────────────────────────────


def test_render_truncated_flag():
    cfg = _render_cfg(truncated=True)
    conflicts, flags, unreadable = _infrastructure_findings(
        cfg, None, "connected", None, as_of=AS_OF
    )
    assert flags["render_truncated"]


# ── TC-032: non-list services → render_health unreadable ─────────────────


def test_render_non_list_services_unreadable():
    cfg = {"services": "not-a-list", "synced_at": SYNCED_NOW}
    conflicts, flags, unreadable = _infrastructure_findings(
        cfg, None, "connected", None, as_of=AS_OF
    )
    assert "render_health" in unreadable


# ── TC-033: non-dict service entry → render_health unreadable ────────────


def test_render_non_dict_service_entry_unreadable():
    cfg = _render_cfg(["not-a-dict"])
    conflicts, flags, unreadable = _infrastructure_findings(
        cfg, None, "connected", None, as_of=AS_OF
    )
    assert "render_health" in unreadable


# ── TC-034: both render and supabase with mixed health ───────────────────


def test_both_providers_mixed_health():
    r_cfg = _render_cfg(
        [{"name": "api", "suspended": "suspended", "latest_deploy_status": "live"}]
    )
    s_cfg = _supabase_cfg([{"ref": "a", "name": "db", "status": "ACTIVE_HEALTHY"}])
    conflicts, flags, unreadable = _infrastructure_findings(
        r_cfg, s_cfg, "connected", "connected", as_of=AS_OF
    )
    assert any(c.provider == "render" for c in conflicts)
    assert not any(c.provider == "supabase" for c in conflicts)


# ── TC-035: snapshot_flags with None config ──────────────────────────────


def test_snapshot_flags_none_config():
    flags = _snapshot_flags(None, None, AS_OF)
    assert not flags["connected"]
    assert not flags["needs_sync"]
    assert not flags["stale"]
    assert not flags["sync_error"]
