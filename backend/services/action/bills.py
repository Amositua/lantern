"""Utility bill payment: propose (read back provider/account/amount/card),
confirm (risk-scaled, same gate reorder.py uses), execute. A second
domain proving the propose-confirm-execute + payment machinery generalizes
past medication -- shares its safety-critical charge/risk-scaling logic
with reorder.py via billing.py rather than duplicating it.
"""
from datetime import datetime, timezone

from common import memory_client

from .billing import charge_with_verify_before_retry, determine_required_confirmation, format_naira, parse_datetime
from .bills_schemas import BillConfirmRequest, BillProposal, BillProposeRequest, BillResult
from .paystack_client import PaystackError, get_paystack_client
from .trust_checks import TrustedCircleNotVerified, require_trusted_circle_member
from .utility_client import get_utility_client

RECENTLY_PAID_WINDOW_DAYS = 1


class BillPaymentError(RuntimeError):
    pass


class AlreadyPaidError(BillPaymentError):
    pass


def propose_bill_payment(request: BillProposeRequest) -> BillProposal:
    bill = memory_client.get_bill(request.user_id, request.bill_id)
    payment = _get_payment_or_raise(request.user_id)

    if _is_recently_paid(bill):
        raise AlreadyPaidError(f"{bill['provider']} was already paid in the last {RECENTLY_PAID_WINDOW_DAYS} day(s)")

    utility = get_utility_client()
    amount_kobo = utility.get_amount_due(bill["provider"], bill["account_ref"])

    has_prior_success = _has_prior_successful_payment(request.user_id, request.bill_id)
    required_confirmation = determine_required_confirmation(amount_kobo, payment, bill["category"], has_prior_success)

    case = memory_client.create_case(
        request.user_id,
        {
            "task": "utility_bill_payment",
            "state": "proposed",
            "data": {
                "bill_id": request.bill_id,
                "provider": bill["provider"],
                "account_ref": bill["account_ref"],
                "amount_kobo": amount_kobo,
                "required_confirmation": required_confirmation,
            },
        },
    )
    idempotency_key = f"bill_{case['id']}"
    card = _card_description(payment)

    read_back = (
        f"Your {bill['provider']} {bill['category']} bill, account {bill['account_ref']} -- "
        f"{format_naira(amount_kobo)} due, paid with {card}. Shall I?"
    )

    return BillProposal(
        case_id=case["id"],
        bill_id=request.bill_id,
        provider=bill["provider"],
        category=bill["category"],
        account_ref=bill["account_ref"],
        amount_kobo=amount_kobo,
        card_description=card,
        required_confirmation=required_confirmation,
        idempotency_key=idempotency_key,
        read_back=read_back,
    )


def resolve_bill_payment(request: BillConfirmRequest) -> BillResult:
    case = memory_client.get_case(request.user_id, request.case_id)
    if case.get("task") != "utility_bill_payment":
        raise BillPaymentError(f"case {request.case_id} is not a utility bill payment")
    if case.get("state") != "proposed":
        raise BillPaymentError(f"case {request.case_id} is not awaiting confirmation (state={case.get('state')})")

    data = case["data"]
    bill_id = data["bill_id"]
    amount_kobo = data["amount_kobo"]
    required_confirmation = data["required_confirmation"]
    idempotency_key = f"bill_{case['id']}"

    if not request.confirmed:
        memory_client.update_case(request.user_id, case["id"], {"state": "declined"})
        _write_audit(request.user_id, data, request.confirmed_by, "declined", "declined", idempotency_key)
        return BillResult(status="declined", message="Okay, not paying that one.")

    if required_confirmation == "step_up" and not request.step_up_token:
        _write_audit(request.user_id, data, request.confirmed_by, required_confirmation, "requires_step_up", idempotency_key)
        return BillResult(status="requires_step_up", message="This needs a one-time code before I can go ahead.")

    if required_confirmation == "trusted_circle":
        try:
            require_trusted_circle_member(request.user_id, request.confirmed_by)
        except TrustedCircleNotVerified:
            _write_audit(
                request.user_id, data, request.confirmed_by, required_confirmation, "requires_trusted_circle", idempotency_key
            )
            return BillResult(status="requires_trusted_circle", message="This one needs a trusted-circle approval.")

    bill = memory_client.get_bill(request.user_id, bill_id)
    if _is_recently_paid(bill):
        memory_client.update_case(request.user_id, case["id"], {"state": "aborted_already_paid"})
        _write_audit(request.user_id, data, request.confirmed_by, required_confirmation, "aborted_already_paid", idempotency_key)
        return BillResult(status="aborted_already_paid", message="Looks like this was already paid recently.")

    payment = _get_payment_or_raise(request.user_id)
    utility = get_utility_client()

    paystack = get_paystack_client()
    email = f"user+{request.user_id}@lantern.local"
    try:
        charge = charge_with_verify_before_retry(paystack, payment["method_ref"], amount_kobo, email, idempotency_key)
    except PaystackError as exc:
        memory_client.update_case(request.user_id, case["id"], {"state": "failed"})
        _write_audit(request.user_id, data, request.confirmed_by, required_confirmation, f"failed: {exc}", idempotency_key)
        raise BillPaymentError(str(exc)) from exc

    payment_result = utility.pay_bill(bill["provider"], bill["account_ref"], amount_kobo)

    memory_client.update_bill(request.user_id, bill_id, {"last_paid": _now_iso()})
    memory_client.update_case(request.user_id, case["id"], {"state": "executed"})
    _write_audit(request.user_id, data, request.confirmed_by, required_confirmation, "success", idempotency_key)

    return BillResult(
        status="executed",
        message=f"Done -- your {bill['provider']} bill is paid.",
        payment_reference=payment_result.reference or charge.reference,
    )


def _is_recently_paid(bill: dict) -> bool:
    last_paid = parse_datetime(bill.get("last_paid"))
    if last_paid is None:
        return False
    return (datetime.now(timezone.utc) - last_paid).days < RECENTLY_PAID_WINDOW_DAYS


def _has_prior_successful_payment(user_id: str, bill_id: str) -> bool:
    for entry in memory_client.list_audit(user_id, limit=100):
        if entry.get("action") == "utility_bill_payment" and entry.get("result") == "success" and entry.get(
            "proposed", {}
        ).get("bill_id") == bill_id:
            return True
    return False


def _get_payment_or_raise(user_id: str) -> dict:
    try:
        return memory_client.get_payment(user_id)
    except memory_client.MemoryAgentError as exc:
        if exc.status_code == 404:
            raise BillPaymentError("no payment method on file for this user") from exc
        raise


def _write_audit(user_id: str, proposed: dict, confirmed_by: str, method: str, result: str, idempotency_key: str) -> None:
    memory_client.append_audit(
        user_id,
        {
            "action": "utility_bill_payment",
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
