#!/usr/bin/env bash
# Builds and deploys every Lantern service to Cloud Run, then the dashboard.
#
# Builds run on Cloud Build, not a local Docker daemon -- one less thing
# that has to be installed and running to reproduce this. Two passes
# happen automatically in one run: the first stands every service up so
# their real Cloud Run URLs exist, the second points every service at its
# actual peers (and the dashboard's real origin, for CORS) and rebuilds
# the dashboard against the real backend URLs -- no manual "run it twice."
#
# Requires: gcloud authenticated against GCP_PROJECT_ID, an Artifact
# Registry Docker repo named "lantern" in GCP_REGION, and env.yaml filled
# in from env.yaml.example.
set -euo pipefail

: "${GCP_PROJECT_ID:?set GCP_PROJECT_ID before running this script}"
: "${GCP_REGION:=us-central1}"

cd "$(dirname "$0")/.."

if [ ! -f env.yaml ]; then
  echo "No env.yaml found -- copy env.yaml.example to env.yaml and fill in first." >&2
  exit 1
fi

REPO="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/lantern"
TAG="$(git rev-parse --short HEAD 2>/dev/null || echo local)"

SERVICES=(
  "orchestrator:services.orchestrator.main:app"
  "perception:services.perception.main:app"
  "clarifier:services.clarifier.main:app"
  "action:services.action.main:app"
  "safety-router:services.safety_router.main:app"
  "memory:services.memory.main:app"
  "live-session-gateway:services.live_session_gateway.main:app"
)

BACKEND_BUILD_CONFIG="$(mktemp)"
cat > "$BACKEND_BUILD_CONFIG" <<'EOF'
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-f', 'backend/Dockerfile', '--build-arg', 'SERVICE_MODULE=${_SERVICE_MODULE}', '-t', '${_IMAGE}', '.']
images: ['${_IMAGE}']
EOF

declare -A SERVICE_URL

echo "==> pass 1: build and deploy every backend service"
for entry in "${SERVICES[@]}"; do
  name="${entry%%:*}"
  module="${entry#*:}"
  image="${REPO}/${name}:${TAG}"

  echo "==> building ${name}"
  gcloud builds submit . \
    --project "${GCP_PROJECT_ID}" \
    --config "${BACKEND_BUILD_CONFIG}" \
    --substitutions="_SERVICE_MODULE=${module},_IMAGE=${image}"

  echo "==> deploying ${name} to Cloud Run"
  extra_flags=()
  if [ "${name}" = "live-session-gateway" ]; then
    # Holds an open Live session + WebSocket registry in-process -- has to
    # stay pinned to one instance for a reconnect to find it again.
    extra_flags+=(--session-affinity --min-instances=1 --max-instances=1)
  fi
  gcloud run deploy "lantern-${name}" \
    --image "${image}" \
    --project "${GCP_PROJECT_ID}" \
    --region "${GCP_REGION}" \
    --platform managed \
    --allow-unauthenticated \
    --env-vars-file "env.yaml" \
    "${extra_flags[@]}"

  url="$(gcloud run services describe "lantern-${name}" --project "${GCP_PROJECT_ID}" --region "${GCP_REGION}" --format='value(status.url)')"
  SERVICE_URL["${name}"]="${url}"
  echo "    ${name} -> ${url}"
done
rm -f "${BACKEND_BUILD_CONFIG}"

echo "==> building and deploying the dashboard, pointed at the real backend URLs"
gateway_url="${SERVICE_URL[live-session-gateway]}"
gateway_ws_url="wss://${gateway_url#https://}/ws/session"
dash_image="${REPO}/dashboard:${TAG}"

FRONTEND_BUILD_CONFIG="$(mktemp)"
cat > "$FRONTEND_BUILD_CONFIG" <<'EOF'
steps:
  - name: gcr.io/cloud-builders/docker
    args:
      - build
      - -f
      - Dockerfile
      - --build-arg
      - VITE_MEMORY_URL=${_VITE_MEMORY_URL}
      - --build-arg
      - VITE_ACTION_URL=${_VITE_ACTION_URL}
      - --build-arg
      - VITE_LIVE_SESSION_GATEWAY_WS_URL=${_VITE_GATEWAY_WS_URL}
      - -t
      - ${_IMAGE}
      - .
images: ['${_IMAGE}']
EOF

gcloud builds submit frontend \
  --project "${GCP_PROJECT_ID}" \
  --config "${FRONTEND_BUILD_CONFIG}" \
  --substitutions="_VITE_MEMORY_URL=${SERVICE_URL[memory]},_VITE_ACTION_URL=${SERVICE_URL[action]},_VITE_GATEWAY_WS_URL=${gateway_ws_url},_IMAGE=${dash_image}"
rm -f "${FRONTEND_BUILD_CONFIG}"

gcloud run deploy lantern-dashboard \
  --image "${dash_image}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${GCP_REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --port 80

dashboard_url="$(gcloud run services describe lantern-dashboard --project "${GCP_PROJECT_ID}" --region "${GCP_REGION}" --format='value(status.url)')"
echo "    dashboard -> ${dashboard_url}"

echo "==> pass 2: point every service at its real peers and the dashboard's real origin"
peer_env="ORCHESTRATOR_URL=${SERVICE_URL[orchestrator]},PERCEPTION_URL=${SERVICE_URL[perception]},CLARIFIER_URL=${SERVICE_URL[clarifier]},ACTION_URL=${SERVICE_URL[action]},SAFETY_ROUTER_URL=${SERVICE_URL[safety-router]},MEMORY_URL=${SERVICE_URL[memory]},LIVE_SESSION_GATEWAY_URL=${SERVICE_URL[live-session-gateway]},DASHBOARD_ORIGIN=${dashboard_url}"
for entry in "${SERVICES[@]}"; do
  name="${entry%%:*}"
  gcloud run services update "lantern-${name}" \
    --project "${GCP_PROJECT_ID}" \
    --region "${GCP_REGION}" \
    --update-env-vars "${peer_env}"
done

echo "==> done"
echo "Dashboard: ${dashboard_url}"
