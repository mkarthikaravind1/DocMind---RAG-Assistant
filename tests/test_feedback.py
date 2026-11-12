"""Answer feedback: thumbs up/down with preset reasons, and the admin views of the votes."""
import pytest

from conftest import FALLBACK, Q_BONUS, Q_INJECTION, Q_LEAVE, Q_UNRELATED, Q_WARRANTY, parse_sse


def vote(env, headers, message_id, rating, reason=None):
    body = {"rating": rating}
    if reason is not None:
        body["reason"] = reason
    return env.client.put(f"/messages/{message_id}/feedback", headers=headers, json=body)


def stats(env, admin):
    return env.client.get("/admin/feedback/stats", headers=admin).json()


def votes(env, admin):
    return env.client.get("/admin/feedback", headers=admin).json()


def conversation(env, headers, cid):
    return env.client.get(f"/conversations/{cid}", headers=headers).json()["messages"]


# ── Voting ────────────────────────────────────────────────────────────────
def test_an_answer_can_be_rated_and_the_vote_survives_a_reload(env, library):
    emp = library["employee"]
    body = env.ask(emp, Q_LEAVE).json()
    assert isinstance(body["message_id"], int)

    r = vote(env, emp, body["message_id"], "up")
    assert r.status_code == 200 and r.json() == {"message_id": body["message_id"], "rating": "up", "reason": None}

    question, answer = conversation(env, emp, body["conversation_id"])
    assert answer["id"] == body["message_id"] and answer["feedback"] == {"rating": "up", "reason": None}
    assert question["role"] == "user" and question["feedback"] is None


def test_an_unrated_answer_reports_no_vote(env, library):
    body = env.ask(library["employee"], Q_LEAVE).json()
    answer = conversation(env, library["employee"], body["conversation_id"])[1]
    assert answer["feedback"] == {"rating": None, "reason": None}


def test_a_vote_can_be_switched_given_a_reason_and_cleared(env, library):
    emp = library["employee"]
    mid = env.ask(emp, Q_LEAVE).json()["message_id"]

    assert vote(env, emp, mid, "up").json()["rating"] == "up"
    assert vote(env, emp, mid, "down").json() == {"message_id": mid, "rating": "down", "reason": None}
    assert vote(env, emp, mid, "down", "wrong_source").json()["reason"] == "wrong_source"
    assert vote(env, emp, mid, "down", "missing_info").json()["reason"] == "missing_info"

    # Switching back to a thumbs up drops the reason
    assert vote(env, emp, mid, "up").json() == {"message_id": mid, "rating": "up", "reason": None}
    assert stats(env, library["admin"])["reasons"]["missing_info"] == 0

    assert vote(env, emp, mid, None).json() == {"message_id": mid, "rating": None, "reason": None}
    s = stats(env, library["admin"])
    assert (s["up"], s["down"], s["rated"], s["satisfaction"]) == (0, 0, 0, None)
    assert votes(env, library["admin"]) == []


def test_streamed_answers_can_be_rated_too(env, library):
    done = parse_sse(env.ask_stream(library["manager"], Q_BONUS).text)[-1][1]
    assert vote(env, library["manager"], done["message_id"], "down", "wrong_answer").status_code == 200
    answer = conversation(env, library["manager"], done["conversation_id"])[1]
    assert answer["feedback"] == {"rating": "down", "reason": "wrong_answer"}


def test_each_answer_in_a_conversation_has_its_own_vote(env, library):
    emp = library["employee"]
    first = env.ask(emp, Q_LEAVE).json()
    second = env.ask(emp, Q_WARRANTY, first["conversation_id"]).json()
    assert first["message_id"] != second["message_id"]

    vote(env, emp, first["message_id"], "up")
    vote(env, emp, second["message_id"], "down", "not_relevant")
    messages = conversation(env, emp, first["conversation_id"])
    assert [m["feedback"] and m["feedback"]["rating"] for m in messages] == [None, "up", None, "down"]


def test_a_fallback_answer_can_be_rated(env, library):
    """A thumbs down on "I couldn't find that" is exactly the signal an admin wants."""
    body = env.ask(library["employee"], Q_UNRELATED).json()
    assert body["answer"] == FALLBACK
    assert vote(env, library["employee"], body["message_id"], "down", "missing_info").status_code == 200


