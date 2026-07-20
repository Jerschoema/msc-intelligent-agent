"""Chunk store and semantic search, on top of LangChain's Chroma binding.

Refer to Langchain and Chroma docs for details.

"""

from pathlib import Path

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from src.config.settings import settings
from src.models import Chunk

_COLLECTION = "research_chunks"


class _LocalMiniLM(Embeddings):
    """Chroma's bundled MiniLM, wrapped so MMR can call it directly."""

    def __init__(self) -> None:
        self._ef = DefaultEmbeddingFunction()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in vector] for vector in self._ef(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class VectorStore:
    def __init__(self, persist_dir: str | None = None) -> None:
        self.persist_dir = persist_dir or str(Path(settings.data_dir) / "chroma")
        Path(self.persist_dir).mkdir(parents=True, exist_ok=True)
        # persist_directory means chunks from earlier runs are still here next time.
        self._store = Chroma(
            collection_name=_COLLECTION,
            persist_directory=self.persist_dir,
            embedding_function=_LocalMiniLM(),
        )

    def add_chunks(self, chunks: list[Chunk], extra_meta: dict | None = None) -> None:
        """Store chunks (same id replaces, never duplicates).

        Added some additional metadata that is unused so far just in case.
        """
        if not chunks:
            return
        extra = extra_meta or {}
        documents = [
            Document(
                page_content=c.text,
                metadata={"source_id": c.source_id, "page": c.page, "chunk_index": c.chunk_index, **extra},
            )
            for c in chunks
        ]
        self._store.add_documents(documents, ids=[c.id for c in chunks])

    def query(
        self,
        text: str,
        k: int | None = None,
        source_id: str | None = None,
        strategy: str = "similarity",
    ) -> list[Chunk]:
        """Return the k chunks closest to text. source_id scopes to one paper.

        strategy: "similarity" (k nearest) or "mmr" (more diversity in long papers). 
        """
        k = k or settings.top_k
        where = {"source_id": source_id} if source_id else None
        if strategy == "mmr":
            results = self._store.max_marginal_relevance_search(
                text, k=k, fetch_k=max(4 * k, 20), filter=where
            )
        else:
            results = self._store.similarity_search(text, k=k, filter=where)
        return [
            Chunk(
                id=doc.id,
                source_id=doc.metadata["source_id"],
                text=doc.page_content,
                page=int(doc.metadata["page"]),
                chunk_index=int(doc.metadata["chunk_index"]),
            )
            for doc in results
        ]
