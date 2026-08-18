# Lantern

Lantern is a voice-and-vision assistant that completes real-world tasks — starting with
medication refills — for people the digital world locks out. You point a camera and speak;
Lantern checks what it sees against what it already knows about you (the Life Graph), proposes
an action, waits for your confirmation, and then actually carries it out through a pharmacy
rail and Paystack.

See `ARCHITECTURE.md` for the full design.

## Layout

```
backend/
  common/            shared config, logging, and Google Cloud client factories
  services/
    orchestrator/          routes a turn to the right agent and sequences the result
    perception/             reads the camera/voice turn and matches it to the Life Graph
    clarifier/               asks the clarifying question, adapts pacing to the user
    action/                   calls the pharmacy rail + Paystack behind a confirmation gate
    safety_router/            halts and hands off on crisis or low confidence
    memory/                   the sole writer to the Life Graph — see below
    live_session_gateway/     holds the Gemini Live voice+video session
  tests/              unit tests for the Life Graph's trust rules + a static sole-writer guard
  Dockerfile         one image, parameterized by SERVICE_MODULE, used for every service
  requirements.txt
frontend/            the dashboard, a Vite + TypeScript single-page app
scripts/
  dev.sh              runs the whole fleet locally without Docker
  deploy.sh           builds, pushes, and deploys every service + the dashboard to Cloud Run
docker-compose.yml    runs the whole fleet locally with Docker
```

Every service is a small FastAPI app. They share one codebase and one Docker image so the
multi-agent topology stays legible without seven copies of the same boilerplate; each is still
deployed as its own Cloud Run service.

### The Memory Agent and the Life Graph

`backend/services/memory` is the only code in the repo that ever touches Firestore or Cloud SQL
— `get_firestore_client`/`get_cloud_sql_engine` live in `services/memory/clients.py`, not in the
shared `common` package, so no other service can import its way around the rule. Every other
service reaches user memory through Memory Agent's HTTP API.

Two trust rules are enforced in `services/memory/life_graph.py`, not just documented:

- **Medications.** Changing a medication's `name` or `dose` — creating one, or patching an
  existing one — requires a `verification` block (`prescription_verified`,
  `pharmacist_verified`, `trusted_circle_verified`, or `dispensing_record_import`). Creation
  requires it at the schema level (Pydantic rejects the request before it reaches Firestore);
  updates check it in `update_medication`, which rejects a bare dose/name change with a
  `TrustViolation` → HTTP 403. Non-identity fields (cadence, pharmacy_ref, condition) can update
  without it.
- **Preferences.** A first-time preference is stored provisional (low confidence, single
  observation). Repeated confirmations raise its confidence until it hardens. A value that
  contradicts an already-hardened preference never overwrites it — it raises a
  `resolution_event` instead, which a human resolves via `POST
  /users/{id}/resolution-events/{event_id}/resolve`. A one-off correction (`is_override: true`)
  is logged to the preference's history but never becomes the standing belief.

`backend/tests/test_life_graph.py` exercises both rules directly (with an in-memory fake
Firestore, so no project or emulator needed) and `backend/tests/test_sole_writer.py` statically
checks that no other service imports a Firestore/Cloud SQL client. Run them with:

```bash
pip install -r backend/requirements-dev.txt
cd backend && pytest
```

`GET /users/{id}/life-graph` renders the belief summary the dashboard's Life Graph panel reads:
profile, medications, people, a redacted payment summary (token presence + caps, never the raw
token), preferences, pending resolution events, and recent audit entries.

### Trusted enrollment (Action Agent)

`backend/services/action` owns the two flows that put verified truth into the Life Graph — the
only two callers who can ever hand the Memory Agent a medication's `verification` block or a
payment's token. Nothing here is reachable from a bare voice turn.

- **Medication, by prescription.** `POST /enrollment/medications/prescription/extract` runs
  Gemini Pro structured extraction (`gemini_extraction.py`) over a prescription image and stores
  it as a `document` — but writes nothing to the Life Graph yet. A human reviews the extracted
  fields (correcting anything misread) and calls `POST
  /enrollment/medications/prescription/verify` with the confirmed fields and a verification
  block; only that second call reaches the Memory Agent. The same endpoint accepts
  `trusted_circle_verified`, which `enrollment.py` checks against the user's own `people` list
  (must be recorded with role `trusted_circle` or `caregiver`) before it's accepted — a claimed
  trusted-circle identity that isn't on record is rejected with 403, not trusted on say-so.
- **Medication, by dispensing record.** `POST /enrollment/medications/import-dispensing-record`
  pulls a record from the pharmacy aggregator (`pharmacy_client.py`, abstracted behind an
  interface with a `SandboxPharmacyClient` fixture for the demo) and writes it straight through,
  since the pharmacy's own record is already tier-2 in the trust hierarchy.
