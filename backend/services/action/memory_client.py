"""HTTP client for the Memory Agent. Action has no Firestore access of its
own — every write goes through here."""
from typing import Any, Dict, List, Optional

import httpx

from common.config import get_settings
from common.logging_utils import get_logger

logger = get_logger("action.memory_client")


class MemoryAgentError(RuntimeError):
    pass


def _request(method: str, path: str, json: Optional[dict] = None) -> Any:
    base_url = get_settings().memory_url
    url = f"{base_url}{path}"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.request(method, url, json=json)
    except httpx.HTTPError as exc:
        logger.warning("memory agent unreachable: %s %s: %s", method, url, exc)
        raise MemoryAgentError(f"could not reach the Memory Agent at {url}: {exc}") from exc

    if resp.status_code >= 400:
        detail = resp.text
        try:
            detail = resp.json().get("detail", detail)
        except ValueError:
            pass
        raise MemoryAgentError(f"Memory Agent rejected {method} {path}: {detail}")

    return resp.json()


def create_document(user_id: str, payload: Dict[str, Any]) -> dict:
    return _request("POST", f"/users/{user_id}/documents", json=payload)


def create_medication(user_id: str, payload: Dict[str, Any]) -> dict:
    return _request("POST", f"/users/{user_id}/medications", json=payload)


def write_payment(user_id: str, payload: Dict[str, Any]) -> dict:
    return _request("PUT", f"/users/{user_id}/payment", json=payload)


def list_people(user_id: str) -> List[dict]:
    return _request("GET", f"/users/{user_id}/people")
