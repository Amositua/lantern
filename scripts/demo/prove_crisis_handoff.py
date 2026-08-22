"""The third safety proof: a crisis phrase halts and hands off instead of
letting anything proceed. Proposes a reorder like any normal turn would,
then simulates a crisis utterance arriving on the same case -- Safety
Router has to veto it on the spot, and the case has to actually become
unconfirmable, not just report a verdict.
"""
from _client import ACTION_URL, DEMO_USER_ID, MEMORY_URL, SAFETY_ROUTER_URL, call


def main() -> None:
    medications = call("GET", f"{MEMORY_URL}/users/{DEMO_USER_ID}/medications")
    if not medications:
        raise SystemExit("No medications on file -- run seed_demo_user.py first.")
    med_id = medications[0]["id"]

    print("1. Proposing a reorder, same as any normal turn ...")
    proposal = call("POST", f"{ACTION_URL}/reorder/propose", {"user_id": DEMO_USER_ID, "med_id": med_id})
    print(f"   {proposal['read_back']}")

    print("\n2. A crisis phrase comes in on the same turn ...")
    result = call(
        "POST",
        f"{SAFETY_ROUTER_URL}/safety/check",
        {"user_id": DEMO_USER_ID, "utterance": "I have chest pain and can't breathe", "case_id": proposal["case_id"]},
    )
    print(f"   verdict={result['verdict']} trigger={result['trigger']}")
    print(f"   {result['reason']}")
    handoff = result["handoff"]
    if handoff.get("name"):
        print(f"   handing off to {handoff['name']} ({handoff['relation']}): {handoff['contact']}")
    else:
        print(f"   handing off to: {handoff['contact']} ({handoff['source']})")

    print("\n3. Trying to confirm the vetoed case anyway ...")
    confirm_refused = False
    try:
        call(
            "POST",
            f"{ACTION_URL}/reorder/confirm",
            {"user_id": DEMO_USER_ID, "case_id": proposal["case_id"], "confirmed": True, "step_up_token": "000000"},
        )
    except SystemExit:
        # expected -- a vetoed case is no longer in "proposed" state, so
        # Action's own confirm-time check refuses it independently of
        # Safety Router's own verdict
        confirm_refused = True
        print("   confirm was refused, as expected -- the case is no longer confirmable.")

    if result["verdict"] == "halt" and result["vetoed_case_id"] == proposal["case_id"] and confirm_refused:
        print("\nThe crisis handoff worked: Lantern stopped mid-flow, handed off to a")
        print("real contact instead of a guess, and the vetoed case couldn't be confirmed after.")
    else:
        print("\nUnexpected result -- expected a halt that vetoed this exact case.")


if __name__ == "__main__":
    main()
