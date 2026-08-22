"""Clinic/scheduling rail behind an interface, same shape as
pharmacy_client.py -- a sandbox implementation so rescheduling and
cancelling both work without a live key. No payment involved here,
unlike the pharmacy rail.
"""
import abc
import uuid
from dataclasses import dataclass


class ClinicError(RuntimeError):
    pass


@dataclass
class ScheduleResult:
    confirmation_ref: str
    new_time: str


class ClinicClient(abc.ABC):
    @abc.abstractmethod
    def confirm_attendance(self, provider: str, appointment_ref: str) -> ScheduleResult:
        ...

    @abc.abstractmethod
    def reschedule(self, provider: str, appointment_ref: str, new_time: str) -> ScheduleResult:
        ...

    @abc.abstractmethod
    def cancel(self, provider: str, appointment_ref: str) -> None:
        ...


class SandboxClinicClient(ClinicClient):
    def confirm_attendance(self, provider: str, appointment_ref: str) -> ScheduleResult:
        return ScheduleResult(confirmation_ref=f"sched_{uuid.uuid4().hex[:12]}", new_time=appointment_ref)

    def reschedule(self, provider: str, appointment_ref: str, new_time: str) -> ScheduleResult:
        return ScheduleResult(confirmation_ref=f"sched_{uuid.uuid4().hex[:12]}", new_time=new_time)

    def cancel(self, provider: str, appointment_ref: str) -> None:
        return None


class LiveClinicClient(ClinicClient):
    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url
        self._api_key = api_key

    def confirm_attendance(self, provider: str, appointment_ref: str) -> ScheduleResult:
        import httpx

        resp = httpx.post(
            f"{self._base_url}/providers/{provider}/appointments/{appointment_ref}/confirm",
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return ScheduleResult(confirmation_ref=data["confirmation_ref"], new_time=data["time"])

    def reschedule(self, provider: str, appointment_ref: str, new_time: str) -> ScheduleResult:
        import httpx

        resp = httpx.post(
            f"{self._base_url}/providers/{provider}/appointments/{appointment_ref}/reschedule",
            json={"new_time": new_time},
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return ScheduleResult(confirmation_ref=data["confirmation_ref"], new_time=data["time"])

    def cancel(self, provider: str, appointment_ref: str) -> None:
        import httpx

        resp = httpx.post(
            f"{self._base_url}/providers/{provider}/appointments/{appointment_ref}/cancel",
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=10.0,
        )
        resp.raise_for_status()


def get_clinic_client() -> ClinicClient:
    from common.config import get_settings

    settings = get_settings()
    if settings.clinic_aggregator_base_url and settings.clinic_aggregator_api_key:
        return LiveClinicClient(settings.clinic_aggregator_base_url, settings.clinic_aggregator_api_key)
    return SandboxClinicClient()
