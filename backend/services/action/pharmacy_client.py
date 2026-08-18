"""Pharmacy aggregator behind an interface — sandbox impl so import and
ordering both work without a live key."""
import abc
import uuid
from dataclasses import dataclass
from typing import Optional

from common.config import get_settings


class PharmacyError(RuntimeError):
    pass


@dataclass
class DispensingRecord:
    name: str
    dose: str
    condition: Optional[str]
    cadence: Optional[int]
    rx_ref: Optional[str]
    pharmacy_ref: str


@dataclass
class OrderResult:
    order_id: str
    amount_kobo: int
    eta: Optional[str] = None


class PharmacyClient(abc.ABC):
    @abc.abstractmethod
    def get_dispensing_record(self, pharmacy_ref: str, dispensing_record_id: str) -> DispensingRecord:
        ...

    @abc.abstractmethod
    def get_refill_price(self, pharmacy_ref: str, name: str, dose: str) -> int:
        """Returns the price in kobo."""

    @abc.abstractmethod
    def place_order(self, pharmacy_ref: str, name: str, dose: str) -> OrderResult:
        ...


class SandboxPharmacyClient(PharmacyClient):
    _FIXTURES = {
        "DR-1001": DispensingRecord(
            name="Amlodipine",
            dose="10mg",
            condition="blood pressure",
            cadence=30,
            rx_ref="RX-2201",
            pharmacy_ref="pharmarun_demo",
        ),
        "DR-1002": DispensingRecord(
            name="Metformin",
            dose="500mg",
            condition="diabetes",
            cadence=30,
            rx_ref="RX-2202",
            pharmacy_ref="pharmarun_demo",
        ),
    }

    # matches the demo script's own numbers where we have them, falls back
    # to a deterministic price for anything else so the demo stays repeatable
    _PRICES_KOBO = {
        ("amlodipine", "10mg"): 450000,  # ₦4,500
        ("metformin", "500mg"): 350000,  # ₦3,500
    }
    _DEFAULT_PRICE_KOBO = 400000  # ₦4,000

    def get_dispensing_record(self, pharmacy_ref: str, dispensing_record_id: str) -> DispensingRecord:
        record = self._FIXTURES.get(dispensing_record_id)
        if record is None or record.pharmacy_ref != pharmacy_ref:
            raise PharmacyError(f"no dispensing record {dispensing_record_id!r} at pharmacy {pharmacy_ref!r}")
        return record

    def get_refill_price(self, pharmacy_ref: str, name: str, dose: str) -> int:
        return self._PRICES_KOBO.get((name.lower(), dose.lower()), self._DEFAULT_PRICE_KOBO)

    def place_order(self, pharmacy_ref: str, name: str, dose: str) -> OrderResult:
        return OrderResult(
            order_id=f"order_{uuid.uuid4().hex[:12]}",
            amount_kobo=self.get_refill_price(pharmacy_ref, name, dose),
            eta="2-3 days",
        )


class LivePharmacyClient(PharmacyClient):
    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url
        self._api_key = api_key

    def get_dispensing_record(self, pharmacy_ref: str, dispensing_record_id: str) -> DispensingRecord:
        import httpx

        resp = httpx.get(
            f"{self._base_url}/pharmacies/{pharmacy_ref}/dispensing-records/{dispensing_record_id}",
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return DispensingRecord(
            name=data["drug_name"],
            dose=data["dose"],
            condition=data.get("condition"),
            cadence=data.get("cadence_days"),
            rx_ref=data.get("rx_ref"),
            pharmacy_ref=pharmacy_ref,
        )

    def get_refill_price(self, pharmacy_ref: str, name: str, dose: str) -> int:
        import httpx

        resp = httpx.get(
            f"{self._base_url}/pharmacies/{pharmacy_ref}/pricing",
            params={"drug_name": name, "dose": dose},
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()["amount_kobo"]

    def place_order(self, pharmacy_ref: str, name: str, dose: str) -> OrderResult:
        import httpx

        resp = httpx.post(
            f"{self._base_url}/pharmacies/{pharmacy_ref}/orders",
            json={"drug_name": name, "dose": dose},
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return OrderResult(order_id=data["order_id"], amount_kobo=data["amount_kobo"], eta=data.get("eta"))


def get_pharmacy_client() -> PharmacyClient:
    settings = get_settings()
    if settings.pharmacy_aggregator_base_url and settings.pharmacy_aggregator_api_key:
        return LivePharmacyClient(settings.pharmacy_aggregator_base_url, settings.pharmacy_aggregator_api_key)
    return SandboxPharmacyClient()
