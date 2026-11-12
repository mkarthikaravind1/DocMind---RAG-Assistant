"""Hybrid retrieval: BM25 keyword search, rank fusion, reranking and their access control."""
from collections import Counter

import pytest

import retrieval
from conftest import BOARD, FALLBACK, Q_BOARD, Q_BONUS, Q_LEAVE, parse_sse

# A parts list built so that ONLY keyword search can find the answer:
# the stand-in embeddings ignore short words, so "K31" and "bay" are invisible
# to vector search, while thirty other pages share the word "location" with
# the question and fill every vector-search slot.
SECRET_BIN = "4417"
PARTS = [[f"Location note {n}: this aisle location is kept dry."] for n in range(1, 31)]
PARTS.append([f"K31 is in bin {SECRET_BIN} of bay 9."])
Q_PART = "K31 bay location?"


def texts(docs):
    return "\n".join(d.page_content for d in docs)


def contexts(prompt):
    """The document excerpts inside an answer prompt, without the user's question."""
    if "Context:\n" not in prompt:
        return ""
    return prompt.split("Context:\n", 1)[1].split("\n\nQuestion:\n", 1)[0]


# ── Tokeniser ─────────────────────────────────────────────────────────────
def test_tokenizer_handles_case_unicode_hyphens_and_non_breaking_spaces():
    assert retrieval.tokenize("Orbit-7 ARM") == ["orbit", "7", "arm"]
    # non-breaking hyphen, en dash, non-breaking space, narrow no-break space
    assert retrieval.tokenize("Orbit‑7 – 630 crore rupees") == ["orbit", "7", "630", "crore", "rupees"]
    assert retrieval.tokenize("snake_case, e-mail!") == ["snake", "case", "e", "mail"]
    assert retrieval.tokenize("") == []


def test_query_terms_drop_question_words_and_duplicates():
    assert retrieval.query_terms("What is the warranty of the Orbit-7? Warranty!") == ["warranty", "orbit", "7"]
    assert retrieval.query_terms("What is this about?") == []


# ── BM25 and fusion (pure functions) ──────────────────────────────────────
def _docs(*passages):
    out = []
    for n, text in enumerate(passages):
        tokens = retrieval.tokenize(text)
        out.append((f"d{n}", Counter(tokens), len(tokens)))
    return out


def test_bm25_prefers_the_rare_exact_term():
    docs = _docs(
        "the pump manual covers the pump and the pump housing",
        "serial ZX900 belongs to the backup pump",
        "nothing relevant here at all",
    )
    assert retrieval.bm25_rank(["zx900", "pump"], docs, k=5) == ["d1", "d0"]   # d2 has no query term
    assert retrieval.bm25_rank(["zx900", "pump"], docs, k=1) == ["d1"]
    assert retrieval.bm25_rank(["tungsten"], docs, k=5) == []
    assert retrieval.bm25_rank([], docs, k=5) == [] == retrieval.bm25_rank(["pump"], [], k=5)


def test_bm25_still_scores_a_term_found_in_most_documents():
    """With a negative-capable IDF, a word in 2 of 3 chunks would score zero and vanish."""
    docs = _docs("leave policy", "leave form", "travel form")
    assert set(retrieval.bm25_rank(["leave"], docs, k=5)) == {"d0", "d1"}


def test_rank_fusion_rewards_agreement_between_the_two_searches():
    fused = retrieval.reciprocal_rank_fusion([["a", "b", "c"], ["c", "d"]])
    assert fused[0] == "c"                        # found by both
    assert set(fused) == {"a", "b", "c", "d"}
    assert fused.index("a") < fused.index("b")    # order inside one list is kept
    assert retrieval.reciprocal_rank_fusion([[], []]) == []


# ── Keyword search finds what vector search cannot ────────────────────────
def test_keyword_search_finds_an_exact_code_that_vector_search_misses(env, people):
    assert env.upload(people["admin"], "Parts.pdf", PARTS).status_code == 200
    assert env.chunk_count() == 31

    assert SECRET_BIN not in texts(retrieval.vector_search(Q_PART, "employee"))
    assert SECRET_BIN in retrieval.keyword_search(Q_PART, "employee")[0].page_content

    top = retrieval.hybrid_search(Q_PART, "employee")
    assert len(top) == retrieval.TOP_K
    assert SECRET_BIN in top[0].page_content      # reranked to first place

    env.ask(people["employee"], Q_PART)
    assert SECRET_BIN in env.llm.prompts[-1]      # and it reaches the model through /chat


