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
  `trusted_circle_verified`, which `trust_checks.py` checks against the user's own `people` list
  (must be recorded with role `trusted_circle` or `caregiver`) before it's accepted — a claimed
  trusted-circle identity that isn't on record is rejected with 403, not trusted on say-so. The
  same check backs the reorder confirmation gate below.
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

Action never touches Firestore either — `common/memory_client.py` is a small HTTP client that
calls the Memory Agent's API, the same as any other service would.

### Medication reorder + the confirmation gate

`backend/services/action/reorder.py` is the propose → confirm → execute gate itself.
`POST /reorder/propose` reads the medication and payment on file, prices the refill through the
pharmacy client, and — this is the part worth being explicit about — decides the required
confirmation strength right there (`determine_required_confirmation`):

- **`simple`** — under the per-transaction cap, not on the never-auto list, and this exact med
  has a prior successful reorder on record (checked against audit history, not just assumed).
- **`step_up`** — over the cap, on the never-auto list, or the *first* reorder of this med — "new
  or unfamiliar" needs an OTP even if the amount itself is small.
- **`trusted_circle`** — more than double the per-transaction cap. Step-up alone isn't enough;
  `/reorder/confirm` then checks `confirmed_by` against the user's own recorded people (same
  check `enrollment.py` uses for trusted-circle med enrollment, pulled into `trust_checks.py` so
  both places enforce it identically) rather than trusting whoever's name comes through.

Propose never charges anything — it only creates a Memory Agent `case` (state `proposed`,
carrying the priced proposal in its `data`) and returns a read-back sentence built from it:
identity, amount, payee, and a card descriptor (`"your GTBank card ending in 4242"` — the last4
Paystack returns at enrollment, never the PAN). `/reorder/confirm` requires that exact `case_id`
and `confirmed: true`; there's no other path to a charge. It re-checks everything against fresh
state, not the propose-time snapshot — including the duplicate-order guard (`last_refill` vs.
`cadence`), which runs once at propose (so a doomed request doesn't even get read back) and again
right before the actual charge, since a case can sit unconfirmed long enough for that to go stale.

The charge itself goes through `_charge_with_verify_before_retry`: the case's id becomes the
Paystack idempotency key, and if `charge_authorization` times out (an outcome the sandbox can
simulate on demand), the code checks `verify_charge` for that same key *before* ever considering
a second attempt — an already-succeeded charge is returned as-is, never repeated. Every branch —
declined, blocked on step-up, blocked on trusted-circle, aborted as a duplicate, executed, or
failed — writes one `audit` record.

### Async re-engagement — the stale-reorder abort

`backend/services/action/reengagement.py` is the other safety proof: a Pub/Sub event means
"re-assess," never "reorder." The event carries a `scheduled_at` timestamp and nothing about the
medication itself — no drug identity, no dose, no assumption baked in at schedule time — so
`evaluate_and_reengage` has to re-read the medication fresh on every fire and re-derive whether a
refill still makes sense:

- **Rx changed since scheduling** — the medication's `last_confirmed` is newer than
  `scheduled_at`, meaning something changed it after this check was queued. Abort.
- **Already reordered** — the same duplicate-order guard `reorder.py` uses (`last_refill` vs.
  `cadence`). Abort, nothing to do.
- **Discontinued** — `discontinued` is tiered-trust protected in the Memory Agent exactly like
  `name`/`dose` (`update_medication` treats it as identity, not a casual field). Abort.
- **Still valid** — proceeds to `reorder.propose_reorder`, the same propose-confirm gate a live
  turn would use. Nothing executes from here either; it only gets as far as a confirmable case.

Anti-nag lives in the same function: an unanswered nudge (a `medication_reengagement` case still
in `nudged` state when the next event fires) doesn't repeat identically — its `nudge_count`
increments on the *same* case, and past three unanswered nudges the fourth escalates to a
`trusted_circle`/`caregiver` contact instead of asking the user again. Quiet hours (from the
profile, or a sane default) defer instead of interrupting sleep, and other medications also due
right now get folded into the same message instead of firing their own separate contact.

`POST /reengagement/fire` is the demo hook — it best-effort publishes to Pub/Sub (so the topic is
genuinely visible in the Console) and then runs the same evaluation a real push subscription
would, so the result doesn't depend on a push subscription being wired up for the demo to work.
`POST /reengagement/pubsub-push` is that real push target, decoding Pub/Sub's standard envelope.
`backend/tests/test_reengagement.py` proves the abort with a medication whose `last_confirmed`
moves *after* `scheduled_at` — exactly "change the Rx behind the scenes, then fire the event."

### Perception Agent

`backend/services/perception` implements the one rule that governs the whole medication flow:
vision matches, it never identifies. `POST /perceive` never lets Gemini return a free-standing
drug identity — it hands Gemini Flash the caller's actual known medications (fetched from the
Memory Agent) and asks it to pick among *those*, nothing else. Whatever comes back is
cross-checked against that same list before it's trusted; a `med_id` Gemini invents that isn't on
the user's Life Graph gets silently dropped in `perception.py`, not treated as a match.

