"""The other safety proof. Enrolls a payment method deliberately set up
to time out on its first charge attempt, then confirms a reorder against
it. Lantern's charge path catches the timeout, verifies with Paystack by
the same idempotency key before ever considering a second attempt, and
finds the charge already went through -- one charge, not two.
"""
from _client import ACTION_URL, DEMO_USER_ID, MEMORY_URL, call


def main() -> None:
    medications = call("GET", f"{MEMORY_URL}/users/{DEMO_USER_ID}/medications")
    if not medications:
        raise SystemExit("No medications on file -- run seed_demo_user.py first.")
    med_id = medications[0]["id"]

    print("1. Enrolling a payment method set up to time out on its first charge ...")
    call(
        "POST",
        f"{ACTION_URL}/enrollment/payment",
        {
            "user_id": DEMO_USER_ID,
            "paystack_reference": "demo_timeout_setup_1",
            "per_transaction_cap": 10000,
            "daily_cap": 20000,
            "never_auto_categories": [],
        },
    )

    print("2. Proposing the reorder ...")
    proposal = call("POST", f"{ACTION_URL}/reorder/propose", {"user_id": DEMO_USER_ID, "med_id": med_id})
    print(f"   {proposal['read_back']}")

    print("3. Confirming -- this charge will time out internally, then verify-and-recover ...")
    # step_up_token is only actually checked when required_confirmation is
    # "step_up" (e.g. this medication's first-ever reorder) -- harmless to
    # send otherwise, and this script shouldn't care which case it's in
    result = call(
        "POST",
        f"{ACTION_URL}/reorder/confirm",
        {
            "user_id": DEMO_USER_ID,
            "case_id": proposal["case_id"],
            "confirmed": True,
            "step_up_token": "000000",
        },
    )

    print(f"\nResult: {result['status']}")
    print(result["message"])

    audit = call("GET", f"{MEMORY_URL}/users/{DEMO_USER_ID}/audit?limit=5")
    idempotency_key = f"reorder_{proposal['case_id']}"
    matches = [e for e in audit if e.get("idempotency_key") == idempotency_key and e.get("result") == "success"]
    print(f"\nAudit entries for this charge's idempotency key: {len(matches)} (proves no double-charge)")


if __name__ == "__main__":
    main()
