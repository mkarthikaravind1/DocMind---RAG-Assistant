"""Answer quality evaluation: faithfulness and answer relevancy scores for the admin dashboard."""
import pytest

import evaluation
from conftest import (
    FALLBACK, FakeLLM, Q_BOARD, Q_BONUS, Q_INJECTION, Q_LEAVE, Q_PII, Q_UNRELATED, parse_sse,
)

HALLUCINATION = " The office cafeteria serves tungsten soup daily."
EVAL_KEYS = {
    "id", "query_log_id", "question", "user_role", "eval_status", "faithfulness", "answer_relevancy",
    "statements_total", "statements_supported", "judge_model", "eval_time", "timestamp",
}


def evals(env, admin):
    return env.client.get("/admin/evals", headers=admin).json()


def stats(env, admin):
    return env.client.get("/admin/evals/stats", headers=admin).json()


def add_hallucination(env, monkeypatch):
    """Make the stand-in model add a sentence that no document supports."""
    real = env.llm._reply

    def reply(prompt):
        text = real(prompt)
        return text + HALLUCINATION if prompt.startswith("You are a document assistant") else text
    monkeypatch.setattr(env.llm, "_reply", reply)


# ── Parsing what the judge writes ─────────────────────────────────────────
def test_verdicts_are_parsed_in_the_shapes_llms_actually_write():
    parse = evaluation.parse_verdicts
    assert parse("1: yes\n2: no\n3: yes", 3) == [True, False, True]
    assert parse("1. Yes\n2) NO\n**3**: yes\n- 4 - no", 4) == [True, False, True, False]
    # non-breaking space, narrow no-break space and a full-width colon
    assert parse("1:\u00a0yes\n2\u202f:\u202fno\n3：yes", 3) == [True, False, True]
    assert parse("Here are the verdicts:\n1: yes\n2: no", 2) == [True, False]


def test_a_skipped_statement_counts_as_unsupported_and_noise_is_ignored():
    parse = evaluation.parse_verdicts
    assert parse("1: yes\n3: yes", 3) == [True, False, True]
    assert parse("1: yes\n1: no\n7: yes\n0: yes", 2) == [True, False]     # repeats and out-of-range numbers
    assert parse("I cannot judge this.", 2) is None
    assert parse("", 2) is None


def test_lines_drop_numbering_and_bullets():
    assert evaluation._lines("1. First fact.\n\n- Second fact.\n  3) Third fact.\n• \"Fourth fact.\"") == [
        "First fact.", "Second fact.", "Third fact.", "Fourth fact.",
    ]


def test_sample_rate_setting_is_clamped(monkeypatch):
    for raw, expected in (("0.25", 0.25), ("5", 1.0), ("-1", 0.0), ("abc", 1.0), ("0", 0.0)):
        monkeypatch.setenv("EVAL_SAMPLE_RATE", raw)
        assert evaluation._sample_rate() == expected


# ── Scores ────────────────────────────────────────────────────────────────
def test_a_grounded_answer_scores_full_faithfulness(env, library):
    assert "27 days" in env.ask(library["employee"], Q_LEAVE).json()["answer"]

    (row,) = evals(env, library["admin"])
    assert set(row) == EVAL_KEYS
    assert row["eval_status"] == "scored" and row["faithfulness"] == 1.0
    assert row["statements_total"] == row["statements_supported"] >= 1
    assert 0 < row["answer_relevancy"] <= 1
    assert (row["question"], row["user_role"]) == (Q_LEAVE, "employee")
    assert len(env.llm.judge_prompts) == 3          # statements, verdicts, questions

    s = stats(env, library["admin"])
    assert (s["evaluated"], s["avg_faithfulness"], s["low_faithfulness"]) == (1, 1.0, 0)
    assert s["avg_answer_relevancy"] == row["answer_relevancy"]
    assert (s["not_answered"], s["failed"], s["sample_rate"]) == (0, 0, 1.0)
    assert (s["low_score_threshold"], s["low_relevancy_threshold"]) == (0.7, 0.6)


