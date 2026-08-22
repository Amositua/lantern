"""Google Cloud client factories shared across services.

Lazy on purpose — a service should be able to boot and answer /health
locally before real credentials exist. Call the factory, catch
ClientInitError if it's not configured yet.

No Firestore or Cloud SQL here on purpose — those are memory-only, see
services/memory/clients.py.
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
def get_genai_live_client():
    """Separate client for the Live API -- it needs a real region and 404s
    against the global endpoint the rest of Gemini serves from."""
    from google import genai

    settings = get_settings()
    if not settings.gcp_project_id:
        raise ClientInitError("GCP_PROJECT_ID is not set; cannot init the Vertex AI GenAI client")
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project_id,
        location=settings.gemini_live_location,
    )


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
