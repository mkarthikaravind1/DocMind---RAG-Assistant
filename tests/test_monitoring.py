"""Admin query logs, stats and CORS."""
from datetime import datetime, timezone

from conftest import Q_BONUS, Q_INJECTION, Q_LEAVE, Q_UNRELATED


def test_logs_and_stats_are_admin_only(env, people):
    for who in ("manager", "employee"):
        assert env.client.get("/admin/logs", headers=people[who]).status_code == 403
        assert env.client.get("/admin/logs/stats", headers=people[who]).status_code == 403


def test_empty_stats(env, people):
    assert env.client.get("/admin/logs/stats", headers=people["admin"]).json() == {
        "total_queries": 0, "avg_response_time": 0.0, "guardrail_violations": 0, "avg_chunks": 0.0,
    }
    assert env.client.get("/admin/logs", headers=people["admin"]).json() == []


def test_every_request_is_logged_including_blocked_and_streamed_ones(env, library):
    env.ask(library["employee"], Q_LEAVE)
    env.ask_stream(library["manager"], Q_BONUS)
    env.ask(library["employee"], Q_UNRELATED)
    env.ask(library["employee"], Q_INJECTION)
    env.ask_stream(library["manager"], "   ")

    logs = env.client.get("/admin/logs", headers=library["admin"]).json()
    assert len(logs) == 5
    by_question = {l["question"]: l for l in logs}

    answered = by_question[Q_LEAVE]
    assert (answered["user_email"], answered["user_role"]) == ("employee@example.test", "employee")
    assert answered["guardrail_hit"] is None and answered["answer_length"] > 0 and answered["chunks_retrieved"] >= 1

    streamed = by_question[Q_BONUS]
    assert streamed["user_role"] == "manager" and streamed["answer_length"] > 0

    blocked = by_question[Q_INJECTION]
    assert "disallowed" in blocked["guardrail_hit"] and blocked["answer_length"] == 0

    # Timestamps are sent with an explicit UTC offset and are the real current time
    stamp = datetime.fromisoformat(logs[0]["timestamp"])
    assert stamp.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 120


def test_stats_exclude_blocked_requests_from_the_averages(env, library):
    env.ask(library["employee"], Q_LEAVE)
    env.ask(library["employee"], Q_LEAVE)
    env.ask(library["employee"], Q_INJECTION)
    env.ask(library["employee"], Q_INJECTION)

    logs = env.client.get("/admin/logs", headers=library["admin"]).json()
    answered = [l for l in logs if not l["guardrail_hit"]]
    stats = env.client.get("/admin/logs/stats", headers=library["admin"]).json()

    assert stats["total_queries"] == 4 and stats["guardrail_violations"] == 2
    assert stats["avg_chunks"] == round(sum(l["chunks_retrieved"] for l in answered) / 2, 2) > 0
    assert abs(stats["avg_response_time"] - sum(l["response_time"] for l in answered) / 2) < 0.002


def test_cors_allows_only_the_configured_frontend(env):
    preflight = lambda origin: env.client.options("/chat", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert preflight("http://localhost:3000").headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert preflight("http://evil.example").headers.get("access-control-allow-origin") is None
