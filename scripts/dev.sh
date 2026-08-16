#!/usr/bin/env bash
# Runs every backend service locally with autoreload, then the dashboard
# dev server, so the fleet can be exercised without Docker.
set -euo pipefail

cd "$(dirname "$0")/.."

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
  (cd backend && PORT="${port}" uvicorn "services.${service}.main:app" --host 0.0.0.0 --port "${port}" --reload) &
  pids+=($!)
done

echo "backend services up, starting dashboard dev server..."
(cd frontend && npm run dev) || true

wait
