"""In-memory stand-in for CloudSqlVectorStore -- scores by word overlap
instead of a real embedding call, so the trust/retrieval logic can be
tested without Cloud SQL or a Vertex AI embedding call.
"""
import re
from typing import Dict, List, Tuple


def _words(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


class FakeVectorStore:
    def __init__(self):
        self._rows: Dict[Tuple[str, str], str] = {}

    def upsert(self, user_id: str, document_id: str, text: str) -> None:
        self._rows[(user_id, document_id)] = text

    def search(self, user_id: str, query: str, top_k: int = 3) -> List[Tuple[str, str, float]]:
        query_words = _words(query)
        scored = []
        for (uid, doc_id), text in self._rows.items():
            if uid != user_id:
                continue
            overlap = len(query_words & _words(text))
            distance = 1.0 / (1 + overlap)  # more overlap -> smaller "distance", same direction as cosine
            scored.append((doc_id, text, distance))
        scored.sort(key=lambda row: row[2])
        return scored[:top_k]
