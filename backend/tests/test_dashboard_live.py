"""Dashboard widgets derive from real ingested rows, never seeded mock data."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.schemas import dashboard as s
from src.services import dashboard_live as live

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def gh(kind, number, title, hours_ago, state="open", repo="me/app"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        kind=kind,
        provider_id=f"{repo}#{number}",
        occurred_at=NOW - timedelta(hours=hours_ago),
        raw={"title": title, "state": state},
    )


def test_age_label_units():
    assert live.age_label(NOW - timedelta(minutes=5), NOW) == "5 m"
    assert live.age_label(NOW - timedelta(hours=3), NOW) == "3 h"
    assert live.age_label(NOW - timedelta(days=2), NOW) == "2 d"


def test_decisions_are_open_prs_oldest_first_and_schema_valid():
    rows = [
        gh("pr", 1, "new", 2),
        gh("pr", 2, "old", 50),
        gh("pr", 3, "closed", 5, state="closed"),
        gh("issue", 4, "an issue", 1),
    ]
    out = live.build_decisions(rows, NOW)
    assert [d["title"] for d in out] == ["Review me/app#2 old", "Review me/app#1 new"]
    dumped = [
        s.DecisionResponse.model_validate(d).model_dump(by_alias=True) for d in out
    ]
    assert dumped[0]["waitingSince"] == "2 d"


def test_tasks_are_open_prs_then_issues_and_validate():
    out = live.build_tasks([gh("issue", 2, "i", 1), gh("pr", 1, "p", 1)], NOW)
    assert [t["priority"] for t in out] == ["p1", "p2"]
    assert all(t["source"] == "github" for t in out)
    for t in out:
        s.TaskResponse.model_validate(t)


def test_task_age_label_never_looks_like_urgency():
    out = live.build_tasks(
        [gh("pr", 1, "a", 1), gh("pr", 2, "b", 30), gh("pr", 3, "c", 72)], NOW
    )
    labels = {t["due"] for t in out}
    assert labels == {"Updated today", "Updated yesterday", "Updated 3 d ago"}
    assert not any(label.startswith(("Today", "Yesterday")) for label in labels)


def test_rows_without_explicit_open_state_are_not_listed():
    rows = [gh("pr", 1, "x", 1, state=None), gh("issue", 2, "y", 1, state="closed")]
    assert live.build_tasks(rows, NOW) == []
    assert live.build_decisions(rows, NOW) == []


def test_null_title_does_not_render_none():
    row = gh("pr", 5, None, 1)
    assert live.build_decisions([row], NOW)[0]["title"] == "Review me/app#5"


def test_tasks_skip_empty_gmail_snippets_and_cap():
    out = live.build_tasks([gh("issue", n, "x", n) for n in range(20)], NOW)
    assert len(out) == 8
    assert all(t["source"] == "github" for t in out)


def test_focus_prefers_oldest_pr_then_issue_then_honest_empty():
    pr = live.build_focus([gh("pr", 9, "fix", 30), gh("issue", 1, "bug", 90)], NOW)
    assert pr["title"] == "Review me/app#9 fix"
    issue = live.build_focus([gh("issue", 1, "bug", 90)], NOW)
    assert issue["title"] == "me/app#1 bug"
    empty = live.build_focus([], NOW)
    assert empty["title"] == "Nothing urgent"
    for f in (pr, issue, empty):
        s.FocusBlockResponse.model_validate(f)


def test_empty_inputs_yield_empty_lists_not_fake_rows():
    assert live.build_tasks([], NOW) == []
    assert live.build_decisions([], NOW) == []
    assert live.build_notifications([], NOW) == []
    assert live.build_agent_activity([], NOW) == []


def test_notifications_only_for_unhealthy_integrations():
    ok = SimpleNamespace(
        id=1, slug="github", status="connected", last_error=None, last_synced_at=None
    )
    bad = SimpleNamespace(
        id=2,
        slug="gmail",
        status="error",
        last_error="boom",
        last_synced_at=NOW - timedelta(hours=4),
    )
    out = live.build_notifications([ok, bad], NOW)
    assert len(out) == 1
    assert out[0]["severity"] == "critical" and out[0]["time"] == "4 h"
    s.NotificationResponse.model_validate(out[0])


def test_agent_activity_reflects_success_flag():
    logs = [
        SimpleNamespace(
            id=uuid.uuid4(),
            agent_name="a",
            success=True,
            invoked_at=NOW - timedelta(minutes=3),
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            agent_name="b",
            success=False,
            invoked_at=NOW - timedelta(hours=1),
        ),
    ]
    out = live.build_agent_activity(logs, NOW)
    assert [o["message"] for o in out] == ["Run completed", "Run failed"]
    for o in out:
        s.AgentTickResponse.model_validate(o)


def test_health_habits_from_whoop_and_apple():
    whoop = {
        "recovery": {
            "recovery_score": 78.4,
            "hrv_rmssd_milli": 64.6,
            "resting_heart_rate": 52,
        },
        "sleep": {
            "total_in_bed_time_milli": 8 * 3_600_000,
            "total_awake_time_milli": 3_600_000,
            "sleep_performance_percentage": 84,
        },
        "strain": {"score": 12.34},
    }
    apple = {"steps": 8432}
    out = live.build_health_habits(whoop, apple)
    assert [c["name"] for c in out] == ["Recovery", "Sleep", "Strain", "Steps"]
    assert out[0]["value"] == "78%"
    assert out[1]["value"] == "7.0 h" and "84%" in out[1]["delta"]
    assert out[3]["value"] == "8,432"
    for c in out:
        s.HealthHabitResponse.model_validate(c)


def test_health_habits_apple_only_and_empty():
    out = live.build_health_habits(
        {"connected": False}, {"sleep_hours": 6.5, "resting_heart_rate": 58.2}
    )
    assert [c["name"] for c in out] == ["Sleep", "Resting HR"]
    assert live.build_health_habits(None, None) == []
    assert (
        live.build_health_habits(
            {"connected": True, "needs_reauth": True},
            {"connected": True, "stale": True},
        )
        == []
    )
