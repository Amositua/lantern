#!/usr/bin/env bash
# The one script: starts the whole fleet, seeds a demo user, and prints
# the demo runbook. Pharmacy and Paystack stay sandboxed regardless, but
# this needs a real GCP_PROJECT_ID -- the Life Graph itself is genuinely
# Firestore, and that's the point.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

if [ ! -f .env ]; then
  echo "No .env found -- copy .env.example to .env and fill in GCP_PROJECT_ID first." >&2
  exit 1
fi

set -a
source .env
set +a

# Windows ships a `python3` PATH entry that's really a Microsoft Store
# redirect stub, not an interpreter -- `command -v` finds it, but running
# it fails. Actually invoking each candidate is the only reliable check.
if python3 -c "" >/dev/null 2>&1; then
  SYSTEM_PYTHON=python3
elif python -c "" >/dev/null 2>&1; then
  SYSTEM_PYTHON=python
else
  echo "No working Python interpreter found (tried python3, python)." >&2
  exit 1
fi

# A project-local venv, not whatever happens to be first on PATH -- a
# machine with more than one Python install can otherwise pick up an
# unrelated uvicorn with none of this project's dependencies installed,
# which fails silently rather than with a useful error.
if [ ! -d .venv ]; then
  echo "creating backend/.venv ..."
  "$SYSTEM_PYTHON" -m venv .venv
fi

if [ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]; then
  VENV_BIN="$REPO_ROOT/.venv/Scripts"
else
  VENV_BIN="$REPO_ROOT/.venv/bin"
fi
PYTHON="$VENV_BIN/python"
UVICORN="$VENV_BIN/uvicorn"

echo "installing backend dependencies into .venv ..."
"$PYTHON" -m pip install --quiet -r backend/requirements.txt

declare -A PORTS=(
  [orchestrator]=8080
  [perception]=8081
  [clarifier]=8082
  [action]=8083
  [safety_router]=8084
  [memory]=8085
  [live_session_gateway]=8086
)

pids=()
cleanup() {
  echo "stopping services..."
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT

for service in "${!PORTS[@]}"; do
  port="${PORTS[$service]}"
  echo "starting ${service} on :${port}"
  (cd backend && PORT="${port}" "$UVICORN" "services.${service}.main:app" --host 0.0.0.0 --port "${port}") &
  pids+=($!)
done

echo "waiting for the fleet to come up..."
failed=()
for service in "${!PORTS[@]}"; do
  port="${PORTS[$service]}"
  up=false
  for _ in $(seq 1 30); do
    curl -sf "http://localhost:${port}/health" > /dev/null 2>&1 && up=true && break
    sleep 1
  done
  [ "$up" = true ] || failed+=("$service")
done

if [ "${#failed[@]}" -gt 0 ]; then
  echo "these services never came up: ${failed[*]}" >&2
  echo "check the output above for the actual error." >&2
  exit 1
fi

echo "seeding the demo user..."
"$PYTHON" scripts/demo/seed_demo_user.py

echo "starting dashboard dev server..."
(cd frontend && npm run dev) &
pids+=($!)

cat <<RUNBOOK

======================================================================
 Demo runbook
======================================================================
 1. Open the dashboard (Vite prints the URL above, usually
    http://localhost:5173).
 2. Show enrollment: the Life Graph panel already lists the seeded
    medication and payment method (scripts/demo/seed_demo_user.py).
 3. Point + speak: "I'm running low on this" -- or in the dashboard,
    choose "Reorder" next to the medication directly.
 4. Confirm -- the Life Graph and activity log panels update live.
 5. The safety proof, in a second terminal:
      $PYTHON scripts/demo/prove_stale_abort.py
    changes the Rx behind the scenes and shows Lantern abort the
    reorder rather than act on stale information.
 6. The no-double-charge proof:
      $PYTHON scripts/demo/prove_no_double_charge.py
    simulates a Paystack timeout and shows verify-before-retry keep it
    to a single charge.
 7. The document RAG proof (needs CLOUD_SQL_INSTANCE_CONNECTION_NAME set):
      $PYTHON scripts/demo/prove_document_qa.py
    asks about the seeded appointment letter, then asks something no
    document covers -- shows Lantern answer grounded, then refuse to
    guess rather than invent an answer.
 8. The crisis-handoff proof:
      $PYTHON scripts/demo/prove_crisis_handoff.py
    a crisis phrase halts an in-progress reorder and hands off to a real
    trusted contact instead of a guess.
 9. The appointment domain, same propose-confirm-execute gate, no
    payment behind it:
      $PYTHON scripts/demo/prove_appointment_confirm.py
    confirms an appointment extracted by Gemini from the enrolled
    letter, with nothing booked until confirmed.
10. Delivery tracking, live over Pub/Sub:
      $PYTHON scripts/demo/simulate_delivery.py
    places an order, then steps it through preparing -> out for delivery
    -> delivered, each landing as its own activity-log entry.
11. Trusted-circle companion page -- open companion.html (same dev
    server, e.g. http://localhost:5173/companion.html) on a second
    device or tab: anything routed to a trusted-circle approval (a
    large reorder, or an unanswered nudge escalated after repeats) shows
    up there, gated by the same trust check the main dashboard uses --
    a wrong name is really rejected, not just hidden in the UI.

 Cloud Console, to show alongside: Firestore, Pub/Sub, Vertex AI, and
 Cloud SQL for the project in your .env.
======================================================================

RUNBOOK

wait
