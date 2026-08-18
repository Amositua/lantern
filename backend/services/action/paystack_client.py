"""Paystack behind an interface — sandbox impl so we can demo without a
live secret key."""
import abc
import hashlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from common.config import get_settings


class PaystackError(RuntimeError):
    pass


class PaystackTimeoutError(PaystackError):
    """The charge attempt's outcome is unknown -- Paystack may or may not
    have processed it. Callers must verify by idempotency key before ever
    retrying, never blindly re-charge."""


@dataclass
class VerifiedTransaction:
    reference: str
    status: str
    authorization_code: Optional[str]
    channel: Optional[str]
    reusable: bool
    last4: Optional[str] = None
    bank: Optional[str] = None


@dataclass
class ChargeResult:
    status: str
    reference: str
    amount_kobo: int


class PaystackClient(abc.ABC):
    @abc.abstractmethod
    def verify_transaction(self, reference: str) -> VerifiedTransaction:
        ...

    @abc.abstractmethod
    def charge_authorization(
        self, authorization_code: str, amount_kobo: int, email: str, idempotency_key: str
    ) -> ChargeResult:
        ...

    @abc.abstractmethod
    def verify_charge(self, idempotency_key: str) -> Optional[ChargeResult]:
        """Looks up a charge by the reference it was made with, without
        charging anything -- how a caller checks an ambiguous outcome
        before ever considering a retry."""


class SandboxPaystackClient(PaystackClient):
    def __init__(self):
        # keyed by idempotency_key -- the same key always replays the same
        # result rather than charging twice
        self._charges: dict = {}
        self._timed_out_once: set = set()

    # ref starting with demo_fail_ = failed 2FA, anything else tokenizes ok
    def verify_transaction(self, reference: str) -> VerifiedTransaction:
        if reference.startswith("demo_fail_"):
            return VerifiedTransaction(
                reference=reference, status="failed", authorization_code=None, channel=None, reusable=False
            )

        digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()[:24]
        return VerifiedTransaction(
            reference=reference,
            status="success",
            authorization_code=f"AUTH_sandbox_{digest}",
            channel="card",
            reusable=True,
            last4="4242",
            bank="Sandbox Bank",
        )

    def charge_authorization(
        self, authorization_code: str, amount_kobo: int, email: str, idempotency_key: str
    ) -> ChargeResult:
        if idempotency_key in self._charges:
            return self._charges[idempotency_key]

        result = ChargeResult(status="success", reference=f"sandbox_charge_{idempotency_key}", amount_kobo=amount_kobo)

        if authorization_code.startswith("AUTH_timeout_once_") and idempotency_key not in self._timed_out_once:
            # Paystack actually processes the charge here (we record it as
            # having happened) but the response never reaches us -- this is
            # the ambiguous-timeout case, not a failure
            self._timed_out_once.add(idempotency_key)
            self._charges[idempotency_key] = result
            raise PaystackTimeoutError(f"timed out waiting for a response charging {idempotency_key}")

        self._charges[idempotency_key] = result
        return result

    def verify_charge(self, idempotency_key: str) -> Optional[ChargeResult]:
        return self._charges.get(idempotency_key)


class LivePaystackClient(PaystackClient):
    def __init__(self, secret_key: str):
        self._secret_key = secret_key

    def verify_transaction(self, reference: str) -> VerifiedTransaction:
        import httpx

        resp = httpx.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {self._secret_key}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        auth = data.get("authorization") or {}
        return VerifiedTransaction(
            reference=reference,
            status=data.get("status", "failed"),
            authorization_code=auth.get("authorization_code"),
            channel=auth.get("channel"),
            reusable=bool(auth.get("reusable")),
            last4=auth.get("last4"),
            bank=auth.get("bank"),
        )

    def charge_authorization(
        self, authorization_code: str, amount_kobo: int, email: str, idempotency_key: str
    ) -> ChargeResult:
        import httpx

        # idempotency_key doubles as the Paystack transaction reference, so
        # a later verify_charge can look the same charge back up by it
        resp = httpx.post(
            "https://api.paystack.co/transaction/charge_authorization",
            headers={"Authorization": f"Bearer {self._secret_key}"},
            json={
                "authorization_code": authorization_code,
                "amount": amount_kobo,
                "email": email,
                "reference": idempotency_key,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return ChargeResult(status=data.get("status", "failed"), reference=idempotency_key, amount_kobo=amount_kobo)

    def verify_charge(self, idempotency_key: str) -> Optional[ChargeResult]:
        import httpx

        resp = httpx.get(
            f"https://api.paystack.co/transaction/verify/{idempotency_key}",
            headers={"Authorization": f"Bearer {self._secret_key}"},
            timeout=10.0,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()["data"]
        return ChargeResult(status=data.get("status", "failed"), reference=idempotency_key, amount_kobo=data.get("amount", 0))


@lru_cache
def get_paystack_client() -> PaystackClient:
    settings = get_settings()
    if settings.paystack_secret_key:
        return LivePaystackClient(settings.paystack_secret_key)
    return SandboxPaystackClient()
