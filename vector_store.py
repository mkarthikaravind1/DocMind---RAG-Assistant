# vector_store.py
# Single place that owns the embedding model and the Chroma connection,
# so ingest.py and rag.py always read and write the SAME collection.
import os
from functools import lru_cache

import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv
from langchain_chroma import Chroma

load_dotenv()

COLLECTION_NAME = "rag_docs"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_embeddings():
    """
    The embedding model, loaded once and shared by ingestion and retrieval.
    Loaded on first use (the app warms it up at startup), which also lets the
    test suite swap in a lightweight stand-in without downloading the model.
    """
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


def get_chroma_client():
    chroma_host = os.getenv("CHROMA_HOST", "localhost")
    chroma_port = int(os.getenv("CHROMA_PORT", "8001"))
    return chromadb.HttpClient(
        host=chroma_host,
        port=chroma_port,
        settings=Settings(anonymized_telemetry=False),
    )


def get_vectorstore() -> Chroma:
    return Chroma(
        client=get_chroma_client(),
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
    )