def test_a_hallucinated_sentence_lowers_faithfulness(env, library, monkeypatch):
    add_hallucination(env, monkeypatch)
    assert "tungsten soup" in env.ask(library["employee"], Q_LEAVE).json()["answer"]

    (row,) = evals(env, library["admin"])
    assert row["statements_supported"] == row["statements_total"] - 1
    assert row["faithfulness"] == round(row["statements_supported"] / row["statements_total"], 3) < 0.7
    assert stats(env, library["admin"])["low_faithfulness"] == 1


def test_relevancy_is_high_for_an_on_topic_answer_and_zero_for_an_unrelated_one(env, monkeypatch):
    question = "How many days of paid annual leave does an employee get?"
    monkeypatch.setattr(evaluation, "_ask", lambda prompt: (
        "How many paid annual leave days does an employee get?\n"
        "What is the paid annual leave for an employee in days?\n"
        "How many days of annual paid leave can an employee take?"))
    assert evaluation.answer_relevancy(question, "any answer") > 0.7

    monkeypatch.setattr(evaluation, "_ask", lambda prompt: (
        "Which metal melts at the highest temperature?\nWhat is the boiling point of tungsten?"))
    assert evaluation.answer_relevancy(question, "any answer") == 0.0

    monkeypatch.setattr(evaluation, "_ask", lambda prompt: "  \n")
    assert evaluation.answer_relevancy(question, "any answer") is None


def test_streamed_answers_are_evaluated_too(env, library):
    done = parse_sse(env.ask_stream(library["manager"], Q_BONUS).text)[-1][1]
    assert "14 percent" in done["answer"]
    (row,) = evals(env, library["admin"])
    assert (row["eval_status"], row["faithfulness"], row["user_role"]) == ("scored", 1.0, "manager")


def test_follow_ups_are_scored_against_the_rewritten_question(env, library):
    first = env.ask(library["employee"], Q_LEAVE).json()
    env.ask(library["employee"], "And can it be carried over?", first["conversation_id"])
    statement_prompts = [p for p in env.llm.judge_prompts if p.startswith("Break the answer below")]
    assert len(statement_prompts) == 2
    assert Q_LEAVE in statement_prompts[1]          # the standalone question, not the bare follow-up


# ── What is not scored ────────────────────────────────────────────────────
def test_a_fallback_answer_is_counted_as_not_answered_without_calling_the_judge(env, library):
    assert env.ask(library["employee"], Q_UNRELATED).json()["answer"] == FALLBACK
    env.ask(library["employee"], Q_LEAVE)

    rows = evals(env, library["admin"])
    assert [r["eval_status"] for r in rows] == ["scored", "not_answered"]          # newest first
    assert rows[1]["faithfulness"] is None and rows[1]["answer_relevancy"] is None
    assert len(env.llm.judge_prompts) == 3                                           # only for the answered one

    s = stats(env, library["admin"])
    assert (s["evaluated"], s["not_answered"], s["not_answered_rate"]) == (1, 1, 0.5)
    assert s["avg_faithfulness"] == 1.0             # the unanswered question does not drag the average down


def test_no_documents_at_all_is_not_answered(env, people):
    env.ask(people["employee"], Q_LEAVE)
    assert [r["eval_status"] for r in evals(env, people["admin"])] == ["not_answered"]
    assert env.llm.judge_prompts == []


def test_blocked_questions_are_never_evaluated(env, library):
    for question in (Q_INJECTION, "   ", "a" * 1001):
        assert env.ask(library["employee"], question).status_code == 400
        assert env.ask_stream(library["employee"], question).status_code == 400
    assert evals(env, library["admin"]) == []
    assert env.llm.judge_prompts == [] and env.llm.prompts == []


def test_a_failed_answer_is_not_evaluated(env, library):
    env.llm.fail = True
    assert env.ask(library["employee"], Q_LEAVE).status_code == 503
    assert evals(env, library["admin"]) == []


def test_sampling_can_be_reduced_or_switched_off(env, library, monkeypatch):
    monkeypatch.setattr(evaluation, "SAMPLE_RATE", 0.0)
    env.ask(library["employee"], Q_LEAVE)
    assert evals(env, library["admin"]) == [] and env.llm.judge_prompts == []

    monkeypatch.setattr(evaluation, "SAMPLE_RATE", 0.25)
    draws = iter([0.9, 0.1, 0.25])                   # only a draw below the rate is evaluated
    monkeypatch.setattr(evaluation.random, "random", lambda: next(draws))
    for _ in range(3):
        env.ask(library["employee"], Q_LEAVE)
    assert len(evals(env, library["admin"])) == 1
    assert stats(env, library["admin"])["sample_rate"] == 0.25