# ── Invalid input ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("body", [
    {"rating": "sideways"},
    {"rating": "UP"},
    {"rating": "down", "reason": "because I said so"},
    {"rating": "down", "reason": "My card is 4111 1111 1111 1111"},     # no free text is accepted
    {"rating": "up", "reason": "wrong_answer"},                          # reasons belong to a thumbs down
    {"rating": None, "reason": "wrong_answer"},
])
def test_invalid_votes_are_rejected_and_nothing_is_stored(env, library, body):
    mid = env.ask(library["employee"], Q_LEAVE).json()["message_id"]
    r = env.client.put(f"/messages/{mid}/feedback", headers=library["employee"], json=body)
    assert r.status_code == 400
    assert stats(env, library["admin"])["rated"] == 0


def test_malformed_requests_are_rejected(env, library):
    mid = env.ask(library["employee"], Q_LEAVE).json()["message_id"]
    emp = library["employee"]
    assert env.client.put(f"/messages/{mid}/feedback", headers=emp, json={"rating": 5}).status_code == 422
    assert env.client.put("/messages/not-a-number/feedback", headers=emp, json={"rating": "up"}).status_code == 422
    assert env.client.put(f"/messages/{mid}/feedback", json={"rating": "up"}).status_code in (401, 403)


# ── Ownership ─────────────────────────────────────────────────────────────
def test_only_the_owner_can_rate_an_answer_not_even_an_admin(env, library):
    body = env.ask(library["employee"], Q_LEAVE).json()
    for other in ("manager", "admin"):
        r = vote(env, library[other], body["message_id"], "down", "wrong_answer")
        assert r.status_code == 404 and r.json()["detail"] == "Answer not found"
    assert vote(env, library["employee"], 999999, "up").json()["detail"] == "Answer not found"   # same reply
    assert stats(env, library["admin"])["rated"] == 0


def test_a_question_cannot_be_rated_only_an_answer(env, library):
    body = env.ask(library["employee"], Q_LEAVE).json()
    question = conversation(env, library["employee"], body["conversation_id"])[0]
    assert vote(env, library["employee"], question["id"], "up").status_code == 404


# ── Admin views ───────────────────────────────────────────────────────────
def test_feedback_views_are_admin_only(env, people):
    for who in ("manager", "employee"):
        assert env.client.get("/admin/feedback", headers=people[who]).status_code == 403
        assert env.client.get("/admin/feedback/stats", headers=people[who]).status_code == 403
    assert env.client.get("/admin/feedback").status_code in (401, 403)

    assert votes(env, people["admin"]) == []
    assert stats(env, people["admin"]) == {
        "up": 0, "down": 0, "rated": 0, "satisfaction": None, "answers": 0, "rated_share": 0.0,
        "reasons": {"wrong_answer": 0, "missing_info": 0, "wrong_source": 0, "not_relevant": 0},
    }


def test_stats_count_votes_reasons_and_the_share_of_answers_rated(env, library):
    emp, mgr = library["employee"], library["manager"]
    ids = [env.ask(emp, q).json()["message_id"] for q in (Q_LEAVE, Q_WARRANTY, Q_UNRELATED)]
    ids.append(env.ask(mgr, Q_BONUS).json()["message_id"])
    env.ask(emp, Q_LEAVE)                                    # a fifth answer, never rated
    env.ask(emp, Q_INJECTION)                                # blocked: not an answer at all

    vote(env, emp, ids[0], "up")
    vote(env, emp, ids[1], "up")
    vote(env, emp, ids[2], "down", "missing_info")
    vote(env, mgr, ids[3], "down")

    s = stats(env, library["admin"])
    assert (s["up"], s["down"], s["rated"], s["satisfaction"]) == (2, 2, 4, 0.5)
    assert (s["answers"], s["rated_share"]) == (5, 0.8)
    assert s["reasons"] == {"wrong_answer": 0, "missing_info": 1, "wrong_source": 0, "not_relevant": 0}


def test_recent_votes_show_the_question_and_scores_but_no_answer_text(env, library):
    emp = library["employee"]
    first = env.ask(emp, Q_LEAVE).json()["message_id"]
    second = env.ask(library["manager"], Q_BONUS).json()["message_id"]
    vote(env, emp, first, "up")
    vote(env, library["manager"], second, "down", "wrong_answer")

    rows = votes(env, library["admin"])
    assert [(r["question"], r["rating"], r["reason"], r["user_role"]) for r in rows] == [
        (Q_BONUS, "down", "wrong_answer", "manager"),        # newest first
        (Q_LEAVE, "up", None, "employee"),
    ]
    assert rows[1]["user_email"] == "employee@example.test"
    assert rows[1]["faithfulness"] == 1.0 and 0 < rows[1]["answer_relevancy"] <= 1    # from the evaluation
    assert set(rows[0]) == {"id", "query_log_id", "rating", "reason", "question", "user_email", "user_role",
                            "faithfulness", "answer_relevancy", "timestamp"}

    # Conversations are private, including from admins: no answer or document text here
    text = env.client.get("/admin/feedback", headers=library["admin"]).text
    for fact in ("27 days", "14 percent", "April", "carried over"):
        assert fact not in text, fact


