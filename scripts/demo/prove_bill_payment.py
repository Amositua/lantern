"""Proves the second domain: the propose-confirm-execute + payment gate
generalizes past medication. Same read-back-then-confirm shape, same
risk-scaled confirmation, same verify-before-retry charge path -- reused
via billing.py, not reimplemented for utility bills.
"""
from _client import ACTION_URL, DEMO_USER_ID, MEMORY_URL, call


def main() -> None:
    bills = call("GET", f"{MEMORY_URL}/users/{DEMO_USER_ID}/bills")
    if not bills:
        raise SystemExit("No bills on file -- run seed_demo_user.py first.")
    bill_id = bills[0]["id"]

    print("1. Proposing the bill payment ...")
    proposal = call("POST", f"{ACTION_URL}/bills/propose", {"user_id": DEMO_USER_ID, "bill_id": bill_id})
    print(f"   {proposal['read_back']}")

    print(f"\n2. Confirming (required_confirmation={proposal['required_confirmation']}) ...")
    result = call(
        "POST",
        f"{ACTION_URL}/bills/confirm",
        {"user_id": DEMO_USER_ID, "case_id": proposal["case_id"], "confirmed": True, "step_up_token": "000000"},
    )
    print(f"\nResult: {result['status']}")
    print(result["message"])


if __name__ == "__main__":
    main()