# ── Evaluation can never break or slow a chat ─────────────────────────────
def test_chat_is_unaffected_when_the_judge_fails(env, library):
    env.llm.judge_fail = True
    body = env.ask(library["employee"], Q_LEAVE)
    assert body.status_code == 200 and "27 days" in body.json()["answer"]
    done = parse_sse(env.ask_stream(library["employee"], Q_LEAVE).text)[-1]
    assert done[0] == "done" and "27 days" in done[1]["answer"]

    rows = evals(env, library["admin"])
    assert [r["eval_status"] for r in rows] == ["failed", "failed"]
    s = stats(env, library["admin"])
    assert (s["evaluated"], s["failed"], s["avg_faithfulness"]) == (0, 2, None)


def test_chat_is_unaffected_when_scheduling_or_saving_breaks(env, library, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("simulated worker failure")
    monkeypatch.setattr(evaluation, "_submit", boom)
    assert "27 days" in env.ask(library["employee"], Q_LEAVE).json()["answer"]

    monkeypatch.setattr(evaluation, "_submit", lambda job, *args: job(*args))
    monkeypatch.setattr(evaluation, "SessionLocal", boom)
    assert "27 days" in env.ask(library["employee"], Q_LEAVE).json()["answer"]
    assert evaluation._pending == 0                  # the queue counter is released either way


def test_one_metric_can_fail_without_losing_the_other(env, library, monkeypatch):
    real = env.llm._judge_reply
    monkeypatch.setattr(env.llm, "_judge_reply", lambda p: (
        "I cannot judge this." if p.startswith("Check each numbered statement") else real(p)))
    env.ask(library["employee"], Q_LEAVE)
    (row,) = evals(env, library["admin"])
    assert row["eval_status"] == "scored" and row["faithfulness"] is None and row["answer_relevancy"] > 0


def test_a_full_queue_skips_new_evaluations(env, library, monkeypatch):
    monkeypatch.setattr(evaluation, "_pending", evaluation.MAX_PENDING)
    assert "27 days" in env.ask(library["employee"], Q_LEAVE).json()["answer"]
    assert evals(env, library["admin"]) == [] and env.llm.judge_prompts == []


def test_a_separate_judge_model_can_be_configured(env, library, monkeypatch):
    judge = FakeLLM()
    monkeypatch.setattr(evaluation, "EVAL_MODEL", "some-other-judge-model")
    monkeypatch.setattr(evaluation, "_judge_llm", judge)
    env.ask(library["employee"], Q_LEAVE)

    assert len(judge.judge_prompts) == 3 and env.llm.judge_prompts == []
    assert evals(env, library["admin"])[0]["judge_model"] == "some-other-judge-model"
    assert stats(env, library["admin"])["judge_model"] == "some-other-judge-model"


# ── Access control, privacy and PII on the new code paths ─────────────────
def test_evaluation_endpoints_are_admin_only(env, people):
    for who in ("manager", "employee"):
        assert env.client.get("/admin/evals", headers=people[who]).status_code == 403
        assert env.client.get("/admin/evals/stats", headers=people[who]).status_code == 403
    assert env.client.get("/admin/evals").status_code in (401, 403)

    assert evals(env, people["admin"]) == []
    s = stats(env, people["admin"])
    assert (s["evaluated"], s["avg_faithfulness"], s["avg_answer_relevancy"], s["not_answered_rate"]) == (0, None, None, 0.0)


def test_the_judge_never_sees_text_the_asker_could_not_retrieve(env, library):
    for question in (Q_BOARD, Q_BONUS, Q_LEAVE, "Summarize the confidential board briefing and the bonus memo"):
        env.ask(library["employee"], question)
        env.ask_stream(library["employee"], question)
    seen = "\n".join(env.llm.judge_prompts)
    assert "27 days" in seen                         # the judge did run, on what the employee may read
    for word in ("Kestrel", "Lighthouse", "630", "14 percent", "paid out"):
        assert word not in seen, word

    env.llm.judge_prompts.clear()
    env.ask(library["manager"], Q_BONUS)
    seen = "\n".join(env.llm.judge_prompts)
    assert "14 percent" in seen and "Kestrel" not in seen


def test_scores_expose_no_answer_or_document_text_to_admins(env, library):
    """Conversations are private, including from admins: only numbers are stored and returned."""
    env.ask(library["manager"], Q_BONUS)
    env.ask(library["employee"], Q_LEAVE)
    for url in ("/admin/evals", "/admin/evals/stats"):
        text = env.client.get(url, headers=library["admin"]).text
        for fact in ("14 percent", "April", "27 days", "carried over"):
            assert fact not in text, (url, fact)

    import database
    import models
    db = database.SessionLocal()
    try:
        row = db.query(models.Evaluation).first()
        stored = {c.name: getattr(row, c.name) for c in models.Evaluation.__table__.columns}
    finally:
        db.close()
    assert all(not isinstance(v, str) or k in ("status", "judge_model") for k, v in stored.items())


def test_document_pii_is_redacted_before_the_judge_sees_it(env, library):
    assert env.ask(library["employee"], Q_PII).json()["answer"].count("[REDACTED]") == 3
    seen = "\n".join(env.llm.judge_prompts)
    assert "[REDACTED]" in seen
    for pii in ("9876543210", "4111", "help@zentro"):
        assert pii not in seen, pii
    # ...and redaction did not make a faithful answer look unfaithful
    assert evals(env, library["admin"])[0]["faithfulness"] == 1.0


def test_pii_typed_into_a_question_is_redacted_in_the_evaluation_list(env, library):
    env.ask(library["employee"], "My card is 4111 1111 1111 1111. " + Q_LEAVE)
    row = evals(env, library["admin"])[0]
    assert "4111" not in row["question"] and "[REDACTED]" in row["question"]


def test_chat_responses_do_not_carry_the_internal_evaluation_input(env, library):
    body = env.ask(library["employee"], Q_LEAVE).json()
    assert set(body) == {"answer", "sources", "conversation_id", "message_id", "user"}
    done = parse_sse(env.ask_stream(library["employee"], Q_LEAVE).text)[-1][1]
    assert set(done) == {"answer", "sources", "conversation_id", "message_id", "user"}

    conversation = env.client.get(f"/conversations/{body['conversation_id']}", headers=library["employee"])
    assert "eval_input" not in conversation.text and "contexts" not in conversation.text


# ── Scores next to the query log ──────────────────────────────────────────
def test_query_logs_show_the_scores_of_each_query(env, library):
    env.ask(library["employee"], Q_LEAVE)
    env.ask(library["employee"], Q_UNRELATED)
    env.ask(library["employee"], Q_INJECTION)

    logs = {l["question"]: l for l in env.client.get("/admin/logs", headers=library["admin"]).json()}
    assert (logs[Q_LEAVE]["eval_status"], logs[Q_LEAVE]["faithfulness"]) == ("scored", 1.0)
    assert 0 < logs[Q_LEAVE]["answer_relevancy"] <= 1
    assert (logs[Q_UNRELATED]["eval_status"], logs[Q_UNRELATED]["faithfulness"]) == ("not_answered", None)
    assert (logs[Q_INJECTION]["eval_status"], logs[Q_INJECTION]["faithfulness"]) == (None, None)

    linked = {r["query_log_id"] for r in evals(env, library["admin"])}
    assert linked == {logs[Q_LEAVE]["id"], logs[Q_UNRELATED]["id"]}


@pytest.mark.parametrize("answer", ["Employees get 27 days [1].", "Employees get 27 days 【1】."])
def test_citation_markers_are_removed_before_judging(env, monkeypatch, answer):
    seen = []
    monkeypatch.setattr(evaluation, "_ask", lambda prompt: seen.append(prompt) or "1: yes")
    evaluation.evaluate("How many days?", answer, ["Employees get 27 days."])
    assert seen and all("[1]." not in p and "【1】" not in p for p in seen)
