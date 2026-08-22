"""Shared by every propose-confirm-execute flow that ends in a Paystack
charge -- reorder.py and bills.py both need the exact same verify-before-
retry guarantee, so it lives in one place rather than two copies that
could quietly drift apart on the one piece of logic where a divergence
means a real double-charge.
"""
from datetime import datetime
from typing import Literal, Optional

from .paystack_client import PaystackTimeoutError

# above this multiple of the per-transaction cap, step-up auth isn't
# enough -- a trusted-circle contact has to approve it instead
TRUSTED_CIRCLE_CAP_MULTIPLIER = 2


def determine_required_confirmation(
    amount_kobo: int, payment: dict, category: Optional[str], has_prior_success: bool
) -> Literal["simple", "step_up", "trusted_circle"]:
    """Domain-agnostic risk scaling shared by every propose-confirm-execute
    flow that ends in a charge -- a reorder's "condition" and a bill's
    "category" both just feed the same never-auto-category check."""
    per_transaction_cap_kobo = naira_to_kobo(payment.get("per_transaction_cap"))
    never_auto = {c.lower() for c in payment.get("never_auto_categories", [])}
    category_key = (category or "").lower()

    if per_transaction_cap_kobo is not None and amount_kobo > per_transaction_cap_kobo * TRUSTED_CIRCLE_CAP_MULTIPLIER:
        return "trusted_circle"
    if category_key in never_auto:
        return "step_up"
    if per_transaction_cap_kobo is not None and amount_kobo > per_transaction_cap_kobo:
        return "step_up"
    if not has_prior_success:
        return "step_up"
    return "simple"


def charge_with_verify_before_retry(paystack, authorization_code: str, amount_kobo: int, email: str, idempotency_key: str):
    try:
        return paystack.charge_authorization(authorization_code, amount_kobo, email, idempotency_key)
    except PaystackTimeoutError:
        existing = paystack.verify_charge(idempotency_key)
        if existing is not None and existing.status == "success":
            return existing
        return paystack.charge_authorization(authorization_code, amount_kobo, email, idempotency_key)


def format_naira(amount_kobo: int) -> str:
    return f"₦{amount_kobo / 100:,.0f}"


def naira_to_kobo(amount_naira: Optional[float]) -> Optional[int]:
    return None if amount_naira is None else int(amount_naira * 100)


def parse_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