def test_without_keyword_search_the_same_question_misses(env, people, monkeypatch):
    """The control for the test above: the hit really comes from BM25."""
    env.upload(people["admin"], "Parts.pdf", PARTS)
    monkeypatch.setattr(retrieval, "keyword_search", lambda *a, **k: [])
    env.ask(people["employee"], Q_PART)
    assert SECRET_BIN not in env.llm.prompts[-1]


def test_only_the_top_chunks_reach_the_prompt(env, people):
    env.upload(people["admin"], "Parts.pdf", PARTS)
    env.ask(people["employee"], Q_PART)
    prompt = env.llm.prompts[-1]
    assert f"[{retrieval.TOP_K}] (Parts.pdf" in prompt
    assert f"[{retrieval.TOP_K + 1}] (" not in prompt
    # ...although many more candidates were compared by the reranker
    assert retrieval.TOP_K < len(env.reranker.passages) <= 2 * retrieval.CANDIDATES


def test_keyword_search_matches_despite_unicode_hyphens_in_the_question(env, library):
    docs = retrieval.keyword_search("warranty of the Orbit‑7 robotic arm", "employee")
    assert docs and "42 months" in docs[0].page_content


def test_a_reuploaded_document_is_searched_by_its_new_text(env, people):
    env.upload(people["admin"], "Parts.pdf", PARTS)
    assert SECRET_BIN in texts(retrieval.keyword_search(Q_PART, "admin"))       # fills the cache

    env.upload(people["admin"], "Parts.pdf", [["K31 is in bin 5520 of bay 2."]])
    found = texts(retrieval.keyword_search(Q_PART, "admin"))
    assert "5520" in found and SECRET_BIN not in found


# ── Document-level access control on the new code paths ───────────────────
EXACT_BOARD = "Kestrel Aerial Project Lighthouse 630 crore acquisition"     # the document's own words


@pytest.mark.parametrize("role, allowed", [("employee", False), ("manager", False), ("admin", True)])
def test_keyword_search_is_filtered_by_role(env, library, role, allowed):
    found = texts(retrieval.keyword_search(EXACT_BOARD, role))
    assert ("Kestrel" in found) is allowed
    found = texts(retrieval.hybrid_search(EXACT_BOARD, role))
    assert ("Kestrel" in found) is allowed


def test_restricted_text_never_reaches_the_reranker_or_the_llm(env, library):
    for question in (EXACT_BOARD, Q_BOARD, Q_BONUS, "manager bonus pool 14 percent April"):
        env.ask(library["employee"], question)
        env.ask_stream(library["employee"], question)
    assert env.reranker.passages and env.llm.prompts
    # The questions themselves contain these words, so look only at document
    # text: what the reranker was given, and the excerpts inside each prompt.
    seen = "\n".join(env.reranker.passages + [contexts(p) for p in env.llm.prompts])
    for word in ("Kestrel", "Lighthouse", "630 crore", "14 percent", "paid out"):
        assert word not in seen, word


def test_revoking_access_applies_at_once_even_with_a_warm_keyword_cache(env, library):
    assert "14 percent" in texts(retrieval.keyword_search(Q_BONUS, "manager"))   # fills the cache
    assert "14 percent" in env.ask(library["manager"], Q_BONUS).json()["answer"]

    r = env.client.patch("/documents/Bonus.pdf/access", headers=library["admin"], json={"allowed_roles": ["admin"]})
    assert r.status_code == 200
    env.llm.prompts.clear()
    env.reranker.passages.clear()

    assert "14 percent" not in texts(retrieval.keyword_search(Q_BONUS, "manager"))
    assert env.ask(library["manager"], Q_BONUS).json()["answer"] == FALLBACK
    assert "14 percent" not in "\n".join(env.reranker.passages + env.llm.prompts)
    assert "14 percent" in env.ask(library["admin"], Q_BONUS).json()["answer"]   # admins keep it


