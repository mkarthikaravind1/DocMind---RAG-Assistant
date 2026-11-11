# rag.py
import os

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


def get_answer(question: str, user_role: str) -> dict:
    """Returns answer + metadata for monitoring."""
    db = get_vectorstore()

    # Document-level RBAC: the search itself only sees chunks this role is
    # allowed to read, so restricted text can never end up in the prompt.
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
            "chunks_retrieved": 0,
        }

    context = "\n".join([doc.page_content for doc in retrieved_docs])
    prompt  = build_strict_prompt(context, question)

    response   = llm.invoke(prompt)
    raw_answer = str(response.content)

    cleaned_answer, pii_found = check_pii_in_response(raw_answer)

    if pii_found:
        print(f"[GUARDRAIL] PII redacted: {pii_found}")

    return {
        "answer":           cleaned_answer,
        "chunks_retrieved": chunks_retrieved,
    }
