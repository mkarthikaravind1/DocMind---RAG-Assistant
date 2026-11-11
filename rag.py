# rag.py
import os

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from guardrails import FALLBACK_ANSWER, build_strict_prompt, check_pii_in_response
from vector_store import get_vectorstore

load_dotenv()

llm = ChatGroq(model="llama-3.3-70b-versatile")

TOP_K = 3
# Chroma returns a squared-L2 distance (0 = identical). With the normalised
# MiniLM embeddings, 1.6 is roughly a cosine similarity of 0.2. Chunks further
# away than this are treated as irrelevant. Tune with RETRIEVAL_MAX_DISTANCE.
MAX_DISTANCE = float(os.getenv("RETRIEVAL_MAX_DISTANCE", "1.6"))


def get_answer(question: str) -> dict:
    """Returns answer + metadata for monitoring."""
    db = get_vectorstore()

    scored_docs = db.similarity_search_with_score(question, k=TOP_K)
    retrieved_docs = [doc for doc, distance in scored_docs if distance <= MAX_DISTANCE]
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
