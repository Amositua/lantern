"""Proves the appointment domain end to end: an appointment that came from
a real Gemini extraction over the enrolled letter (see seed_demo_user.py)
gets confirmed through the same propose-confirm-execute shape as a
reorder or a bill payment -- just without a charge behind it.
"""
from _client import ACTION_URL, DEMO_USER_ID, MEMORY_URL, call


def main() -> None:
    appointments = call("GET", f"{MEMORY_URL}/users/{DEMO_USER_ID}/appointments")
    if not appointments:
        raise SystemExit("No appointments on file -- run seed_demo_user.py first.")
    appointment_id = appointments[0]["id"]

    print("1. Proposing to confirm attendance ...")
    proposal = call(
        "POST",
        f"{ACTION_URL}/appointments/propose",
        {"user_id": DEMO_USER_ID, "appointment_id": appointment_id, "intent": "confirm_attendance"},
    )
    print(f"   {proposal['read_back']}")

    print("\n2. Confirming ...")
    result = call(
        "POST",
        f"{ACTION_URL}/appointments/confirm",
        {"user_id": DEMO_USER_ID, "case_id": proposal["case_id"], "confirmed": True},
    )
    print(f"\nResult: {result['status']}")
    print(result["message"])


if __name__ == "__main__":
    main()
