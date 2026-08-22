"""Clears the demo user's Firestore records and pgvector rows before
seed_demo_user.py writes fresh ones. Against a real project this state is
genuinely persistent, so re-running demo.sh without a reset leaves every
earlier take's medications and people sitting there too -- and something
like the reorder cadence guard then acts on whichever stale record it
finds first, not the one this run just seeded.

Talks to Firestore/Cloud SQL directly rather than through the Memory
Agent's API, on purpose: this is demo housekeeping, not a product
capability, and the sole-writer rule in backend/services/memory exists to
keep application writes trust-gated in one place -- it was never about
whether a throwaway script can clear test fixtures.
"""
import os

from _client import DEMO_USER_ID

FIRESTORE_SUBCOLLECTIONS = (
    "medications",
    "appointments",
    "people",
    "documents",
    "preferences",
    "resolution_events",
    "cases",
    "audit",
)


def _reset_firestore(project_id: str) -> None:
    from google.cloud import firestore

    db = firestore.Client(project=project_id, database=os.environ.get("FIRESTORE_DATABASE", "(default)"))
    user_ref = db.collection("users").document(DEMO_USER_ID)

    for name in FIRESTORE_SUBCOLLECTIONS:
        for doc in user_ref.collection(name).stream():
            if name == "preferences":
                for history_doc in doc.reference.collection("history").stream():
                    history_doc.reference.delete()
            doc.reference.delete()

    user_ref.delete()


def _reset_vector_store() -> None:
    instance = os.environ.get("CLOUD_SQL_INSTANCE_CONNECTION_NAME")
    if not instance:
        return

    from google.cloud.sql.connector import Connector
    from sqlalchemy import create_engine, text

    connector = Connector()
    try:
        def getconn():
            return connector.connect(
                instance,
                "pg8000",
                user=os.environ["CLOUD_SQL_USER"],
                password=os.environ["CLOUD_SQL_PASSWORD"],
                db=os.environ["CLOUD_SQL_DATABASE"],
            )

        engine = create_engine("postgresql+pg8000://", creator=getconn)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM document_embeddings WHERE user_id = :user_id"), {"user_id": DEMO_USER_ID})
    except Exception:
        pass  # table doesn't exist yet on a first-ever run -- nothing to reset
    finally:
        connector.close()


def reset_demo_user() -> None:
    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        return  # nothing to reset -- seeding itself will fail at the same "not configured" boundary
    _reset_firestore(project_id)
    _reset_vector_store()


if __name__ == "__main__":
    reset_demo_user()
    print(f"Cleared any previous {DEMO_USER_ID} state.")
