"""HTTP client for the Memory Agent — no service touches Firestore
directly, every read/write goes through here."""
from typing import Any, Dict, List, Optional

import httpx

from .config import get_settings
from .logging_utils import get_logger

logger = get_logger("memory_client")


class MemoryAgentError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _request(method: str, path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> Any:
    base_url = get_settings().memory_url
    url = f"{base_url}{path}"
    try:
        # Document search chains a real embedding call plus a Cloud SQL
        # round-trip -- 10s was tight enough to fail even on a genuinely
        # successful request.
        with httpx.Client(timeout=30.0) as client:
            resp = client.request(method, url, json=json, params=params)
    except httpx.HTTPError as exc:
        logger.warning("memory agent unreachable: %s %s: %s", method, url, exc)
        raise MemoryAgentError(f"could not reach the Memory Agent at {url}: {exc}") from exc

    if resp.status_code >= 400:
        detail = resp.text
        try:
            detail = resp.json().get("detail", detail)
        except ValueError:
            pass
        raise MemoryAgentError(f"Memory Agent rejected {method} {path}: {detail}", status_code=resp.status_code)

    return resp.json()


def create_document(user_id: str, payload: Dict[str, Any]) -> dict:
    return _request("POST", f"/users/{user_id}/documents", json=payload)


def search_documents(user_id: str, query: str, top_k: int = 3) -> List[dict]:
    return _request("GET", f"/users/{user_id}/documents/search", params={"q": query, "top_k": top_k})


def create_medication(user_id: str, payload: Dict[str, Any]) -> dict:
    return _request("POST", f"/users/{user_id}/medications", json=payload)


def list_medications(user_id: str) -> List[dict]:
    return _request("GET", f"/users/{user_id}/medications")


def write_payment(user_id: str, payload: Dict[str, Any]) -> dict:
    return _request("PUT", f"/users/{user_id}/payment", json=payload)


def list_people(user_id: str) -> List[dict]:
    return _request("GET", f"/users/{user_id}/people")


def get_life_graph(user_id: str) -> dict:
    return _request("GET", f"/users/{user_id}/life-graph")


def write_preference(user_id: str, payload: Dict[str, Any]) -> dict:
    return _request("POST", f"/users/{user_id}/preferences", json=payload)


def resolve_resolution_event(user_id: str, event_id: str, payload: Dict[str, Any]) -> dict:
    return _request("POST", f"/users/{user_id}/resolution-events/{event_id}/resolve", json=payload)


def get_payment(user_id: str) -> dict:
    return _request("GET", f"/users/{user_id}/payment")


def get_medication(user_id: str, med_id: str) -> dict:
    return _request("GET", f"/users/{user_id}/medications/{med_id}")


def update_medication(user_id: str, med_id: str, payload: Dict[str, Any]) -> dict:
    return _request("PATCH", f"/users/{user_id}/medications/{med_id}", json=payload)


def create_case(user_id: str, payload: Dict[str, Any]) -> dict:
    return _request("POST", f"/users/{user_id}/cases", json=payload)


def list_cases(user_id: str) -> List[dict]:
    return _request("GET", f"/users/{user_id}/cases")


def get_case(user_id: str, case_id: str) -> dict:
    return _request("GET", f"/users/{user_id}/cases/{case_id}")


def update_case(user_id: str, case_id: str, payload: Dict[str, Any]) -> dict:
    return _request("PATCH", f"/users/{user_id}/cases/{case_id}", json=payload)


def append_audit(user_id: str, payload: Dict[str, Any]) -> dict:
    return _request("POST", f"/users/{user_id}/audit", json=payload)


def list_audit(user_id: str, limit: int = 50) -> List[dict]:
    return _request("GET", f"/users/{user_id}/audit?limit={limit}")
