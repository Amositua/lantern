"""Lazy factories for the Google Cloud clients Lantern's services depend on.

Every factory builds its client on first use rather than at import time,
so a service can boot and answer /health locally before real project
credentials exist. Callers that need a client to actually be configured
should call the factory and handle ClientInitError.
"""
from functools import lru_cache

from .config import get_settings


class ClientInitError(RuntimeError):
    """Raised when a client can't be built because required config is missing."""


@lru_cache
def get_genai_client():
    from google import genai

    settings = get_settings()
    if not settings.gcp_project_id:
        raise ClientInitError("GCP_PROJECT_ID is not set; cannot init the Vertex AI GenAI client")
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project_id,
        location=settings.vertex_location,
    )


@lru_cache
def get_firestore_client():
    from google.cloud import firestore

    settings = get_settings()
    if not settings.gcp_project_id:
        raise ClientInitError("GCP_PROJECT_ID is not set; cannot init the Firestore client")
    return firestore.Client(project=settings.gcp_project_id, database=settings.firestore_database)


@lru_cache
def get_pubsub_publisher():
    from google.cloud import pubsub_v1

    return pubsub_v1.PublisherClient()


@lru_cache
def get_pubsub_subscriber():
    from google.cloud import pubsub_v1

    return pubsub_v1.SubscriberClient()


def topic_path(topic_name: str) -> str:
    settings = get_settings()
    if not settings.gcp_project_id:
        raise ClientInitError("GCP_PROJECT_ID is not set; cannot build a Pub/Sub topic path")
    publisher = get_pubsub_publisher()
    return publisher.topic_path(settings.gcp_project_id, f"{settings.pubsub_topic_prefix}-{topic_name}")


@lru_cache
def get_cloud_sql_engine():
    from google.cloud.sql.connector import Connector
    from sqlalchemy import create_engine

    settings = get_settings()
    if not settings.cloud_sql_instance_connection_name:
        raise ClientInitError("CLOUD_SQL_INSTANCE_CONNECTION_NAME is not set; cannot init the Cloud SQL engine")

    connector = Connector()

    def getconn():
        return connector.connect(
            settings.cloud_sql_instance_connection_name,
            "pg8000",
            user=settings.cloud_sql_user,
            password=settings.cloud_sql_password,
            db=settings.cloud_sql_database,
        )

    return create_engine("postgresql+pg8000://", creator=getconn)
