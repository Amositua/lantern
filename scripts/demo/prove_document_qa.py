"""The third proof: RAG over the user's own documents, grounded honestly.
Asks a question the seeded letter actually answers, and one it doesn't --
the second call has to come back "not in your documents", never a guessed
answer pulled from Gemini's general knowledge.
"""
from _client import CLARIFIER_URL, DEMO_USER_ID, call


def main() -> None:
    print("1. Asking a question the enrolled letter actually answers ...")
    answered = call(
        "POST",
        f"{CLARIFIER_URL}/clarify/document-question",
        {"user_id": DEMO_USER_ID, "question": "When is my next cardiology appointment?"},
    )
    print(f"   grounded={answered['grounded']}")
    print(f"   {answered['answer']}")
    if answered["sources"]:
        print(f"   source: {answered['sources'][0]['type']} document")

    print("\n2. Asking something no enrolled document covers ...")
    unanswered = call(
        "POST",
        f"{CLARIFIER_URL}/clarify/document-question",
        {"user_id": DEMO_USER_ID, "question": "What's the weather like tomorrow?"},
    )
    print(f"   grounded={unanswered['grounded']}")
    print(f"   {unanswered['answer']}")

    if answered["grounded"] and not unanswered["grounded"]:
        print("\nThe RAG grounding worked: answered from the real letter, refused to")
        print("guess when nothing on file actually covered the question.")
    else:
        print("\nUnexpected result -- expected the first grounded and the second not.")


if __name__ == "__main__":
    main()