The result always lands in one of three branches, matching the trust hierarchy in
`ARCHITECTURE.md` §5b:

- **`confirm_identity`** — exactly one plausible candidate at high confidence (≥ 0.75). Returns
  the matched medication so the caller can read its identity back to the user rather than trusting
  the image itself.
- **`ask_clarifying_question`** — two or more plausible candidates (a look-alike situation).
  Returns every candidate so a follow-up question can distinguish between them — never a guess.
- **`fallback_to_memory`** — nothing legible, nothing on record, or a single candidate that isn't
  confident enough. Falls back to refill timing and a spoken check, not the picture.

`backend/tests/test_perception.py` exercises all three branches plus the case that matters most:
a hallucinated `med_id` outside the user's known set never reaches `confirm_identity`, no matter
how confident Gemini claims to be about it.

### Clarifier / Dialogue Agent

`backend/services/clarifier` owns three kinds of clarifying exchange, and any of them that
resolves a preference hands the Memory Agent the user's own words as provenance:

- **`POST /clarify/medication-question`** — turns Perception's ambiguous candidates into one
  distinguishing question (`templates.py` picks the attribute that actually differs — condition,
  then dose, then falls back to name).
- **`POST /clarify/preference-correction`** — the one-off-vs-durable gate from `ARCHITECTURE.md`
  §5e. `templates.classify_correction_scope` looks for explicit cues ("just this once" vs.
  "always") in the utterance; if neither is there, it returns a question and writes nothing —
  callers resume by passing `is_override` explicitly once the user has answered, which skips
  classification and writes straight through.
- **`POST /clarify/resolution-question`** — phrases the contradiction Memory Agent already
  detected (existing value vs. new value) as one question; `POST
  /clarify/resolution-question/resolve` then carries the user's decision back to Memory Agent's
  own resolve endpoint.

Every question is phrased by Gemini Pro (`gemini_phrasing.py`), adapted to the user's
`pacing_pref`/`literacy_level`/abilities where on file — but asking a question is always the safe
behavior, so a Gemini failure falls back to the plain deterministic template rather than blocking
the question from being asked at all.

### Safety Router

`backend/services/safety_router` runs on every turn and can veto anything in progress. Two
triggers, both checked in `POST /safety/check`: a crisis phrase (`crisis_detection.py`) or
confidence below a threshold. Either one halts and returns a handoff contact — a recorded
`emergency`-role person from the user's own `people` list if there is one; failing that, a
detected mental-health crisis uses `CRISIS_HOTLINE_NUMBER` if it's configured, and everything
else falls back to the national emergency number. `CRISIS_HOTLINE_NUMBER` stays unset by default
on purpose — a wrong crisis number is actively harmful, so this repo doesn't guess one; a real
deployment has to configure a verified, current, local number itself.

