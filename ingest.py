import os

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from access import DEFAULT_ROLES, role_flags
from vector_store import get_vectorstore


class IngestError(Exception):
    """Raised when a PDF cannot be turned into searchable chunks."""


def delete_document_chunks(filename: str) -> None:
    """Remove every stored chunk that belongs to the given file."""
    db = get_vectorstore()
    db.delete(where={"filename": filename})


def set_document_roles(filename: str, allowed_roles) -> int:
    """
    Re-tag every chunk of a document with a new set of allowed roles.
    Returns the number of chunks updated.
    """
    collection = get_vectorstore()._collection
    existing = collection.get(where={"filename": filename}, include=["metadatas"])
    ids = existing.get("ids") or []
    if not ids:
        return 0

    flags = role_flags(allowed_roles)
    metadatas = [{**(meta or {}), **flags} for meta in existing["metadatas"]]
    collection.update(ids=ids, metadatas=metadatas)
    return len(ids)


def ingest_pdf(file_path: str, allowed_roles=None) -> int:
    """Load, chunk, embed, and store a PDF in the vectorstore."""
    filename = os.path.basename(file_path)
    flags = role_flags(allowed_roles or DEFAULT_ROLES)

    loader = PyPDFLoader(file_path)
    docs = loader.load()

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = [c for c in splitter.split_documents(docs) if c.page_content.strip()]

    if not chunks:
        raise IngestError(
            "No readable text found in this PDF. Scanned/image-only PDFs are not supported."
        )

    # Tag every chunk with its filename (for citing/deleting) and with the
    # roles allowed to read it (for access-filtered retrieval)
    for chunk in chunks:
        chunk.metadata["filename"] = filename
        chunk.metadata.update(flags)

    db = get_vectorstore()
    # Re-uploading the same file replaces its chunks instead of duplicating them
    db.delete(where={"filename": filename})
    db.add_documents(chunks)

    print(f"Stored {len(chunks)} chunks from {file_path}")
    return len(chunks)
