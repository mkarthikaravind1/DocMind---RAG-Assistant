"""Conversation memory and saved chat history."""
from conftest import FALLBACK, Q_BOARD, Q_BONUS, Q_INJECTION, Q_LEAVE, Q_WARRANTY, parse_sse

Q_FOLLOW_UP = "And for how long can the unused ones be carried over?"


def chats(env, headers):
    return env.client.get("/conversations", headers=headers).json()


def test_first_answer_creates_a_titled_conversation(env, library):
    emp = library["employee"]
    assert chats(env, emp) == []
    cid = env.ask(emp, Q_WARRANTY).json()["conversation_id"]
    listing = chats(env, emp)
    assert [c["id"] for c in listing] == [cid]
    assert listing[0]["title"] == Q_WARRANTY and listing[0]["updated_at"].endswith("+00:00")


def test_long_first_question_gives_a_shortened_title(env, library):
    question = "Please explain in detail " + Q_LEAVE + " " + Q_WARRANTY
    env.ask(library["employee"], question)
    title = chats(env, library["employee"])[0]["title"]
    assert len(title) <= 61 and title.endswith("…") and question.startswith(title[:-1])


def test_follow_up_is_rewritten_using_the_conversation(env, library):
    emp = library["employee"]
    cid = env.ask(emp, Q_LEAVE).json()["conversation_id"]

    env.llm.prompts.clear()
    body = env.ask(emp, Q_FOLLOW_UP, cid).json()
    assert body["conversation_id"] == cid and "carried over for one year" in body["answer"]

    rewrite_prompt, answer_prompt = env.llm.prompts
    assert rewrite_prompt.startswith("Rewrite the follow-up question")
    assert f"User: {Q_LEAVE}" in rewrite_prompt and f"Follow-up question: {Q_FOLLOW_UP}" in rewrite_prompt
    assert Q_LEAVE in answer_prompt.split("Question:\n")[1]          # the standalone question was used
    # History is for the rewrite only: the answer prompt holds excerpts, never the transcript
    assert "User:" not in answer_prompt and "Assistant:" not in answer_prompt


def test_first_question_needs_no_rewrite_call(env, library):
    env.ask(library["employee"], Q_LEAVE)
    assert len(env.llm.prompts) == 1 and not env.llm.prompts[0].startswith("Rewrite")


def test_memory_window_is_limited_to_recent_turns(env, library):
    emp = library["employee"]
    cid = env.ask(emp, "Opening question about the Orbit-7 warranty period").json()["conversation_id"]
    for i in range(4):
        env.ask(emp, f"Filler question number {i} about annual leave days", cid)
    env.llm.prompts.clear()
    env.ask(emp, Q_FOLLOW_UP, cid)
    rewrite_prompt = env.llm.prompts[0]
    assert rewrite_prompt.count("User: ") == 3 and "Opening question" not in rewrite_prompt


def test_follow_ups_work_over_the_stream_too(env, library):
    emp = library["employee"]
    first = parse_sse(env.ask_stream(emp, Q_LEAVE).text)[-1][1]
    second = parse_sse(env.ask_stream(emp, Q_FOLLOW_UP, first["conversation_id"]).text)[-1][1]
    assert second["conversation_id"] == first["conversation_id"]
    assert "carried over for one year" in second["answer"]
    assert len(chats(env, emp)) == 1


def test_reopening_a_conversation_returns_messages_and_sources(env, library):
    emp = library["employee"]
    cid = env.ask(emp, Q_LEAVE).json()["conversation_id"]
    env.ask(emp, Q_FOLLOW_UP, cid)

    data = env.client.get(f"/conversations/{cid}", headers=emp).json()
    assert [m["role"] for m in data["messages"]] == ["user", "ai", "user", "ai"]
    assert data["messages"][0]["text"] == Q_LEAVE and data["messages"][2]["text"] == Q_FOLLOW_UP   # as typed
    assert data["messages"][1]["sources"][0]["filename"] == "Handbook.pdf"
    assert data["messages"][0]["sources"] == []


