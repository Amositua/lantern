"""Only module allowed to hold a Firestore or Cloud SQL client — keeps
the Memory Agent the actual sole writer, not just the documented one.
test_sole_writer.py checks nobody else starts importing these."""
from functools import lru_cache

from common.config import get_settings
from common.gcp_clients import ClientInitError

__all__ = ["ClientInitError", "get_firestore_client", "get_cloud_sql_engine"]


@lru_cache
def get_firestore_client():
    from google.cloud import firestore

    settings = get_settings()
    if not settings.gcp_project_id:
        raise ClientInitError("GCP_PROJECT_ID is not set; cannot init the Firestore client")
    return firestore.Client(project=settings.gcp_project_id, database=settings.firestore_database)


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
