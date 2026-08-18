"""Minimal in-memory stand-in for firestore.Client — just enough of the
API surface life_graph.py actually calls, so we can test the trust logic
without spinning up the emulator."""
from typing import Any, Dict, List, Optional, Tuple


class _Snapshot:
    def __init__(self, doc_id: str, data: Optional[dict]):
        self.id = doc_id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> Optional[dict]:
        return dict(self._data) if self._data is not None else None


class _Query:
    def __init__(self, docs: List[Tuple[str, dict]]):
        self._docs = docs

    def where(self, field: str, op: str, value: Any) -> "_Query":
        assert op == "==", f"fake firestore only supports '==', got {op!r}"
        return _Query([d for d in self._docs if d[1].get(field) == value])

    def order_by(self, field: str, direction: str = "ASCENDING") -> "_Query":
        reverse = direction == "DESCENDING"
        return _Query(sorted(self._docs, key=lambda d: d[1].get(field) or 0, reverse=reverse))

    def limit(self, count: int) -> "_Query":
        return _Query(self._docs[:count])

    def stream(self):
        return (_Snapshot(doc_id, data) for doc_id, data in self._docs)


class _DocumentRef:
    def __init__(self, collection: "_CollectionRef", doc_id: str):
        self._collection = collection
        self.id = doc_id

    def get(self) -> _Snapshot:
        return _Snapshot(self.id, self._collection._store.get(self.id))

    def set(self, data: dict, merge: bool = False) -> None:
        if merge and self.id in self._collection._store:
            self._collection._store[self.id] = {**self._collection._store[self.id], **data}
        else:
            self._collection._store[self.id] = dict(data)

    def update(self, data: dict) -> None:
        if self.id not in self._collection._store:
            raise KeyError(f"cannot update missing document {self.id!r}")
        self._collection._store[self.id].update(data)

    def collection(self, name: str) -> "_CollectionRef":
        return self._collection._db.collection(f"{self._collection.name}/{self.id}/{name}")


class _CollectionRef:
    def __init__(self, db: "FakeFirestoreClient", name: str):
        self._db = db
        self.name = name
        self._store: Dict[str, dict] = db._collections.setdefault(name, {})
        self._auto_counter = 0

    def document(self, doc_id: Optional[str] = None) -> _DocumentRef:
        if doc_id is None:
            self._auto_counter += 1
            doc_id = f"auto-{self._auto_counter}"
        return _DocumentRef(self, doc_id)

    def _query(self) -> _Query:
        return _Query(list(self._store.items()))

    def stream(self):
        return self._query().stream()

    def where(self, field: str, op: str, value: Any) -> _Query:
        return self._query().where(field, op, value)

    def order_by(self, field: str, direction: str = "ASCENDING") -> _Query:
        return self._query().order_by(field, direction)


class FakeFirestoreClient:
    def __init__(self):
        self._collections: Dict[str, Dict[str, dict]] = {}

    def collection(self, name: str) -> _CollectionRef:
        return _CollectionRef(self, name)
