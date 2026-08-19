"""The safety proof. Records when this "refill check" was scheduled,
changes the medication's dose behind the scenes through the normal
trusted-enrollment path, then fires the re-engagement event with the
*original* scheduled_at. Lantern re-reads current state at fire time and
aborts rather than reordering against what's now a stale assumption.
"""
from datetime import datetime, timezone

from _client import ACTION_URL, DEMO_USER_ID, MEMORY_URL, call


def main() -> None:
    medications = call("GET", f"{MEMORY_URL}/users/{DEMO_USER_ID}/medications")
    if not medications:
        raise SystemExit("No medications on file -- run seed_demo_user.py first.")
    med = medications[0]
    med_id = med["id"]

    scheduled_at = datetime.now(timezone.utc).isoformat()
    print(f"1. Refill check scheduled for {med['name']} at {scheduled_at}")

    print(f"2. Changing the Rx behind the scenes: {med['name']} {med['dose']} -> 20mg")
    call(
        "PATCH",
        f"{MEMORY_URL}/users/{DEMO_USER_ID}/medications/{med_id}",
        {"dose": "20mg", "verification": {"method": "pharmacist_verified", "verified_by": "Pharm. Okafor (demo)"}},
    )

    print("3. Firing the re-engagement event with the *original* scheduled_at ...")
    result = call(
        "POST",
        f"{ACTION_URL}/reengagement/fire",
        {"user_id": DEMO_USER_ID, "med_id": med_id, "scheduled_at": scheduled_at},
    )

    print(f"\nResult: {result['status']}")
    print(result["message"])
    if result["status"] == "aborted_rx_changed":
        print("\nThe stale-reorder abort worked: Lantern re-read the medication fresh")
        print("and refused to act on the assumption it had when this was scheduled.")
    else:
        print("\nUnexpected result -- expected aborted_rx_changed.")


if __name__ == "__main__":
    main()
