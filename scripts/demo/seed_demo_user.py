"""Seeds the demo user's Life Graph: a profile, a trusted-circle contact,
an enrolled medication (via the pharmacy's own dispensing record -- tier 2
in the trust hierarchy, no separate human-verification step needed for
this path), a tokenized payment method, and a reference letter (embedded
into Cloud SQL/pgvector so prove_document_qa.py has something real to
retrieve). Run once against a real backend (needs GCP_PROJECT_ID and
CLOUD_SQL_INSTANCE_CONNECTION_NAME configured) before recording the demo.
"""
from _client import ACTION_URL, DEMO_USER_ID, MEMORY_URL, call


def main() -> None:
    print(f"Seeding {DEMO_USER_ID} ...")

    call(
        "PUT",
        f"{MEMORY_URL}/users/{DEMO_USER_ID}/profile",
        {
            "name": "Amara",
            "language": "en",
            "literacy_level": "low",
            "pacing_pref": "slow, one step at a time",
            "abilities": {"low_vision": True, "speaks_slowly": True, "jargon_averse": True},
        },
    )
    print("  profile set")

    call(
        "POST",
        f"{MEMORY_URL}/users/{DEMO_USER_ID}/people",
        {
            "name": "Aunty Bisi",
            "relation": "daughter",
            "roles": ["trusted_circle", "caregiver", "emergency"],
            "contact": "+234 800 000 0000",
        },
    )
    print("  trusted-circle contact added")

    medication = call(
        "POST",
        f"{ACTION_URL}/enrollment/medications/import-dispensing-record",
        {"user_id": DEMO_USER_ID, "pharmacy_ref": "pharmarun_demo", "dispensing_record_id": "DR-1001"},
    )
    print(f"  medication enrolled: {medication['name']} {medication['dose']} (id={medication['id']})")

    payment = call(
        "POST",
        f"{ACTION_URL}/enrollment/payment",
        {
            "user_id": DEMO_USER_ID,
            "paystack_reference": "demo_success_seed",
            "per_transaction_cap": 10000,
            "daily_cap": 20000,
            "never_auto_categories": [],
        },
    )
    print(f"  payment enrolled: card ending in {payment['card_last4']}")

    call(
        "POST",
        f"{MEMORY_URL}/users/{DEMO_USER_ID}/documents",
        {
            "type": "letter",
            "uri": "seed:cardiology-appointment-letter",
            "text": (
                "City General Hospital, Cardiology Department. Dear Amara, your next "
                "cardiology follow-up appointment is on Thursday the 14th at 10:30am with "
                "Dr. Adeyemi. Please bring your current medication list. Call 0800-555-0102 "
                "to reschedule."
            ),
        },
    )
    print("  reference document enrolled: cardiology appointment letter (embedded via Cloud SQL/pgvector)")

    print(f"\nDone. Life Graph: {MEMORY_URL}/users/{DEMO_USER_ID}/life-graph")


if __name__ == "__main__":
    main()
