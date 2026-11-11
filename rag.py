# rag.py
import os
import re

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from access import role_filter
from guardrails import FALLBACK_ANSWER, build_strict_prompt, check_pii_in_response
from vector_store import get_vectorstore

load_dotenv()

# Groq retires models from time to time (llama-3.3-70b-versatile is gone),
# so the model is set in .env rather than hardcoded. See the current list at
# https://console.groq.com/docs/models
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
llm = ChatGroq(model=GROQ_MODEL, temperature=0)

TOP_K = 3
# Chroma returns a squared-L2 distance (0 = identical). With the normalised
# MiniLM embeddings, 1.6 is roughly a cosine similarity of 0.2. Chunks further
# away than this count as weak matches. Tune with RETRIEVAL_MAX_DISTANCE.
MAX_DISTANCE = float(os.getenv("RETRIEVAL_MAX_DISTANCE", "1.6"))

SNIPPET_CHARS = 240
CITATION_RE = re.compile(r"\[(\d+)\]")


def _page_number(metadata: dict):
    """PyPDFLoader stores a 0-based page index; people count from 1."""
    page = metadata.get("page")
    return page + 1 if isinstance(page, int) else None


def _build_source(number: int, doc) -> dict:
    text = " ".join(doc.page_content.split())
    snippet = text[:SNIPPET_CHARS].rstrip() + ("…" if len(text) > SNIPPET_CHARS else "")
    # Snippets are raw document text, so they get the same PII redaction as answers
    snippet, _ = check_pii_in_response(snippet)
    return {
        "id":       number,
        "filename": doc.metadata.get("filename") or "Unknown document",
        "page":     _page_number(doc.metadata),
        "snippet":  snippet,
    }


def _build_context(docs) -> str:
    """Number every chunk so the model can cite it as [1], [2], ..."""
    blocks = []
    for number, doc in enumerate(docs, start=1):
        page = _page_number(doc.metadata)
        where = doc.metadata.get("filename") or "Unknown document"
        if page:
            where += f", page {page}"
        blocks.append(f"[{number}] ({where})\n{doc.page_content}")
    return "\n\n".join(blocks)


def get_answer(question: str, user_role: str) -> dict:
    """Returns answer + cited sources + metadata for monitoring."""
    db = get_vectorstore()

    # Document-level RBAC: the search itself only sees chunks this role is
    # allowed to read, so restricted text can never end up in the prompt
    # (and therefore never in the answer or its sources either).
    scored_docs = db.similarity_search_with_score(
        question, k=TOP_K, filter=role_filter(user_role)
    )

    # Keep only the strongly matching chunks when there are any, so weak
    # neighbours do not dilute the context. Broad requests such as
    # "summarize this document" match nothing strongly (they score the same as
    # an unrelated question), so in that case pass the top chunks through and
    # let the strict prompt decide whether the context answers the question.
    strong_docs = [doc for doc, distance in scored_docs if distance <= MAX_DISTANCE]
    retrieved_docs = strong_docs or [doc for doc, _ in scored_docs]
    chunks_retrieved = len(retrieved_docs)

    if not retrieved_docs:
        return {
            "answer":           FALLBACK_ANSWER,
            "sources":          [],
            "chunks_retrieved": 0,
        }

    prompt = build_strict_prompt(_build_context(retrieved_docs), question)

    response   = llm.invoke(prompt)
    raw_answer = str(response.content).strip()

    cleaned_answer, pii_found = check_pii_in_response(raw_answer)

    if pii_found:
        print(f"[GUARDRAIL] PII redacted: {pii_found}")

    # ── Citations ─────────────────────────────────────────────────
    if FALLBACK_ANSWER in cleaned_answer:
        # Nothing was answered, so there is nothing to cite
        cleaned_answer, sources = FALLBACK_ANSWER, []
    else:
        all_sources = [_build_source(n, d) for n, d in enumerate(retrieved_docs, start=1)]
        cited = {int(n) for n in CITATION_RE.findall(cleaned_answer)}
        sources = [s for s in all_sources if s["id"] in cited]
        if not sources:
            # The model answered without markers: show everything it was given
            sources = all_sources
        # Drop markers that point at nothing (a hallucinated "[7]")
        valid = {s["id"] for s in all_sources}
        cleaned_answer = CITATION_RE.sub(
            lambda m: m.group(0) if int(m.group(1)) in valid else "", cleaned_answer
        )

    return {
        "answer":           cleaned_answer,
        "sources":          sources,
        "chunks_retrieved": chunks_retrieved,
    }