Crisis detection is deliberately a fixed phrase list, not a Gemini call. Every other Gemini-backed
piece in this codebase degrades gracefully to a template on failure; this one has to be
guaranteed available even if Vertex AI is unreachable, and a fixed, auditable list makes its
false-negative behavior something you can actually reason about and test — a probabilistic
classifier's failure modes are much harder to pin down for the one gate where missing something
matters most. `health/deep` reflects this: no GCP client checks, because it doesn't have one.

The veto itself needs no cooperation from Action: passing `case_id` moves that case straight out
of `proposed` state, and Action's own confirm-time check (a case has to still be `proposed` to
execute) refuses it from there — one state machine, enforced the same way no matter who's asking.
`test_safety_router.py` proves this isn't just an assertion about Safety Router's own return
value: it proposes a real reorder, vetoes it, and confirms `reorder.resolve_reorder` genuinely
raises rather than executing.

### Live Session Gateway

`backend/services/live_session_gateway` holds the open Gemini Live connection and relays it to
the dashboard over a WebSocket at `/ws/session`. It only perceives and talks — no real-world
action happens here.

The Gemini Live session and the browser's WebSocket are deliberately decoupled
(`live_session.py`): a `SessionState`'s model session and its background pump task keep running
even while no browser is attached. A browser sends `{"session_id": null}` on first connect and
gets one back; sending that same `session_id` on a later reconnect reattaches to the *same*
still-open Gemini session instead of starting a fresh conversation — that's what makes a brief
disconnect survivable. A session with no browser attached for longer than the grace period (60s)
is swept and closed.

The real Gemini connection (`gemini_live.py`) sits behind the same `LiveModelSession` interface
pattern used for the Paystack/pharmacy clients, so `tests/test_live_session_gateway.py` can
verify the reconnection logic — registry attach/detach/grace-period eviction, event buffering
while detached, and the actual `/ws/session` WebSocket route end-to-end — against a fake,
without needing a Vertex AI project.

Wire protocol: browser→gateway audio is raw binary PCM16 frames (everything else, including
video frames, is JSON); gateway→browser is always JSON, with audio and video base64-encoded
inside it. The frontend mirrors this in `frontend/src/session.ts`.

**Frontend** (`frontend/src/`): `media.ts` captures the camera and downsamples mic audio to
16kHz PCM16 via an AudioWorklet (`public/pcm-worklet.js`); `audio-playback.ts` schedules
Lantern's spoken responses back-to-back; `session.ts` is the WebSocket client, reconnecting with
backoff and carrying the `session_id` across reconnects to match the gateway's contract.
`main.ts` wires these into the camera-feed and transcript panels, the first two of the
dashboard's five.

Camera capture, mic capture/playback, and the actual Gemini Live exchange all require a real
device and (for the Gemini side) a configured Vertex AI project — neither is available in this
environment. Everything else about the dashboard, including this pair of panels' layout and
accessibility, is verified with a real headless browser (below).

### The Dashboard

Five panels, all first-class UI: camera, transcript, **proposed action**, **what Lantern
believes about you** (Life Graph), and the **activity log**. The last three call the backend
directly from the browser — Memory Agent for reads, Action Agent for the reorder gate — since no
BFF layer exists yet; `common/cors.py` scopes both services' CORS to exactly `DASHBOARD_ORIGIN`,
not `*`.

- **Life Graph panel** (`panels/life-graph-panel.ts`) renders `GET /life-graph` — medications
  (each with a **Reorder** button), people, a redacted payment summary, and any pending
  resolution event. Choosing **Reorder** is the dashboard's entry point into the confirmation
  gate: it calls `propose_reorder` and hands the result to the Proposed Action panel.
