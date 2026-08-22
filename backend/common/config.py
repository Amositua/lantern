from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "local"
    port: int = 8080

    gcp_project_id: Optional[str] = None
    gcp_region: str = "us-central1"
    # Gemini 3.5 Flash only serves out of the global Vertex AI endpoint right
    # now, not regional ones -- this is separate from gcp_region, which still
    # governs Cloud Run/Firestore/everything else.
    vertex_location: str = "global"
    # The Live API is the opposite: it 404s against the global endpoint and
    # needs an actual region. Kept separate from vertex_location rather than
    # forcing one location to serve both.
    gemini_live_location: str = "us-central1"
    gemini_flash_model: str = "gemini-3.5-flash"
    # No 3.5 Pro model exists yet; 3.1-pro-preview is the same generation's
    # Pro tier and what's actually available.
    gemini_pro_model: str = "gemini-3.1-pro-preview"
    gemini_embedding_model: str = "gemini-embedding-001"
    # The bidi Live API is served by its own model family, separate from the
    # regular generate_content lineup -- gemini-3.5-flash rejects a live.connect
    # outright ("not supported in the live api"). This is the live-capable
    # model actually listed for this project.
    gemini_live_model: str = "gemini-live-2.5-flash-native-audio"

    firestore_database: str = "(default)"

    cloud_sql_instance_connection_name: Optional[str] = None
    cloud_sql_database: str = "lantern"
    cloud_sql_user: Optional[str] = None
    cloud_sql_password: Optional[str] = None

    pubsub_topic_prefix: str = "lantern"

    pharmacy_aggregator_base_url: Optional[str] = None
    pharmacy_aggregator_api_key: Optional[str] = None
    clinic_aggregator_base_url: Optional[str] = None
    clinic_aggregator_api_key: Optional[str] = None
    paystack_secret_key: Optional[str] = None

    # Nigeria's national emergency number -- stable and well-established,
    # safe to default. crisis_hotline_number is deliberately unset by
    # default: a wrong crisis-line number is actively harmful, so a real
    # deployment must configure a verified, current, local one rather than
    # trusting a hardcoded guess.
    national_emergency_number: str = "112"
    crisis_hotline_number: Optional[str] = None

    # The dashboard calls Memory and Action directly from the browser (no
    # BFF layer yet -- reasonable for this scope, revisit before this ever
    # serves real users at scale). CORS is scoped to this one origin, not "*".
    dashboard_origin: str = "http://localhost:5173"

    orchestrator_url: str = "http://localhost:8080"
    perception_url: str = "http://localhost:8081"
    clarifier_url: str = "http://localhost:8082"
    action_url: str = "http://localhost:8083"
    safety_router_url: str = "http://localhost:8084"
    memory_url: str = "http://localhost:8085"
    live_session_gateway_url: str = "http://localhost:8086"


@lru_cache
def get_settings() -> Settings:
    return Settings()
