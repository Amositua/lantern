"""Medication reorder: propose (read back identity/amount/payee/card),
confirm (risk-scaled), execute. Every branch writes an audit record and
nothing runs without confirmed=True against a case propose actually made.
"""
from datetime import datetime, timezone
from typing import Literal, Optional

from common import memory_client

from .delivery import publish_delivery_started
from .paystack_client import PaystackError, PaystackTimeoutError, get_paystack_client
from .pharmacy_client import get_pharmacy_client
from .reorder_schemas import ReorderConfirmRequest, ReorderProposal, ReorderProposeRequest, ReorderResult
from .trust_checks import TrustedCircleNotVerified, require_trusted_circle_member

# above this multiple of the per-transaction cap, step-up auth isn't
# enough -- a trusted-circle contact has to approve it instead
TRUSTED_CIRCLE_CAP_MULTIPLIER = 2


class ReorderError(RuntimeError):
    pass


class DuplicateOrderError(ReorderError):
    pass


def propose_reorder(request: ReorderProposeRequest) -> ReorderProposal:
    medication = memory_client.get_medication(request.user_id, request.med_id)
    payment = _get_payment_or_raise(request.user_id)

    if _is_duplicate(medication):
        raise DuplicateOrderError(
            f"{medication['name']} was already reordered within its {medication.get('cadence')}-day cadence"
        )

    pharmacy = get_pharmacy_client()
    amount_kobo = pharmacy.get_refill_price(medication["pharmacy_ref"], medication["name"], medication["dose"])

    has_prior_order = _has_prior_successful_reorder(request.user_id, request.med_id)
    required_confirmation = determine_required_confirmation(amount_kobo, payment, medication, has_prior_order)

    case = memory_client.create_case(
        request.user_id,
        {
            "task": "medication_reorder",
            "state": "proposed",
            "data": {
                "med_id": request.med_id,
                "pharmacy_ref": medication["pharmacy_ref"],
                "amount_kobo": amount_kobo,
                "required_confirmation": required_confirmation,
            },
        },
    )
    idempotency_key = f"reorder_{case['id']}"
    card = _card_description(payment)

    read_back = (
        f"That's your {medication['name']}, {medication['dose']}"
        + (f", for {medication['condition']}" if medication.get("condition") else "")
        + f" -- reorder a month's supply for {_format_naira(amount_kobo)} from {medication['pharmacy_ref']}, "
        + f"paid with {card}. Shall I?"
    )

    return ReorderProposal(
        case_id=case["id"],
        med_id=request.med_id,
        medication_name=medication["name"],
        medication_dose=medication["dose"],
        pharmacy_ref=medication["pharmacy_ref"],
        amount_kobo=amount_kobo,
        payee=medication["pharmacy_ref"],
        card_description=card,
        required_confirmation=required_confirmation,
        idempotency_key=idempotency_key,
        read_back=read_back,
    )


def resolve_reorder(request: ReorderConfirmRequest) -> ReorderResult:
    case = memory_client.get_case(request.user_id, request.case_id)
    if case.get("task") != "medication_reorder":
        raise ReorderError(f"case {request.case_id} is not a medication reorder")
    if case.get("state") != "proposed":
        raise ReorderError(f"case {request.case_id} is not awaiting confirmation (state={case.get('state')})")

    data = case["data"]
    med_id = data["med_id"]
    amount_kobo = data["amount_kobo"]
    required_confirmation = data["required_confirmation"]
    idempotency_key = f"reorder_{case['id']}"

    if not request.confirmed:
        memory_client.update_case(request.user_id, case["id"], {"state": "declined"})
        _write_audit(request.user_id, data, request.confirmed_by, "declined", "declined", idempotency_key)
        return ReorderResult(status="declined", message="Okay, not reordering.")

    if required_confirmation == "step_up" and not request.step_up_token:
        _write_audit(request.user_id, data, request.confirmed_by, required_confirmation, "requires_step_up", idempotency_key)
        return ReorderResult(status="requires_step_up", message="This needs a one-time code before I can go ahead.")

    if required_confirmation == "trusted_circle":
        try:
            require_trusted_circle_member(request.user_id, request.confirmed_by)
        except TrustedCircleNotVerified:
            _write_audit(
                request.user_id, data, request.confirmed_by, required_confirmation, "requires_trusted_circle", idempotency_key
            )
            return ReorderResult(status="requires_trusted_circle", message="This one needs a trusted-circle approval.")

    # re-checked against fresh state right before executing, not the
    # snapshot from propose time
    medication = memory_client.get_medication(request.user_id, med_id)
    if _is_duplicate(medication):
        memory_client.update_case(request.user_id, case["id"], {"state": "aborted_duplicate"})
        _write_audit(request.user_id, data, request.confirmed_by, required_confirmation, "aborted_duplicate", idempotency_key)
        return ReorderResult(status="aborted_duplicate", message="Looks like this was already reordered recently.")

    payment = _get_payment_or_raise(request.user_id)
    pharmacy = get_pharmacy_client()
    order = pharmacy.place_order(data["pharmacy_ref"], medication["name"], medication["dose"])

    paystack = get_paystack_client()
    email = f"user+{request.user_id}@lantern.local"
    try:
        charge = _charge_with_verify_before_retry(paystack, payment["method_ref"], amount_kobo, email, idempotency_key)
    except PaystackError as exc:
        memory_client.update_case(request.user_id, case["id"], {"state": "failed"})
        _write_audit(request.user_id, data, request.confirmed_by, required_confirmation, f"failed: {exc}", idempotency_key)
        raise ReorderError(str(exc)) from exc

    memory_client.update_medication(request.user_id, med_id, {"last_refill": _now_iso()})
    memory_client.update_case(request.user_id, case["id"], {"state": "executed"})
    _write_audit(request.user_id, data, request.confirmed_by, required_confirmation, "success", idempotency_key)

    publish_delivery_started(request.user_id, case["id"], order.order_id)

    return ReorderResult(
        status="executed",
        message=f"Done -- {medication['name']} is on its way, arriving in {order.eta}.",
        order_id=order.order_id,
        charge_reference=charge.reference,
    )


