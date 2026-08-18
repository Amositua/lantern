"""Shared trust checks used by both enrollment and the reorder confirmation
gate -- a claimed trusted-circle identity is only good if it's actually on
record, never trusted on the caller's word alone."""
from common import memory_client


class TrustedCircleNotVerified(PermissionError):
    pass


def require_trusted_circle_member(user_id: str, claimed_name: str) -> None:
    people = memory_client.list_people(user_id)
    normalized = claimed_name.strip().lower()
    for person in people:
        roles = [r.lower() for r in person.get("roles", [])]
        if person.get("name", "").strip().lower() == normalized and (
            "trusted_circle" in roles or "caregiver" in roles
        ):
            return
    raise TrustedCircleNotVerified(f"{claimed_name!r} is not recorded as a trusted-circle member for this user")