- **Proposed Action panel** (`panels/proposed-action-panel.ts`) is the propose→confirm→execute
  gate made visible. It reads back identity, amount, payee, and card in plain language, and the
  form it shows adapts to `required_confirmation` — a plain **Reorder**/**Not now** pair for
  `simple`, a one-time-code field for `step_up`, an approver-name field for `trusted_circle`.
  Copy stays consistent through the flow the way `ARCHITECTURE.md` asks: **Reorder** →
  **Reordering…** → **Reordered**.
- **Activity log panel** (`panels/audit-panel.ts`) renders `GET /audit`.

Confirming or declining refreshes both the Life Graph and activity log panels, so the acceptance
bar ("visibly update as actions happen") is a real callback (`onSettled` in `main.ts`), not a
manual refresh someone has to remember to click — though a **Refresh** link is there too.

Design: a deliberate "lantern" identity, not the generic AI-app look — a warm dark palette
(`--bg`/`--panel-bg`/`--accent` in `style.css`) instead of cream-serif or acid-on-black. One
signature bold element per the brief: `.brand-mark`, a small glowing orb next to the wordmark
that pulses while the live session is listening and sits dim otherwise — everywhere else stays
quiet by comparison. Accessibility is load-bearing, not a checkbox: `html` sets an 18px base
size, every interactive element gets a 3px high-contrast focus ring via `:focus-visible`, hit
targets run comfortably past the 44px minimum, and the pulse animation only applies inside
`@media (prefers-reduced-motion: no-preference)` — reduced-motion keeps the glow (still says
"listening") but drops the animation. Every raw backend error is caught and replaced with a
specific, calm message in the interface's own voice (`describeFailure` in `api.ts` logs the real
detail to the console instead of showing it) — a fix that came out of actually testing this: the
first pass leaked `"GCP_PROJECT_ID is not set; cannot init the Firestore client"` straight into
the Life Graph panel.

All of this — the five panels rendering, focus-visible outlines, computed font size, hit-target
dimensions, the reduced-motion behavior, and the copy fix above — was checked with a real
headless Chromium session (Playwright) driving the actual dev server against the actual backend,
not just a type-check. What that session can't exercise here: an actual camera/microphone, and a
real Gemini Live connection (no Vertex AI project configured in this environment).

## Stack

| Requirement | Where |
|---|---|
| Gemini 3.5 (Flash + Pro) via Vertex AI | `backend/common/gcp_clients.py:get_genai_client`, used by perception, clarifier, safety_router, live_session_gateway, action |
| Gemini Live API | `services/live_session_gateway/gemini_live.py`, relayed to the dashboard over `/ws/session` |
| Google ADK | `backend/services/orchestrator/adk_agent.py` |
| GenAI SDK | structured output — `services/action/gemini_extraction.py` extracts prescription fields at enrollment, `services/perception/gemini_match.py` returns typed match candidates, `services/clarifier/gemini_phrasing.py` returns a single phrased question |
| Firestore | Life Graph + per-user case state (`services/memory/clients.py:get_firestore_client`, memory-only) |
| Cloud SQL + pgvector | RAG over user documents (`services/memory/clients.py:get_cloud_sql_engine`, memory-only) |
| Cloud Run | every service below, scale-to-zero |
| Pub/Sub | async refill/delivery/re-engagement events (`get_pubsub_publisher`) |

## Local development

Without Docker:

```bash
cp .env.example .env                     # fill in GCP_PROJECT_ID etc. once you have a project
cp frontend/.env.example frontend/.env.local
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
| `NATIONAL_EMERGENCY_NUMBER` | Safety Router's handoff fallback, defaults to Nigeria's 112 |
| `CRISIS_HOTLINE_NUMBER` | mental-health crisis line for Safety Router's handoff — unset by default, must be a verified real number before deploying |
| `DASHBOARD_ORIGIN` | the one origin Memory and Action's CORS allows the browser to call from |
| `ORCHESTRATOR_URL`, `PERCEPTION_URL`, `CLARIFIER_URL`, `ACTION_URL`, `SAFETY_ROUTER_URL`, `MEMORY_URL`, `LIVE_SESSION_GATEWAY_URL` | how services find each other |

The dashboard has its own env file, `frontend/.env.example` — `VITE_LIVE_SESSION_GATEWAY_WS_URL`,
`VITE_MEMORY_URL`, `VITE_ACTION_URL` for where to reach the backend, and `VITE_DEMO_USER_ID` for
which Life Graph user it reads and writes (there's no auth yet, so this stands in for "who's
using the app").

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