def test_a_deleted_document_leaves_keyword_search_at_once(env, library):
    assert "Kestrel" in texts(retrieval.keyword_search(EXACT_BOARD, "admin"))    # fills the cache
    assert env.client.delete("/delete/Board.pdf", headers=library["admin"]).status_code == 200
    assert "Kestrel" not in texts(retrieval.hybrid_search(EXACT_BOARD, "admin"))


def test_an_unknown_role_is_rejected_by_both_searches(env, library):
    for search in (retrieval.keyword_search, retrieval.vector_search, retrieval.hybrid_search):
        with pytest.raises(ValueError):
            search(Q_LEAVE, "superuser")


# ── Reranker: ordering, failure and the off switch ────────────────────────
def test_the_reranker_decides_the_final_order(env, library, monkeypatch):
    first = retrieval.hybrid_search(Q_LEAVE, "employee")[0]
    assert "27 days" in first.page_content

    # A reranker with the opposite taste puts that chunk last
    real = env.reranker.score
    monkeypatch.setattr(env.reranker, "score", lambda q, passages: [-s for s in real(q, passages)])
    assert "27 days" not in retrieval.hybrid_search(Q_LEAVE, "employee")[0].page_content


def test_chat_still_answers_when_the_reranker_fails(env, library):
    env.reranker.fail = True
    body = env.ask(library["employee"], Q_LEAVE).json()
    assert "27 days" in body["answer"] and body["sources"]
    assert env.reranker.calls == 1

    done = parse_sse(env.ask_stream(library["employee"], Q_LEAVE).text)[-1]
    assert done[0] == "done" and "27 days" in done[1]["answer"]


def test_chat_still_answers_when_the_reranker_cannot_be_loaded(env, library, monkeypatch):
    monkeypatch.setattr(retrieval, "get_reranker", lambda: None)
    assert "27 days" in env.ask(library["employee"], Q_LEAVE).json()["answer"]


def test_a_failed_reranker_load_is_not_retried_on_every_question(monkeypatch):
    attempts = []

    def broken(model_name):
        attempts.append(model_name)
        raise OSError("no network")

    monkeypatch.setattr(retrieval, "CrossEncoderReranker", broken)
    monkeypatch.setattr(retrieval, "_reranker", None)
    monkeypatch.setattr(retrieval, "_reranker_retry_at", 0.0)
    assert retrieval.get_reranker() is None and retrieval.get_reranker() is None
    assert len(attempts) == 1


def test_reranking_can_be_switched_off(env, library, monkeypatch):
    monkeypatch.setattr(retrieval, "RERANK_ENABLED", False)
    assert "27 days" in env.ask(library["employee"], Q_LEAVE).json()["answer"]
    assert env.reranker.calls == 0


def test_chat_still_answers_when_keyword_search_breaks(env, library, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("simulated keyword search failure")
    monkeypatch.setattr(retrieval, "keyword_search", boom)
    assert "27 days" in env.ask(library["employee"], Q_LEAVE).json()["answer"]


# ── No hard relevance cut-off ─────────────────────────────────────────────
def test_a_generic_request_still_sends_excerpts_to_the_model(env, library):
    """"Summarize this document" matches nothing strongly; it must not be cut off before the LLM."""
    env.ask(library["employee"], "Summarize this document")
    prompts = env.llm.answer_prompts()
    assert len(prompts) == 1 and "[1] (Handbook.pdf" in prompts[0]

    logs = env.client.get("/admin/logs", headers=library["admin"]).json()
    assert logs[0]["chunks_retrieved"] >= 1


def test_nothing_to_search_returns_nothing(env, people):
    assert retrieval.hybrid_search(Q_LEAVE, "employee") == []
    assert retrieval.keyword_search(Q_LEAVE, "employee") == []
    assert env.reranker.calls == 0


def test_board_fixture_words_are_what_the_access_tests_look_for():
    assert "Kestrel" in " ".join(BOARD[0]) and "Lighthouse" in " ".join(BOARD[0])
