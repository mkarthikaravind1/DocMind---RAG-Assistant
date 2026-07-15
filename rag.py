# rag.py
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_groq import ChatGroq
from dotenv import load_dotenv
from guardrails import check_pii_in_response, build_strict_prompt
import os
import chromadb
from chromadb.config import Settings

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
VECTORSTORE_DIR = os.path.join(BASE_DIR, "vectorstore")

load_dotenv()

embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
llm        = ChatGroq(model="llama-3.3-70b-versatile")

def get_answer(question: str) -> dict:
    """Returns answer + metadata for monitoring."""
    db = Chroma(
        persist_directory=VECTORSTORE_DIR,
        embedding_function=embeddings,
        collection_name="rag_docs"
    )

    retrieved_docs = db.similarity_search(question, k=3)
    chunks_retrieved = len(retrieved_docs)

    if not retrieved_docs:
        return {
            "answer":          "Hello ABC ",
            "chunks_retrieved": 0,  
        }

    context = "\n".join([doc.page_content for doc in retrieved_docs])
    prompt  = build_strict_prompt(context, question)

    response    = llm.invoke(prompt)
    raw_answer  = str(response.content)

    cleaned_answer, pii_found = check_pii_in_response(raw_answer)

    if pii_found:
        print(f"[GUARDRAIL] PII redacted: {pii_found}")

    return {
        "answer":           cleaned_answer,
        "chunks_retrieved": chunks_retrieved,
    }


def get_chroma_client():
    chroma_host = os.getenv("CHROMA_HOST", "localhost")
    chroma_port = int(os.getenv("CHROMA_PORT", "8001"))
    return chromadb.HttpClient(
        host=chroma_host,
        port=chroma_port,
        settings=Settings(anonymized_telemetry=False)
    )