def determine_required_confirmation(
    amount_kobo: int, payment: dict, medication: dict, has_prior_order: bool
) -> Literal["simple", "step_up", "trusted_circle"]:
    per_transaction_cap_kobo = _naira_to_kobo(payment.get("per_transaction_cap"))
    never_auto = {c.lower() for c in payment.get("never_auto_categories", [])}
    condition = (medication.get("condition") or "").lower()

    if per_transaction_cap_kobo is not None and amount_kobo > per_transaction_cap_kobo * TRUSTED_CIRCLE_CAP_MULTIPLIER:
        return "trusted_circle"
    if condition in never_auto:
        return "step_up"
    if per_transaction_cap_kobo is not None and amount_kobo > per_transaction_cap_kobo:
        return "step_up"
    if not has_prior_order:
        return "step_up"
    return "simple"


def _charge_with_verify_before_retry(paystack, authorization_code: str, amount_kobo: int, email: str, idempotency_key: str):
    try:
        return paystack.charge_authorization(authorization_code, amount_kobo, email, idempotency_key)
    except PaystackTimeoutError:
        existing = paystack.verify_charge(idempotency_key)
        if existing is not None and existing.status == "success":
            return existing
        return paystack.charge_authorization(authorization_code, amount_kobo, email, idempotency_key)


def _is_duplicate(medication: dict) -> bool:
    last_refill = medication.get("last_refill")
    cadence = medication.get("cadence")
    if not last_refill or not cadence:
        return False
    last_refill_at = _parse_datetime(last_refill)
    if last_refill_at is None:
        return False
    return (datetime.now(timezone.utc) - last_refill_at).days < cadence


def _has_prior_successful_reorder(user_id: str, med_id: str) -> bool:
    for entry in memory_client.list_audit(user_id, limit=100):
        if entry.get("action") == "medication_reorder" and entry.get("result") == "success" and entry.get(
            "proposed", {}
        ).get("med_id") == med_id:
            return True
    return False


def _get_payment_or_raise(user_id: str) -> dict:
    try:
        return memory_client.get_payment(user_id)
    except memory_client.MemoryAgentError as exc:
        if exc.status_code == 404:
            raise ReorderError("no payment method on file for this user") from exc
        raise


def _write_audit(user_id: str, proposed: dict, confirmed_by: str, method: str, result: str, idempotency_key: str) -> None:
    memory_client.append_audit(
        user_id,
        {
            "action": "medication_reorder",
            "proposed": proposed,
            "confirmed_by": confirmed_by,
            "method": method,
            "result": result,
            "idempotency_key": idempotency_key,
        },
    )


def _card_description(payment: dict) -> str:
    if payment.get("card_last4"):
        bank = f"{payment['card_bank']} " if payment.get("card_bank") else ""
        return f"your {bank}card ending in {payment['card_last4']}"
    return "your card on file"


def _format_naira(amount_kobo: int) -> str:
    return f"₦{amount_kobo / 100:,.0f}"


def _naira_to_kobo(amount_naira: Optional[float]) -> Optional[int]:
    return None if amount_naira is None else int(amount_naira * 100)


def _parse_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
