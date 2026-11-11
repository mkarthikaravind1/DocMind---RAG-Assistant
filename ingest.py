import os

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from vector_store import get_vectorstore


class IngestError(Exception):
    """Raised when a PDF cannot be turned into searchable chunks."""


def delete_document_chunks(filename: str) -> None:
    """Remove every stored chunk that belongs to the given file."""
    db = get_vectorstore()
    db.delete(where={"filename": filename})


def ingest_pdf(file_path: str) -> int:
    """Load, chunk, embed, and store a PDF in the vectorstore."""
    filename = os.path.basename(file_path)

    loader = PyPDFLoader(file_path)
    docs = loader.load()

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = [c for c in splitter.split_documents(docs) if c.page_content.strip()]

    if not chunks:
        raise IngestError(
            "No readable text found in this PDF. Scanned/image-only PDFs are not supported."
        )

    # Tag every chunk with its filename so it can be cited and deleted later
    for chunk in chunks:
        chunk.metadata["filename"] = filename

    db = get_vectorstore()
    # Re-uploading the same file replaces its chunks instead of duplicating them
    db.delete(where={"filename": filename})
    db.add_documents(chunks)

    print(f"Stored {len(chunks)} chunks from {file_path}")
    return len(chunks)
