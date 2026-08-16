from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "local"
    port: int = 8080

    gcp_project_id: Optional[str] = None
    gcp_region: str = "us-central1"
    vertex_location: str = "us-central1"
    gemini_flash_model: str = "gemini-3.5-flash"
    gemini_pro_model: str = "gemini-3.5-pro"

    firestore_database: str = "(default)"

    cloud_sql_instance_connection_name: Optional[str] = None
    cloud_sql_database: str = "lantern"
    cloud_sql_user: Optional[str] = None
    cloud_sql_password: Optional[str] = None

    pubsub_topic_prefix: str = "lantern"

    pharmacy_aggregator_base_url: Optional[str] = None
    pharmacy_aggregator_api_key: Optional[str] = None
    paystack_secret_key: Optional[str] = None

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
