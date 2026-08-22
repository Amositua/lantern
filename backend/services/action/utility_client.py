"""Utility biller behind an interface, same shape as pharmacy_client.py --
a sandbox implementation so account import and bill payment both work
without a live key."""
import abc
import uuid
from dataclasses import dataclass
from typing import Optional

from common.config import get_settings


class UtilityError(RuntimeError):
    pass


@dataclass
class AccountStatement:
    provider: str
    category: str
    account_ref: str
    amount_due_kobo: int
    due_date: Optional[str]


@dataclass
class PaymentResult:
    reference: str
    amount_kobo: int


class UtilityClient(abc.ABC):
    @abc.abstractmethod
    def get_account_statement(self, provider: str, account_ref: str) -> AccountStatement:
        ...

    @abc.abstractmethod
    def get_amount_due(self, provider: str, account_ref: str) -> int:
        """Returns the currently-due amount in kobo."""

    @abc.abstractmethod
    def pay_bill(self, provider: str, account_ref: str, amount_kobo: int) -> PaymentResult:
        ...


class SandboxUtilityClient(UtilityClient):
    _FIXTURES = {
        "ACC-EKEDC-1": AccountStatement(
            provider="EKEDC",
            category="electricity",
            account_ref="ACC-EKEDC-1",
            amount_due_kobo=850000,
            due_date="the 28th",
        ),
    }
    _DEFAULT_AMOUNT_KOBO = 850000  # ₦8,500

    def get_account_statement(self, provider: str, account_ref: str) -> AccountStatement:
        record = self._FIXTURES.get(account_ref)
        if record is None or record.provider != provider:
            raise UtilityError(f"no account {account_ref!r} on file with provider {provider!r}")
        return record

    def get_amount_due(self, provider: str, account_ref: str) -> int:
        record = self._FIXTURES.get(account_ref)
        return record.amount_due_kobo if record else self._DEFAULT_AMOUNT_KOBO

    def pay_bill(self, provider: str, account_ref: str, amount_kobo: int) -> PaymentResult:
        return PaymentResult(reference=f"util_{uuid.uuid4().hex[:12]}", amount_kobo=amount_kobo)


class LiveUtilityClient(UtilityClient):
    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url
        self._api_key = api_key

    def get_account_statement(self, provider: str, account_ref: str) -> AccountStatement:
        import httpx

        resp = httpx.get(
            f"{self._base_url}/providers/{provider}/accounts/{account_ref}",
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return AccountStatement(
            provider=provider,
            category=data.get("category", "utility"),
            account_ref=account_ref,
            amount_due_kobo=data["amount_due_kobo"],
            due_date=data.get("due_date"),
        )

    def get_amount_due(self, provider: str, account_ref: str) -> int:
        return self.get_account_statement(provider, account_ref).amount_due_kobo

    def pay_bill(self, provider: str, account_ref: str, amount_kobo: int) -> PaymentResult:
        import httpx

        resp = httpx.post(
            f"{self._base_url}/providers/{provider}/accounts/{account_ref}/payments",
            json={"amount_kobo": amount_kobo},
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return PaymentResult(reference=data["reference"], amount_kobo=data["amount_kobo"])


def get_utility_client() -> UtilityClient:
    settings = get_settings()
    if settings.utility_aggregator_base_url and settings.utility_aggregator_api_key:
        return LiveUtilityClient(settings.utility_aggregator_base_url, settings.utility_aggregator_api_key)
    return SandboxUtilityClient()
