# retrieval.py
# Hybrid retrieval: vector search + BM25 keyword search, fused, then reranked.
#
#   1. Vector search   - finds chunks that MEAN the same as the question.
#   2. Keyword search  - BM25 finds chunks that contain the question's exact
#                        words (part codes, names, numbers), which embeddings
#                        are weak at.
#   3. Fusion          - the two rankings are merged with Reciprocal Rank Fusion.
#   4. Reranking       - a cross-encoder reads the question together with each
#                        candidate and scores how well it answers it. The best
#                        TOP_K chunks go into the prompt.
#
# Document-level RBAC: BOTH searches run with the asker's role filter inside
# Chroma, and the reranker only ever sees their union. Text a role may not read
# is therefore never a candidate, so it cannot reach the reranker or the LLM.
import heapq
import math
import os
import re
import threading
import time
import unicodedata
from collections import Counter

from dotenv import load_dotenv
from langchain_core.documents import Document

from access import role_filter
from vector_store import get_vectorstore

load_dotenv()

TOP_K = 3            # chunks that go into the prompt
CANDIDATES = 15      # taken from EACH search before fusion (so at most 30 are reranked)
RRF_K = 60           # standard Reciprocal Rank Fusion constant
BM25_K1 = 1.5
BM25_B = 0.75

RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
# Set RERANK_ENABLED=0 to skip the cross-encoder and use the fused order as is
RERANK_ENABLED = os.getenv("RERANK_ENABLED", "1") == "1"
RERANKER_RETRY_SECONDS = 300    # after a failed load, wait this long before trying again

_TOKEN_RE = re.compile(r"[^\W_]+")

# Question words that say nothing about the topic. Only used for the query;
# BM25's own weighting already plays down common words inside documents.
_QUERY_STOPWORDS = frozenset("""
a about all also am an and any are as at be been but by can could did do does for from
give had has have how i if in into is it its me my of on or our please shall should so
tell than that the their them then there these they this those to us was we were what
when where which who whom whose why will with would you your
""".split())


def tokenize(text: str) -> list[str]:
    """
    Lower-cased words and numbers. NFKC folds the non-breaking spaces and other
    look-alike characters that PDFs and LLMs produce, and every kind of hyphen
    is a separator, so "Orbit‑7" (non-breaking hyphen) gives ["orbit", "7"].
    """
    return _TOKEN_RE.findall(unicodedata.normalize("NFKC", text).lower())


def query_terms(question: str) -> list[str]:
    return [t for t in dict.fromkeys(tokenize(question)) if t not in _QUERY_STOPWORDS]


# ── Keyword search (BM25) ───────────────────────────────────────────
# Tokenised chunk text, cached by chunk id. A chunk's text never changes
# (re-uploading a file creates new ids), so this is safe to keep. What is
# deliberately NOT cached is which chunks a role may read: that list is asked
# from Chroma on every question, so access changes and deletes apply at once.
_term_cache: dict[str, tuple[Counter, int]] = {}
_term_cache_lock = threading.Lock()
_TERM_CACHE_MAX = 50_000
_FETCH_BATCH = 500


def _load_terms(collection, ids: list[str], where: dict) -> None:
    missing = [i for i in ids if i not in _term_cache]
    if not missing:
        return
    loaded = {}
    for start in range(0, len(missing), _FETCH_BATCH):
        # The role filter is repeated here, so even this fetch cannot return
        # text the asker's role may not read.
        got = collection.get(
            ids=missing[start:start + _FETCH_BATCH], where=where, include=["documents"]
        )
        for chunk_id, text in zip(got.get("ids") or [], got.get("documents") or []):
            tokens = tokenize(text or "")
            loaded[chunk_id] = (Counter(tokens), len(tokens))
    with _term_cache_lock:
        if len(_term_cache) + len(loaded) > _TERM_CACHE_MAX:
            _term_cache.clear()
        _term_cache.update(loaded)


def bm25_rank(terms: list[str], docs: list[tuple[str, Counter, int]], k: int) -> list[str]:
    """
    Okapi BM25 over docs given as (id, term counts, length). Returns the ids of
    the best k docs that contain at least one query term, best first.
    The IDF is the always-positive variant (as in Lucene), so a term found in
    most of a small collection still counts a little instead of scoring zero.
    """
    if not terms or not docs:
        return []
    n = len(docs)
    avg_len = (sum(length for _, _, length in docs) / n) or 1.0
    idf = {}
    for term in terms:
        df = sum(1 for _, counts, _ in docs if term in counts)
        if df:
            idf[term] = math.log(1 + (n - df + 0.5) / (df + 0.5))

    scored = []
    for chunk_id, counts, length in docs:
        score = 0.0
        for term, weight in idf.items():
            tf = counts.get(term, 0)
            if tf:
                score += weight * tf * (BM25_K1 + 1) / (
                    tf + BM25_K1 * (1 - BM25_B + BM25_B * length / avg_len)
                )
        if score > 0:
            scored.append((score, chunk_id))
    # Highest score first; ties broken by id so the order is repeatable
    return [chunk_id for _, chunk_id in heapq.nsmallest(k, scored, key=lambda s: (-s[0], s[1]))]


