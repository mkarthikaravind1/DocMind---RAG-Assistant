# rag.py
import os
import re

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from access import role_filter
from guardrails import (
    FALLBACK_ANSWER,
    MAX_INPUT_LENGTH,
    StreamingRedactor,
    build_strict_prompt,
    check_pii_in_response,
    check_prompt_injection,
)
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


def condense_question(question: str, history) -> str:
    """
    Conversation memory: rewrite a follow-up ("from when does it start?") into
    a question that makes sense on its own, using the recent turns.

    History is used ONLY here. The answer itself is still built from freshly
    retrieved, access-filtered excerpts, so memory can never re-serve text from
    a document the user has since lost access to.
    """
    if not history:
        return question

    transcript = "\n".join(
        f"{'User' if role == 'user' else 'Assistant'}: {content[:500]}"
        for role, content in history
    )
    prompt = f"""Rewrite the follow-up question so it can be understood without the conversation.

Rules:
- Replace words like "it", "that", "they", "there" with what they refer to.
- If the follow-up is already clear on its own, return it unchanged.
- Do NOT answer the question. Do NOT add facts or numbers from the conversation.
- Output only the rewritten question on one line, nothing else.

Conversation:
{transcript}

Follow-up question: {question}

Standalone question:"""

    try:
        rewritten = str(llm.invoke(prompt).content).strip().strip('"').strip()
    except Exception as e:
        print(f"[MEMORY] Could not rewrite follow-up, using it as asked: {e}")
        return question

    # Anything odd (empty, huge, or looking like an injection) falls back to the original
    if not rewritten or len(rewritten) > MAX_INPUT_LENGTH or check_prompt_injection(rewritten):
        return question
    return " ".join(rewritten.split())


def _retrieve(question: str, user_role: str) -> list:
    """Chunks this role may read that best match the question."""
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
    return strong_docs or [doc for doc, _ in scored_docs]


def _finalize(cleaned_answer: str, retrieved_docs: list) -> dict:
    """Turn an already-redacted answer into the final answer + cited sources."""
    cleaned_answer = cleaned_answer.strip()

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
        "chunks_retrieved": len(retrieved_docs),
    }


NO_CONTEXT_RESULT = {"answer": FALLBACK_ANSWER, "sources": [], "chunks_retrieved": 0}


def get_answer(question: str, user_role: str, history=None) -> dict:
    """Returns answer + cited sources + metadata for monitoring."""
    question = condense_question(question, history)
    retrieved_docs = _retrieve(question, user_role)
    if not retrieved_docs:
        return dict(NO_CONTEXT_RESULT)

    prompt   = build_strict_prompt(_build_context(retrieved_docs), question)
    response = llm.invoke(prompt)

    cleaned_answer, pii_found = check_pii_in_response(str(response.content))
    if pii_found:
        print(f"[GUARDRAIL] PII redacted: {pii_found}")

    return _finalize(cleaned_answer, retrieved_docs)


def stream_answer(question: str, user_role: str, history=None):
    """
    Generator version of get_answer for live streaming.

    Yields ("token", text) for each piece of the answer that is safe to show,
    then exactly one ("done", result) with the same dict get_answer returns.
    Everything yielded has already been through PII redaction.
    """
    question = condense_question(question, history)
    retrieved_docs = _retrieve(question, user_role)
    if not retrieved_docs:
        yield "token", FALLBACK_ANSWER
        yield "done", dict(NO_CONTEXT_RESULT)
        return

    prompt   = build_strict_prompt(_build_context(retrieved_docs), question)
    redactor = StreamingRedactor()
    parts    = []

    for chunk in llm.stream(prompt):
        piece = chunk.content if isinstance(chunk.content, str) else ""
        if not piece:
            continue
        safe = redactor.feed(piece)
        if safe:
            parts.append(safe)
            yield "token", safe

    tail = redactor.flush()
    if tail:
        parts.append(tail)
        yield "token", tail

    if redactor.found:
        print(f"[GUARDRAIL] PII redacted: {redactor.found}")

    yield "done", _finalize("".join(parts), retrieved_docs)
