"""Memory Agent should be the only thing touching Firestore/Cloud SQL.
Backs that up with a real check instead of just trusting nobody adds an
import later."""
import pathlib

import pytest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
SERVICES_DIR = BACKEND_DIR / "services"

FORBIDDEN_SNIPPETS = ("google.cloud.firestore", "google.cloud.sql", "cloud_sql_python_connector")

OTHER_SERVICE_DIRS = sorted(
    p for p in SERVICES_DIR.iterdir() if p.is_dir() and p.name not in {"memory", "__pycache__"}
)


@pytest.mark.parametrize("service_dir", OTHER_SERVICE_DIRS, ids=lambda p: p.name)
def test_service_does_not_touch_the_life_graph_store(service_dir):
    for py_file in service_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_SNIPPETS:
            assert forbidden not in text, (
                f"{py_file} references {forbidden!r} — only backend/services/memory "
                "may talk to the Life Graph store"
            )


def test_firestore_and_cloud_sql_clients_are_not_exposed_from_common():
    common_gcp_clients = (BACKEND_DIR / "common" / "gcp_clients.py").read_text(encoding="utf-8")
    assert "get_firestore_client" not in common_gcp_clients
    assert "get_cloud_sql_engine" not in common_gcp_clients
