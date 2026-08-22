"""Shared in-memory stand-in for the Memory Agent's HTTP surface, used by
any test that needs to wire up common.memory_client without a real
Firestore project or the Memory Agent service running."""
from common.memory_client import MemoryAgentError


class FakeMemoryStore:
    def __init__(
        self,
        medication=None,
        medications=None,
        bill=None,
        bills=None,
        appointment=None,
        appointments=None,
        payment=None,
        audit=None,
        people=None,
        profile=None,
    ):
        seeded = list(medications or [])
        if medication:
            seeded.append(medication)
        self.medications = {m["id"]: dict(m) for m in seeded}

        seeded_bills = list(bills or [])
        if bill:
            seeded_bills.append(bill)
        self.bills = {b["id"]: dict(b) for b in seeded_bills}

        seeded_appointments = list(appointments or [])
        if appointment:
            seeded_appointments.append(appointment)
        self.appointments = {a["id"]: dict(a) for a in seeded_appointments}

        self.payment = dict(payment) if payment else None
        self.audit_log = list(audit or [])
        self.people = list(people or [])
        self.profile = dict(profile) if profile else {}
        self.cases = {}
        self._case_counter = 0

    def get_medication(self, user_id, med_id):
        return dict(self.medications[med_id])

    def list_medications(self, user_id):
        return [dict(m) for m in self.medications.values()]

    def update_medication(self, user_id, med_id, payload):
        self.medications[med_id].update(payload)
        return dict(self.medications[med_id])

    def get_bill(self, user_id, bill_id):
        return dict(self.bills[bill_id])

    def list_bills(self, user_id):
        return [dict(b) for b in self.bills.values()]

    def update_bill(self, user_id, bill_id, payload):
        self.bills[bill_id].update(payload)
        return dict(self.bills[bill_id])

    def get_appointment(self, user_id, appointment_id):
        return dict(self.appointments[appointment_id])

    def list_appointments(self, user_id):
        return [dict(a) for a in self.appointments.values()]

    def update_appointment(self, user_id, appointment_id, payload):
        self.appointments[appointment_id].update(payload)
        return dict(self.appointments[appointment_id])

    def get_payment(self, user_id):
        if self.payment is None:
            raise MemoryAgentError("no payment on file", status_code=404)
        return dict(self.payment)

    def list_people(self, user_id):
        return list(self.people)

    def get_life_graph(self, user_id):
        return {"profile": dict(self.profile)}

    def create_case(self, user_id, payload):
        self._case_counter += 1
        case = {"id": f"case-{self._case_counter}", **payload}
        self.cases[case["id"]] = case
        return dict(case)

    def get_case(self, user_id, case_id):
        if case_id not in self.cases:
            raise MemoryAgentError(f"case {case_id} not found", status_code=404)
        return dict(self.cases[case_id])

    def update_case(self, user_id, case_id, payload):
        self.cases[case_id].update(payload)
        return dict(self.cases[case_id])

    def list_cases(self, user_id):
        return [dict(c) for c in self.cases.values()]

    def append_audit(self, user_id, payload):
        entry = dict(payload)
        self.audit_log.append(entry)
        return entry

    def list_audit(self, user_id, limit=50):
        return list(reversed(self.audit_log))[:limit]