def test_pii_typed_into_a_question_is_redacted_in_the_feedback_list(env, library):
    emp = library["employee"]
    mid = env.ask(emp, "My card is 4111 1111 1111 1111. " + Q_LEAVE).json()["message_id"]
    vote(env, emp, mid, "up")
    row = votes(env, library["admin"])[0]
    assert "4111" not in row["question"] and "[REDACTED]" in row["question"]


def test_query_logs_show_the_vote_next_to_each_query(env, library):
    emp = library["employee"]
    rated = env.ask(emp, Q_LEAVE).json()["message_id"]
    env.ask(emp, Q_WARRANTY)
    env.ask(emp, Q_INJECTION)
    vote(env, emp, rated, "down", "wrong_source")

    logs = {l["question"]: l for l in env.client.get("/admin/logs", headers=library["admin"]).json()}
    assert logs[Q_LEAVE]["feedback"] == {"rating": "down", "reason": "wrong_source"}
    assert logs[Q_WARRANTY]["feedback"] == {"rating": None, "reason": None}
    assert logs[Q_INJECTION]["feedback"] == {"rating": None, "reason": None}


# ── Deleting a conversation ───────────────────────────────────────────────
def test_votes_stay_as_statistics_when_the_conversation_is_deleted(env, library):
    emp = library["employee"]
    body = env.ask(emp, Q_LEAVE).json()
    vote(env, emp, body["message_id"], "down", "wrong_answer")
    assert env.client.delete(f"/conversations/{body['conversation_id']}", headers=emp).status_code == 200

    s = stats(env, library["admin"])
    assert (s["down"], s["reasons"]["wrong_answer"]) == (1, 1)
    assert votes(env, library["admin"])[0]["question"] == Q_LEAVE
    assert vote(env, emp, body["message_id"], "up").status_code == 404      # the answer itself is gone


def test_a_new_answer_never_inherits_the_vote_of_a_deleted_one(env, library):
    """SQLite reuses row ids after a delete; a kept vote must not attach to the next answer."""
    emp = library["employee"]
    old = env.ask(emp, Q_LEAVE).json()
    vote(env, emp, old["message_id"], "down", "wrong_answer")
    env.client.delete(f"/conversations/{old['conversation_id']}", headers=emp)

    new = env.ask(emp, Q_WARRANTY).json()
    answer = conversation(env, emp, new["conversation_id"])[1]
    assert answer["feedback"] == {"rating": None, "reason": None}
    assert vote(env, emp, new["message_id"], "up").status_code == 200
    s = stats(env, library["admin"])
    assert (s["up"], s["down"]) == (1, 1)


# ── Feedback bookkeeping can never break a chat ───────────────────────────
def test_chat_still_answers_when_the_feedback_link_cannot_be_saved(env, library, monkeypatch):
    import feedback

    def boom(*args, **kwargs):
        raise RuntimeError("simulated database failure")
    monkeypatch.setattr(feedback, "Feedback", boom)

    body = env.ask(library["employee"], Q_LEAVE)
    assert body.status_code == 200 and "27 days" in body.json()["answer"]
    done = parse_sse(env.ask_stream(library["employee"], Q_LEAVE).text)[-1]
    assert done[0] == "done" and "27 days" in done[1]["answer"]


def test_an_answer_saved_before_feedback_existed_can_still_be_rated(env, library):
    import database
    import models

    emp = library["employee"]
    body = env.ask(emp, Q_LEAVE).json()
    db = database.SessionLocal()
    try:
        db.query(models.Feedback).delete()          # as if the answer predates the feature
        db.commit()
    finally:
        db.close()

    assert vote(env, emp, body["message_id"], "up").status_code == 200
    assert conversation(env, emp, body["conversation_id"])[1]["feedback"]["rating"] == "up"
    row = votes(env, library["admin"])[0]
    assert (row["rating"], row["question"], row["query_log_id"]) == ("up", None, None)   # no log link, still counted
    assert stats(env, library["admin"])["up"] == 1