- **Payment.** `POST /enrollment/payment` takes only a Paystack transaction `reference` — never
  card data — verifies it server-side (`paystack_client.py`, same sandbox/live split), and if the
  first-transaction 2FA actually completed, stores the resulting `authorization_code` alongside
  the per-transaction cap, daily cap, and never-auto list the caller supplied. A failed or
  incomplete transaction never reaches the Memory Agent, and the request schema's `extra="forbid"`
  rejects any attempt to attach raw card fields at the API boundary.

Action never touches Firestore either — `memory_client.py` is a small HTTP client that calls the
Memory Agent's API, the same as any other service would.

## Stack

| Requirement | Where |
|---|---|
| Gemini 3.5 (Flash + Pro) via Vertex AI | `backend/common/gcp_clients.py:get_genai_client`, used by perception, clarifier, safety_router, live_session_gateway, action |
| Gemini Live API | live_session_gateway (voice+video session) |
| Google ADK | `backend/services/orchestrator/adk_agent.py` |
| GenAI SDK | structured output — `services/action/gemini_extraction.py` extracts prescription fields into a Pydantic schema at enrollment |
| Firestore | Life Graph + per-user case state (`services/memory/clients.py:get_firestore_client`, memory-only) |
| Cloud SQL + pgvector | RAG over user documents (`services/memory/clients.py:get_cloud_sql_engine`, memory-only) |
| Cloud Run | every service below, scale-to-zero |
| Pub/Sub | async refill/delivery/re-engagement events (`get_pubsub_publisher`) |

## Local development

Without Docker:

```bash
cp .env.example .env      # fill in GCP_PROJECT_ID etc. once you have a project
pip install -r backend/requirements.txt
(cd frontend && npm install)
scripts/dev.sh
```

With Docker:

```bash
cp .env.example .env
docker compose up --build
```

Either way, the orchestrator comes up on `:8080` and every other service on `:8081`–`:8086`.
Check the fleet is wired together:

```bash
curl http://localhost:8080/health          # this service only
curl http://localhost:8080/health/deep     # tries to construct each Google client it needs
curl http://localhost:8080/hello           # fans out to every downstream service's /health
```

`/health/deep` reports `not configured: ...` instead of failing when a credential or project id
isn't set yet — that's expected until real GCP config lands. `/hello` is the scaffold's
round-trip proof that the orchestrator can actually reach the rest of the fleet.

The dashboard dev server runs on `:5173`.

## Environment variables

See `.env.example` for local/Docker runs and `env.yaml.example` for Cloud Run deploys. Every
variable a service reads is defined in `backend/common/config.py`:

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `local` or `production`, surfaced on `/health` |
| `GCP_PROJECT_ID` | required for Vertex AI, Firestore, Pub/Sub |
| `GCP_REGION` | Cloud Run / Artifact Registry region |
| `VERTEX_LOCATION` | Vertex AI location for Gemini calls |
| `GEMINI_FLASH_MODEL`, `GEMINI_PRO_MODEL` | model ids used by the GenAI client |
| `FIRESTORE_DATABASE` | Firestore database id (`(default)` unless you've created a named one) |
| `CLOUD_SQL_INSTANCE_CONNECTION_NAME` | `project:region:instance` for the Cloud SQL connector |
| `CLOUD_SQL_DATABASE`, `CLOUD_SQL_USER`, `CLOUD_SQL_PASSWORD` | Cloud SQL credentials |
| `PUBSUB_TOPIC_PREFIX` | prefix applied to every Pub/Sub topic Lantern creates |
| `PHARMACY_AGGREGATOR_BASE_URL`, `PHARMACY_AGGREGATOR_API_KEY` | pharmacy rail credentials |
| `PAYSTACK_SECRET_KEY` | Paystack secret key — server-side only, never sent to the client |
| `ORCHESTRATOR_URL`, `PERCEPTION_URL`, `CLARIFIER_URL`, `ACTION_URL`, `SAFETY_ROUTER_URL`, `MEMORY_URL`, `LIVE_SESSION_GATEWAY_URL` | how services find each other |

All secrets are read from the server-side environment (Secret Manager in Cloud Run). None of
them are ever sent to or read by the frontend.

## Deploying

```bash
export GCP_PROJECT_ID=your-project
export GCP_REGION=us-central1
cp env.yaml.example env.yaml   # fill in real values
scripts/deploy.sh
```

This builds every service from the one Dockerfile (varying only `SERVICE_MODULE`), pushes each
to Artifact Registry, and deploys it to Cloud Run, then does the same for the dashboard. Run it
a second time after the first deploy to fill in the real `*_URL` values in `env.yaml` once
Cloud Run has assigned them.

Requires: `gcloud` authenticated against `GCP_PROJECT_ID`, and an Artifact Registry Docker repo
named `lantern` already created in `GCP_REGION`.
