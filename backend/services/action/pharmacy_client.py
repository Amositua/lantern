"""Pharmacy aggregator behind an interface — sandbox impl so import works
without a live key. Order placement gets added here later."""
import abc
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


class PharmacyClient(abc.ABC):
    @abc.abstractmethod
    def get_dispensing_record(self, pharmacy_ref: str, dispensing_record_id: str) -> DispensingRecord:
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

    def get_dispensing_record(self, pharmacy_ref: str, dispensing_record_id: str) -> DispensingRecord:
        record = self._FIXTURES.get(dispensing_record_id)
        if record is None or record.pharmacy_ref != pharmacy_ref:
            raise PharmacyError(f"no dispensing record {dispensing_record_id!r} at pharmacy {pharmacy_ref!r}")
        return record


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


def get_pharmacy_client() -> PharmacyClient:
    settings = get_settings()
    if settings.pharmacy_aggregator_base_url and settings.pharmacy_aggregator_api_key:
        return LivePharmacyClient(settings.pharmacy_aggregator_base_url, settings.pharmacy_aggregator_api_key)
    return SandboxPharmacyClient()
