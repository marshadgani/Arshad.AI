"""FEAT-132: pure verdict logic. Clocks are passed in."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.services.render import verdict as v
from src.services.render.models import LogRecord, MetricWindow, RenderVerdictResponse

T0 = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)
FINISH = T0 + timedelta(minutes=3)
LATER = FINISH + timedelta(hours=3)


def _logs(n_err, n_info=5):
    recs = [LogRecord(timestamp=T0, level="error", message="e") for _ in range(n_err)]
    recs += [LogRecord(timestamp=T0, level="info", message="i") for _ in range(n_info)]
    return recs


def _m(mean=None, failed=False):
    return MetricWindow(
        mean=mean, fetch_failed=failed, sample_count=0 if mean is None else 5
    )


def _run(
    before,
    after,
    *,
    as_of=LATER,
    finish=FINISH,
    bt=False,
    at=False,
    cpu=(None, None),
    lat=(None, None),
    mem=(None, None),
    connected=True,
    extra=(),
):
    bw, aw = v.compute_windows(T0, finish, as_of)
    return v.compute_verdict_from_data(
        before,
        after,
        bt,
        at,
        bw,
        aw,
        _m(cpu[0]),
        _m(cpu[1]),
        _m(mem[0]),
        _m(mem[1]),
        _m(lat[0]),
        _m(lat[1]),
        connected,
        False,
        extra_failures=extra,
    )


def test_unknown_when_after_window_not_elapsed():
    r = _run(_logs(1), _logs(1), as_of=FINISH + timedelta(minutes=10))
    assert r.verdict == "unknown" and "window_incomplete" in r.partial_failures


def test_unknown_when_deploy_still_running():
    assert v.compute_windows(T0, None, LATER) is None


def test_unknown_when_before_has_too_few_records():
    r = _run(_logs(0, 1), _logs(0))
    assert r.verdict == "unknown"
    assert "insufficient_log_samples_before" in r.partial_failures


def test_unknown_when_after_has_too_few_records():
    r = _run(_logs(0), _logs(0, 1))
    assert "insufficient_log_samples_after" in r.partial_failures
    assert r.verdict == "unknown"


def test_clean_service_with_enough_records_is_neutral():
    assert _run(_logs(0), _logs(0)).verdict == "neutral"


def test_unknown_when_truncated_before_or_after():
    assert _run(_logs(1), _logs(1), bt=True).verdict == "unknown"
    assert _run(_logs(1), _logs(1), at=True).verdict == "unknown"


def test_regression_when_rate_passes_multiplier():
    r = _run(_logs(2), _logs(10))
    assert r.verdict == "regression"
    assert r.before_error_count == 2 and r.after_error_count == 10


def test_neutral_when_equal():
    assert _run(_logs(3), _logs(3)).verdict == "neutral"


def test_improvement_when_rate_drops_and_metrics_lower():
    r = _run(_logs(10), _logs(8), cpu=(0.5, 0.4), lat=(100, 80))
    assert r.verdict == "improvement"


def test_slight_drop_without_metrics_is_neutral():
    assert _run(_logs(10), _logs(8)).verdict == "neutral"


def test_metrics_never_reverse_regression():
    r = _run(_logs(2), _logs(10), cpu=(0.9, 0.1), lat=(900, 10))
    assert r.verdict == "regression"


def test_failed_metric_blocks_neutral_but_not_regression():
    bw, aw = v.compute_windows(T0, FINISH, LATER)
    args = (
        bw,
        aw,
        _m(failed=True),
        _m(failed=True),
        _m(),
        _m(),
        _m(),
        _m(),
        True,
        False,
    )
    neutral = v.compute_verdict_from_data(_logs(3), _logs(3), False, False, *args)
    assert neutral.verdict == "unknown" and "cpu" in neutral.partial_failures
    reg = v.compute_verdict_from_data(_logs(1), _logs(10), False, False, *args)
    assert reg.verdict == "regression"


def test_logs_failure_is_unknown():
    r = _run([], [], extra=["logs", "scope_insufficient"])
    assert r.verdict == "unknown"
    assert "insufficient_log_samples_before" not in r.partial_failures


def test_not_connected_guard_returns_unknown_before_classification():
    r = _run(_logs(1), _logs(50), connected=False)
    assert r.verdict == "unknown" and r.connected is False


def test_needs_reauth_forces_unknown():
    bw, aw = v.compute_windows(T0, FINISH, LATER)
    m = _m()
    r = v.compute_verdict_from_data(
        _logs(1), _logs(50), False, False, bw, aw, m, m, m, m, m, m, True, True
    )
    assert r.verdict == "unknown" and r.needs_reauth


def test_response_model_forbids_impossible_states():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RenderVerdictResponse(verdict="neutral", connected=False)
    with pytest.raises(ValidationError):
        RenderVerdictResponse(verdict="unknown", connected=False, needs_reauth=True)


def test_no_github_references_in_feature_code():
    root = Path(__file__).resolve().parents[1] / "src"
    files = [
        root / "api/v1/render_deploys.py",
        *(root / "services/render").glob("*.py"),
    ]
    for f in files:
        assert "github" not in f.read_text().lower(), f.name


def test_unknown_when_no_log_carries_a_level():
    unlabelled = [LogRecord(timestamp=T0, level=None, message="x") for _ in range(5)]
    resp = _run(unlabelled, _logs(0))
    assert resp.verdict == "unknown"
    assert "log_level_unavailable_before" in resp.partial_failures
