"""Cloud SQL + pgvector store for RAG over the user's own documents
(letters, labels, prescriptions) -- separate from Firestore, which holds
each document's metadata. life_graph.py calls this the same way it calls
the Firestore client: through one interface, real Postgres underneath,
a fake underneath in tests.
"""
import abc
from typing import List, Optional, Tuple

from common.config import get_settings
from common.gcp_clients import get_genai_client

from .clients import get_cloud_sql_engine

EMBEDDING_DIMENSIONS = 3072


class DocumentVectorStore(abc.ABC):
    @abc.abstractmethod
    def upsert(self, user_id: str, document_id: str, text: str) -> None:
        ...

    @abc.abstractmethod
    def search(self, user_id: str, query: str, top_k: int = 3) -> List[Tuple[str, str, float]]:
        """(document_id, content, distance) tuples, nearest first. Always
        scoped to user_id -- one user's documents never leak into another's
        search results."""


def embed(text: str) -> List[float]:
    settings = get_settings()
    response = get_genai_client().models.embed_content(model=settings.gemini_embedding_model, contents=text)
    return list(response.embeddings[0].values)


def _vector_literal(values: List[float]) -> str:
    return "[" + ",".join(repr(v) for v in values) + "]"


class CloudSqlVectorStore(DocumentVectorStore):
    def __init__(self, engine=None):
        self._engine = engine or get_cloud_sql_engine()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS document_embeddings (
                        user_id TEXT NOT NULL,
                        document_id TEXT NOT NULL,
                        content TEXT NOT NULL,
                        embedding vector({EMBEDDING_DIMENSIONS}) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (user_id, document_id)
                    )
                    """
                )
            )

    def upsert(self, user_id: str, document_id: str, text_content: str) -> None:
        from sqlalchemy import text

        vector = _vector_literal(embed(text_content))
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO document_embeddings (user_id, document_id, content, embedding)
                    VALUES (:user_id, :document_id, :content, CAST(:embedding AS vector))
                    ON CONFLICT (user_id, document_id)
                    DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding
                    """
                ),
                {"user_id": user_id, "document_id": document_id, "content": text_content, "embedding": vector},
            )

    def search(self, user_id: str, query: str, top_k: int = 3) -> List[Tuple[str, str, float]]:
        from sqlalchemy import text

        vector = _vector_literal(embed(query))
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT document_id, content, embedding <=> CAST(:embedding AS vector) AS distance
                    FROM document_embeddings
                    WHERE user_id = :user_id
                    ORDER BY distance ASC
                    LIMIT :top_k
                    """
                ),
                {"user_id": user_id, "embedding": vector, "top_k": top_k},
            ).fetchall()
        return [(row.document_id, row.content, float(row.distance)) for row in rows]


_store: Optional[DocumentVectorStore] = None


def get_vector_store() -> DocumentVectorStore:
    global _store
    if _store is None:
        _store = CloudSqlVectorStore()
    return _store
