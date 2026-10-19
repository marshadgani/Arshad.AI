"""FEAT-132: snapshot entries carry scalar deploy status, deploy id and owner id."""

from src.integrations.project import render


def test_entries_store_scalars_not_tuples():
    kept = [{"id": "srv-a", "name": "api", "type": "web_service", "ownerId": "tea-1"}]
    entries = render._build_service_entries(kept, [("live", "dep-1")])
    e = entries[0]
    assert e["latest_deploy_status"] == "live"
    assert e["latest_deploy_id"] == "dep-1"
    assert e["owner_id"] == "tea-1"


def test_failed_lookup_and_missing_owner_are_none():
    entries = render._build_service_entries([{"id": "srv-a"}], [RuntimeError("x")])
    e = entries[0]
    assert e["latest_deploy_status"] == render.DEPLOY_UNCHECKED
    assert e["latest_deploy_id"] is None and e["owner_id"] is None


def test_service_without_id_is_unchecked():
    e = render._build_service_entries([{"name": "x"}], [])[0]
    assert e["latest_deploy_status"] == render.DEPLOY_UNCHECKED
    assert e["latest_deploy_id"] is None
