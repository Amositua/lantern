"""Paystack behind an interface — sandbox impl so we can demo without a
live secret key."""
import abc
import hashlib
from dataclasses import dataclass
from typing import Optional

from common.config import get_settings


class PaystackError(RuntimeError):
    pass


@dataclass
class VerifiedTransaction:
    reference: str
    status: str
    authorization_code: Optional[str]
    channel: Optional[str]
    reusable: bool


class PaystackClient(abc.ABC):
    @abc.abstractmethod
    def verify_transaction(self, reference: str) -> VerifiedTransaction:
        ...


class SandboxPaystackClient(PaystackClient):
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
        )


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
        )


def get_paystack_client() -> PaystackClient:
    settings = get_settings()
    if settings.paystack_secret_key:
        return LivePaystackClient(settings.paystack_secret_key)
    return SandboxPaystackClient()
