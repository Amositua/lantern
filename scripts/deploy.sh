#!/usr/bin/env bash
# Builds and deploys every Lantern service to Cloud Run, then the dashboard.
#
# Requires: gcloud CLI authenticated against GCP_PROJECT_ID, an Artifact
# Registry Docker repo named "lantern" in GCP_REGION, and env.yaml filled
# in from env.yaml.example for the runtime env vars each service reads.
set -euo pipefail

: "${GCP_PROJECT_ID:?set GCP_PROJECT_ID before running this script}"
: "${GCP_REGION:=us-central1}"

cd "$(dirname "$0")/.."

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

for entry in "${SERVICES[@]}"; do
  name="${entry%%:*}"
  module="${entry#*:}"
  image="${REPO}/${name}:${TAG}"

  echo "==> building ${name}"
  docker build -f backend/Dockerfile --build-arg "SERVICE_MODULE=${module}" -t "${image}" .

  echo "==> pushing ${name}"
  docker push "${image}"

  echo "==> deploying ${name} to Cloud Run"
  gcloud run deploy "lantern-${name}" \
    --image "${image}" \
    --project "${GCP_PROJECT_ID}" \
    --region "${GCP_REGION}" \
    --platform managed \
    --allow-unauthenticated \
    --env-vars-file "env.yaml"
done

echo "==> building and deploying dashboard"
dash_image="${REPO}/dashboard:${TAG}"
docker build -f frontend/Dockerfile -t "${dash_image}" frontend
docker push "${dash_image}"
gcloud run deploy lantern-dashboard \
  --image "${dash_image}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${GCP_REGION}" \
  --platform managed \
  --allow-unauthenticated

echo "==> done"
