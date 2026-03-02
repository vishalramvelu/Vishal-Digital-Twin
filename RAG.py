"""
RAG.py — loads profile chunks, embeds them, exposes a retriever tool for the agent.
"""

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("vishals-twin")

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings

MEMORY_DIR = Path(__file__).parent / "memory"
CHUNK_FILES = ["profile.json", "github.json"]


def _load_chunks() -> list[Document]:
    """Load chunks from all memory JSON files into LangChain Documents."""
    docs = []
    for filename in CHUNK_FILES:
        path = MEMORY_DIR / filename
        if not path.exists():
            log.warning("Memory file not found, skipping: %s", path)
            continue
        data = json.loads(path.read_text())
        for chunk in data["chunks"]:
            docs.append(
                Document(
                    page_content=chunk["text"],
                    metadata={
                        "id": chunk["id"],
                        "category": chunk["category"],
                        "tags": chunk["tags"],
                        "source_file": filename,
                    },
                )
            )
    log.info("Loaded %d chunks from %s", len(docs), CHUNK_FILES)
    return docs


def build_vectorstore() -> InMemoryVectorStore:
    """Build an in-memory vector store from profile chunks."""
    docs = _load_chunks()
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=os.environ["OPEN_AI_KEY"],
    )
    return InMemoryVectorStore.from_documents(docs, embeddings)


# singleton — built once at import time
vectorstore = build_vectorstore()
retriever = vectorstore.as_retriever(search_kwargs={"k": 8})


def query_profile(query: str) -> str:
    """Retrieve the most relevant profile chunks for a query.

    Args:
        query: natural-language question about Vishal's background,
               skills, experience, projects, goals, etc.

    Returns:
        Concatenated text of the top matching profile chunks.
    """
    t = time.perf_counter()
    docs = retriever.invoke(query)
    log.info("  [query_profile] retrieval %.2fs (%d chunks)", time.perf_counter() - t, len(docs))
    return "\n\n".join(doc.page_content for doc in docs)
