from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from dotenv import load_dotenv
import os
import chromadb
from chromadb.config import Settings

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VECTORSTORE_DIR = os.path.join(BASE_DIR, "vectorstore")
DOCUMENTS_DIR   = os.path.join(BASE_DIR, "documents")

load_dotenv()

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

def ingest_pdf(file_path: str):
    """Load, chunk, embed, and store a PDF in the vectorstore."""
    loader = PyPDFLoader(file_path)
    docs = loader.load()

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(docs)

    client = get_chroma_client()

    # db = Chroma.from_documents(
    #     chunks,
    #     embeddings,
    #     persist_directory=VECTORSTORE_DIR,
    #     collection_name="rag_docs"
    # )
    db = Chroma(
        client=client,
        collection_name="rag_docs",
        embedding_function=embeddings,
    )
    db.add_documents(chunks)


    print(f"Stored {len(chunks)} chunks from {file_path}")
    return len(chunks)

def get_chroma_client():
    chroma_host = os.getenv("CHROMA_HOST", "localhost")
    chroma_port = int(os.getenv("CHROMA_PORT", "8001"))
    return chromadb.HttpClient(
        host=chroma_host,
        port=chroma_port,
        settings=Settings(anonymized_telemetry=False)
    )
