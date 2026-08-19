#!/usr/bin/env bash
# Runs every backend service locally with autoreload, then the dashboard
# dev server, so the fleet can be exercised without Docker.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

# Windows ships a `python3` PATH entry that's really a Microsoft Store
# redirect stub, not an interpreter -- actually invoking each candidate is
# the only reliable check.
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
# unrelated uvicorn with none of this project's dependencies installed.
if [ ! -d .venv ]; then
  echo "creating .venv ..."
  "$SYSTEM_PYTHON" -m venv .venv
fi

if [ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]; then
  VENV_BIN="$REPO_ROOT/.venv/Scripts"
else
  VENV_BIN="$REPO_ROOT/.venv/bin"
fi
UVICORN="$VENV_BIN/uvicorn"

echo "installing backend dependencies into .venv ..."
"$VENV_BIN/python" -m pip install --quiet -r backend/requirements.txt

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
  (cd backend && PORT="${port}" "$UVICORN" "services.${service}.main:app" --host 0.0.0.0 --port "${port}" --reload) &
  pids+=($!)
done

echo "backend services up, starting dashboard dev server..."
(cd frontend && npm run dev) || true

wait