def keyword_search(question: str, user_role: str, k: int = CANDIDATES) -> list[Document]:
    """BM25 over the chunks this role may read. Best first."""
    terms = query_terms(question)
    if not terms:
        return []

    collection = get_vectorstore()._collection
    where = role_filter(user_role)
    # Asked fresh every time: the chunks this role may read right now
    ids = collection.get(where=where, include=[]).get("ids") or []
    if not ids:
        return []
    _load_terms(collection, ids, where)

    docs = [(i, *_term_cache[i]) for i in ids if i in _term_cache]
    best = bm25_rank(terms, docs, k)
    if not best:
        return []

    got = collection.get(ids=best, where=where, include=["documents", "metadatas"])
    found = {
        chunk_id: Document(page_content=text or "", metadata=meta or {}, id=chunk_id)
        for chunk_id, text, meta in zip(got["ids"], got["documents"], got["metadatas"])
    }
    return [found[i] for i in best if i in found]


# ── Vector search ───────────────────────────────────────────────────
def vector_search(question: str, user_role: str, k: int = CANDIDATES) -> list[Document]:
    """Embedding similarity over the chunks this role may read. Best first."""
    scored = get_vectorstore().similarity_search_with_score(
        question, k=k, filter=role_filter(user_role)
    )
    return [doc for doc, _ in scored]


# ── Fusion ──────────────────────────────────────────────────────────
def reciprocal_rank_fusion(rankings: list[list[str]]) -> list[str]:
    """
    Merge several best-first lists of keys into one. Each list gives a key
    1 / (RRF_K + rank); keys found by more than one search add up. Only ranks
    are used, so the two searches' very different score scales do not matter.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
    order = {key: n for n, key in enumerate(scores)}      # first seen, for stable ties
    return sorted(scores, key=lambda key: (-scores[key], order[key]))


# ── Reranking ───────────────────────────────────────────────────────
class CrossEncoderReranker:
    """Scores (question, passage) pairs with a small cross-encoder on CPU."""

    def __init__(self, model_name: str):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name, max_length=512)

    def score(self, question: str, passages: list[str]) -> list[float]:
        pairs = [(question, passage) for passage in passages]
        return [float(s) for s in self.model.predict(pairs, show_progress_bar=False)]


_reranker = None
_reranker_retry_at = 0.0
_reranker_lock = threading.Lock()


def get_reranker():
    """
    The reranker, loaded once. Returns None when it cannot be loaded (for
    example no network on first start); the caller then keeps the fused order.
    A failed load is not retried on every question, only every few minutes.
    """
    global _reranker, _reranker_retry_at
    if _reranker is not None:
        return _reranker
    with _reranker_lock:
        if _reranker is not None:
            return _reranker
        if time.monotonic() < _reranker_retry_at:
            return None
        try:
            _reranker = CrossEncoderReranker(RERANKER_MODEL)
        except Exception as e:
            print(f"[RETRIEVAL] Reranker could not be loaded, using fused order: {e}")
            _reranker_retry_at = time.monotonic() + RERANKER_RETRY_SECONDS
            return None
    return _reranker


def warm_up() -> None:
    """Load the reranker before the first question (called at startup)."""
    if not RERANK_ENABLED:
        return
    reranker = get_reranker()
    if reranker is not None:
        try:
            reranker.score("warm up", ["warm up"])
        except Exception as e:
            print(f"[RETRIEVAL] Reranker warm-up failed: {e}")


def rerank(question: str, docs: list[Document]) -> tuple[list[Document], bool]:
    """
    Reorder docs by how well each answers the question. Returns (docs, reranked).
    Any failure leaves the given (fused) order untouched, so chat keeps working.
    """
    if not RERANK_ENABLED or len(docs) < 2:
        return docs, False
    try:
        reranker = get_reranker()
        if reranker is None:
            return docs, False
        scores = reranker.score(question, [d.page_content for d in docs])
        if len(scores) != len(docs):
            raise ValueError("reranker returned the wrong number of scores")
        order = sorted(range(len(docs)), key=lambda i: (-scores[i], i))
        return [docs[i] for i in order], True
    except Exception as e:
        print(f"[RETRIEVAL] Reranking failed, using fused order: {e}")
        return docs, False


# ── The whole pipeline ──────────────────────────────────────────────
def _key(doc: Document) -> str:
    return doc.id or f"{doc.metadata.get('filename')}|{doc.metadata.get('page')}|{doc.page_content}"


def hybrid_search(question: str, user_role: str, top_k: int = TOP_K) -> list[Document]:
    """
    The chunks this role may read that best answer the question.

    There is deliberately no relevance cut-off: a broad request such as
    "summarize this document" matches nothing strongly, so the best candidates
    are always passed on and the strict prompt decides whether they answer it.
    """
    start = time.time()
    by_vector = vector_search(question, user_role)
    try:
        by_keyword = keyword_search(question, user_role)
    except Exception as e:
        # Keyword search is an addition: if it breaks, vector search still answers
        print(f"[RETRIEVAL] Keyword search failed, using vector search only: {e}")
        by_keyword = []

    docs = {}
    for doc in by_vector + by_keyword:
        docs.setdefault(_key(doc), doc)
    fused = reciprocal_rank_fusion([[_key(d) for d in by_vector], [_key(d) for d in by_keyword]])
    candidates = [docs[key] for key in fused]

    ranked, reranked = rerank(question, candidates)
    print(
        f"[RETRIEVAL] vector={len(by_vector)} keyword={len(by_keyword)} "
        f"candidates={len(candidates)} reranked={reranked} "
        f"time={round((time.time() - start) * 1000)}ms"
    )
    return ranked[:top_k]