def test_list_is_ordered_by_most_recently_used(env, library):
    emp = library["employee"]
    first = env.ask(emp, Q_LEAVE).json()["conversation_id"]
    second = env.ask(emp, Q_WARRANTY).json()["conversation_id"]
    assert [c["id"] for c in chats(env, emp)] == [second, first]
    env.ask(emp, Q_FOLLOW_UP, first)
    assert [c["id"] for c in chats(env, emp)] == [first, second]


def test_conversations_are_private_even_from_admins(env, library):
    owner, other, admin = library["employee"], library["manager"], library["admin"]
    cid = env.ask(owner, Q_LEAVE).json()["conversation_id"]

    for intruder in (other, admin):
        assert chats(env, intruder) == []
        assert env.client.get(f"/conversations/{cid}", headers=intruder).status_code == 404
        assert env.ask(intruder, Q_FOLLOW_UP, cid).status_code == 404
        assert env.ask_stream(intruder, Q_FOLLOW_UP, cid).status_code == 404
        assert env.client.delete(f"/conversations/{cid}", headers=intruder).status_code == 404
        assert chats(env, intruder) == []                       # nothing was created for them either

    assert len(env.client.get(f"/conversations/{cid}", headers=owner).json()["messages"]) == 2
    assert env.ask(owner, Q_LEAVE, 999999).status_code == 404


def test_blocked_questions_are_not_saved(env, library):
    emp = library["employee"]
    assert env.ask(emp, Q_INJECTION).status_code == 400
    assert chats(env, emp) == []                                # no empty conversation left behind

    cid = env.ask(emp, Q_LEAVE).json()["conversation_id"]
    assert env.ask(emp, Q_INJECTION, cid).status_code == 400
    assert len(env.client.get(f"/conversations/{cid}", headers=emp).json()["messages"]) == 2


def test_owner_can_delete_a_conversation(env, library):
    emp = library["employee"]
    keep = env.ask(emp, Q_LEAVE).json()["conversation_id"]
    drop = env.ask(emp, Q_WARRANTY).json()["conversation_id"]
    assert env.client.delete(f"/conversations/{drop}", headers=emp).status_code == 200
    assert [c["id"] for c in chats(env, emp)] == [keep]
    assert env.client.get(f"/conversations/{drop}", headers=emp).status_code == 404
    assert env.ask(emp, Q_FOLLOW_UP, drop).status_code == 404


def test_memory_cannot_reach_restricted_documents(env, library):
    emp = library["employee"]
    cid = env.ask(emp, Q_LEAVE).json()["conversation_id"]
    for question in (Q_BOARD, Q_BONUS):
        body = env.ask(emp, question, cid).json()
        # Whatever it answers can only come from the handbook, the one document an employee may read
        assert not [w for w in ("Kestrel", "Lighthouse", "14 percent") if w in str(body)]
        assert {s["filename"] for s in body["sources"]} <= {"Handbook.pdf"}
    assert "Kestrel" not in "\n".join(env.llm.prompts) and "14 percent" not in "\n".join(env.llm.prompts)


def test_memory_does_not_reserve_content_after_access_is_revoked(env, library):
    manager, admin = library["manager"], library["admin"]
    first = env.ask(manager, Q_BONUS).json()
    cid = first["conversation_id"]
    assert "14 percent" in first["answer"]

    env.client.patch("/documents/Bonus.pdf/access", headers=admin, json={"allowed_roles": ["admin"]})

    env.llm.prompts.clear()
    again = env.ask(manager, "Remind me, what percent was that?", cid).json()
    assert again["answer"] == FALLBACK and again["sources"] == []
    # The follow-up's answer prompt must not contain the now-restricted excerpt
    assert not [p for p in env.llm.answer_prompts() if "14 percent" in p]

    reopened = env.client.get(f"/conversations/{cid}", headers=manager).json()["messages"]
    assert all(s["filename"] != "Bonus.pdf" for m in reopened for s in m["sources"])   # excerpts hidden
