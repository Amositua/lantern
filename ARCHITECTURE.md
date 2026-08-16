# Lantern — Architecture & Concept Spec

> **One line:** Lantern is a voice-and-vision agent that *completes real-world tasks* for people the digital world locks out. You point and speak; it doesn't describe what it sees — it **does the thing** — and it knows your life deeply enough to do it safely.

Built for the **All Things Agentic Hackathon — Collaborative Partner track**.

---

## 1. The problem (large scale, real, unsolved-in-this-shape)

Hundreds of millions of people cannot use a smartphone the way it assumes they can: elderly people, people with low vision, people with limited hand mobility, people recovering from stroke, low-literacy and non-native users. For them, everyday digital chores — reordering medication, understanding a hospital letter, filling a form, completing a checkout — are daily walls.

**The market already solved *seeing*. Nobody solved *doing*.**

- Be My AI, Seeing AI, Google Lookout, Apple's 2026 camera reader: all **describe and read**. They are **eyes**.
- None of them **complete the multi-step task**. None are **hands**.

That gap is Lantern's entire moat, and it maps directly onto the hackathon's **40% "autonomous action over simple chat"** criterion. Existing accessibility tools are structurally disqualified from this criterion because they narrate; Lantern acts.

## 2. The moat, stated plainly

> **Existing tools are eyes. Lantern is hands.**

And the thing that makes hands *safe*: a persistent, structured model of the user's life (the **Life Graph**) that no fresh-chat AI and no generic competitor holds. Lantern can act correctly *because it knows this specific person* — their medication and dosage, their pharmacy, their payment method, their doctors, their people, their abilities, and every correction they've ever made.

## 3. The four pillars

1. **Perception** — Point the camera, speak naturally. Gemini Live sees what the user sees and understands it *in the user's context* (not "a pill bottle" but "*your* 10mg amlodipine, refill due in 3 days").
2. **Action** — The differentiator. Executes the whole chore end-to-end: reorder the refill, fill and submit the form, book the appointment, complete the checkout, set the reminder. Multi-step, autonomous, goal-completing.
3. **Memory (the Life Graph)** — Persistent, structured, per-user model of the person's life. RAG-fed into every action so Lantern does the *right* thing for *this* person. Deepens with every interaction. **This is the true moat.**
4. **Adaptation** — Learns *how the user works* (speaks slowly, can't tap small targets, needs one step at a time, confused by jargon) and reshapes every future interaction. This is the Collaborative Partner track's literal core requirement, and it is demonstrable.

## 4. Flagship demo chain: medication / health-admin

Chosen because it is the most visually undeniable and emotionally powerful in a 4-minute unedited demo, and because it *forces* the safety architecture that scores under the 30% criterion.

**The unbroken chain (target demo):**
1. User points phone at a pill bottle and says "I'm running low on this."
2. Lantern recognizes it **against the Life Graph** — "That's your amlodipine, 10mg, blood-pressure. You have about 3 days left."
3. Lantern proposes the action — "I can reorder a month's supply from [your usual pharmacy] for ₦4,500, paid from your usual card. Shall I?"
4. **Confirmation gate** (voice) — user says yes.
5. Lantern places the order through the pharmacy-aggregator + Paystack rail, arranges delivery.
6. Lantern sets the refill reminder and, with consent, notifies the trusted-circle contact ("Mum's BP meds reordered, arriving Tuesday").
7. **Next session**, Lantern remembers and has adapted (e.g. now defaults to the confirmation style the user preferred).

This single chain demonstrates Perception + Action + Memory + Adaptation + Safety in ~90 seconds.

### Legal lane (real, grounds the design)
Nigeria's **Electronic Pharmacy Regulations 2026** (gazetted April 2026) permit online dispensing against a **valid prescription**, require compliance with the **Nigeria Data Protection Act** + NDPC registration, and mandate mechanisms to catch inappropriate/duplicate orders. Therefore Lantern's clean lane is:

- **Refills/reorders of an already-prescribed medication** (the user is already on it) and **OTC items**.
- Lantern **coordinates**, it does **not prescribe**. Navigator, not clinician.
- Real action rails that exist today: **Pharmarun / Famasi / OneHealth / Drugstore.ng** aggregators, **Paystack** for payment (card / transfer / USSD), verified-pharmacy fulfilment + delivery.

Designing against the actual 2026 law is a **production-readiness signal** almost no entry will have.

## 5. Safety architecture (a scoring *strength*, not a disclaimer)

Feature this; don't hide it. Under the **30% Architectural Discipline** criterion this is points on the board.

- **Confirmation gate** before any irreversible/paid/health action: propose → confirm → execute. Never silent auto-execute for high-stakes categories.
- **High-stakes never-auto list**: medication, payments above a threshold, anything medical, anything sending money.
- **Crisis / uncertainty router**: if the user expresses a medical emergency or mental-health crisis, or if Lantern's confidence is low, it **hands off to a human / trusted contact / official hotline** rather than guessing. Lantern is a navigator; it never plays doctor.
- **Duplicate-order guard** (also a legal requirement): checks the Life Graph refill history before reordering.
- **Credential isolation**: payment + personal data handled per §7. Personal data compliant with NDPA framing.
- **Tool-failure handling**: every external tool call (pharmacy API, Paystack, calendar) is traced; failures surface to the user in plain language and never corrupt Life Graph state (addresses the well-known "agent improvises around a broken tool response" failure mode).

## 5b. Medication recognition & the Trust Hierarchy (safety-critical)

This is the single most dangerous point in the system. If Lantern misreads a drug or dose and reorders the wrong thing, that is potential harm, not a bug. The design below is non-negotiable.

### Why naive vision recognition is unsafe in the real Nigerian context
- **Meds often aren't in labeled manufacturer packaging.** Loose tablets are extremely common (e.g. ~91% of outlets dispense loose rifampicin); for solid forms not in blister packs, most dispensing envelopes don't even carry the drug name. The camera frequently has *nothing trustworthy to read*.
- **Labeling errors and missing info are documented and common** — even when a label exists it may be wrong or incomplete.
- **Counterfeit/substandard meds mean the printed label can lie** — Nigeria has a documented falsified-medicine problem.
- **Look-alike drugs** — many tablets are white, round, unmarked; two different drugs can look identical. Vision cannot distinguish them.
- **Base-model failure mode:** the biggest agent risk isn't hallucination, it's *overconfidence* — the model returns a confident "amlodipine 10mg" from a blurry envelope and commits.

**Conclusion: vision can NEVER be the source of truth for what the drug is.**

### The inversion: vision *matches*, it never *identifies*
Lantern already holds a source of truth vision doesn't — the **Life Graph**. The user is on a *known* set of medications that entered through a trusted path. So the camera's question is not "what is this drug?" but **"does what I'm seeing match one of the medications I already know this person takes, and how confident am I?"** — a constrained match against a small known set, which degrades safely: weak match → Lantern asks, it never guesses.

### Trust hierarchy (strict priority; vision is weakest)
1. **Prescription of record** (highest) — actual Rx captured at enrollment, verified with practitioner details per the 2026 regs. Ground truth.
2. **Pharmacy dispensing record** — what the verified pharmacy dispensed against that Rx.
3. **Life Graph entry** — the structured medication derived from 1 & 2.
4. **Prior confirmed refills** — history of this exact reorder being confirmed and delivered.
5. **Vision match** (lowest) — a *hint* to route to the right Life Graph entry and a *safety cross-check*, never an identifier on its own.

### Reorder flow (safe)
```
User points camera + "I'm running low on this"
        │
        ▼
Perception Agent → { candidate_match: medId?, confidence: 0.0–1.0, features_read: [...] }
        │
        ▼
Match against Life Graph (the KNOWN med set for THIS user)
   ┌────┴───────────────────────┬─────────────────────────────┐
   ▼                            ▼                             ▼
HIGH conf + single match    AMBIGUOUS (2+ plausible /     NO match / low conf /
   │                        look-alike)                   nothing readable
   ▼                            ▼                             ▼
Confirm by IDENTITY,        Clarifier asks the            Fall back to MEMORY, not vision:
not image:                  distinguishing question:      "I can't read it clearly. You're
"That's your amlodipine,    "The one you take each        due for your amlodipine around
 10mg, blood-pressure —      morning for blood             now — is that the one?"
 reorder a month? ₦4,500."   pressure, or the water        (verify via spoken details +
   │                         tablet?"                       refill timing, never the picture)
   ▼                            └───────────┬───────────────────┘
Voice confirmation gate                     ▼
   │                            Proceeds only once identity is
   ▼                            established by something the
Duplicate-order guard          USER confirms in words
(last_refill vs cadence)
   │
   ▼
Execute via aggregator + Paystack → write audit log
```

### Key safety properties
- **Confirms drugs by *identity read back to the user*, never by trusting the image.** The user, who knows their own meds, confirms; vision only *routed* to the entry.
- **Ambiguity → clarifying question, not a guess.** The safety mechanism and the Collaborative-Partner track-fit are the *same* mechanism.
- **No readable label is fine** — falls back to refill timing + spoken confirmation, because the source of truth was never the label. Handles the loose-tablet / blank-envelope reality that breaks naive competitors.
- **Duplicate-order guard** via `last_refill` + `cadence` (also a 2026 legal requirement).
- **Confidence surfaced, not hidden** — low confidence means *more* confirmation, never silent action.

### Enrollment: where truth enters the system
A med enters the Life Graph through a **trusted onboarding path**, not by waving a camera at a bottle:
- Capture the actual **prescription** (photo → Gemini Pro structured extraction → human/pharmacist-verified for the first entry), **or**
- Import from the **pharmacy dispensing record** on the aggregator, **or**
- A **trusted-circle member** sets it up and confirms it.

Once a med is in the Life Graph *with verified identity*, day-to-day reordering is safe match-and-confirm against that trusted entry. **The demo must show this enrollment-with-verification step** so the trust chain is complete on camera — otherwise "how do you know that's really amlodipine?" has no answer.

---

## 5c. Payment authorization & the spend gate (safety-critical)

Payment is dangerous differently from medication: the risk isn't misreading, it's **moving real money by voice for someone who may be vulnerable to error, confusion, or coercion.**

### Threat model
1. **Accidental/mistaken spend** — ambiguous phrasing or misinterpretation moves money; a low-vision/elderly user can't easily verify what happened.
2. **Runaway/duplicate spend** — agent loops or retries on an ambiguous tool response (the classic "improvise around a broken tool response") and double-charges.
3. **Coercion / third-party abuse** — someone beside the user, or a stolen device, drives a payment.

### Paystack primitives used deliberately
- **Card is tokenized, not stored** — after the first successful payment Paystack returns an `authorization_code` (a token for the card); subsequent charges hit `charge_authorization` against that token. Life Graph stores only `payment: { method_ref = authorization_code }`. No raw card data — credential isolation is real.
- **First transaction legally requires 2FA** (OTP/PIN/3DS) before any card can be charged later — so payment enrollment has bank-grade auth built in, mirroring medication enrollment.
- **Every subsequent charge is Lantern-initiated**, so Lantern also owns the gate in front of each charge.
- **Challenged charges** return an `authorization_url` — reusable mid-flow as a step-up challenge.

### The spend gate (layered defense)
1. **Propose → confirm → execute, always.** No charge without reading back the full transaction (amount, payee, reason, card) and getting affirmative confirmation. For this population the read-back is simultaneously the accessibility feature and the safety feature.
2. **Confirmation strength scales with amount/risk.** Cheap known recurring refill → simple "yes." Larger amount, new payee, or unusual pattern → **step-up auth** via Paystack's OTP/PIN challenge (`authorization_url`). High-risk spend then requires the bank's own OTP — something a coercer or a confused moment can't easily produce.
3. **Hard limits + never-auto list** (Life Graph): per-transaction cap, daily cap, category never-auto list. Above cap → mandatory step-up or trusted-circle approval. Bounds worst-case blast radius.
4. **Idempotency on every charge.** Client-generated idempotency key tied to the case/order. Ambiguous timeout → **verify before retry** (Paystack verify-transaction), never blind re-charge. Kills the double-charge failure mode.
5. **Trusted-circle escalation.** Above a higher threshold or on anomaly, route approval to a designated contact ("Your daughter needs to approve this ₦40,000 payment") instead of executing on voice alone.
6. **Full audit + plain-language receipt.** Every payment writes `audit` (proposed → confirmed_by → method → result → idempotency_key) and is spoken back to the user (and optionally the trusted circle). Nothing moves money silently.

### The coercion caveat (claim this honestly)
Layers 1–6 **mitigate but do not fully solve** coercion — if someone holds the device and can produce the OTP, they can spend. No consumer payment system fully solves this; Lantern shouldn't pretend to. Honest claim: spend is **bounded (caps), challenged (step-up auth), escalated (trusted circle), and fully auditable** — the same posture as real banking apps. Do **not** claim "coercion-proof"; the calibrated claim is the credible one.

---

## 5d. Async re-engagement loop (correctness & trust)

Proactive re-contact (Pub/Sub-driven "your refill is due") is the highest-value feature for this population *and* the easiest to get wrong. Failure modes: **nagging** (trains the user to ignore Lantern — fatal), **acting on stale state** (an event scheduled 25 days ago fires today, but the Rx changed / user already reordered / med discontinued), **wrong moment/channel** (3am, or a modality the user can't perceive).

### Core principle: the event is a trigger to RE-EVALUATE, never a command to ACT
A Pub/Sub message carries *"re-assess whether a refill is needed,"* not *"reorder amlodipine."* At fire time Lantern re-reads **current** Life Graph state and re-derives whether the action still holds:
- Rx changed since scheduling? → abort.
- Already reordered manually (`last_refill`)? → abort (no duplicate).
- Med discontinued? → abort.
- Still valid? → proceed **only to the propose-confirm gate**, never silent execution.

Stale state cannot drive an action because the decision is made at fire time from fresh data, not baked into the message at schedule time. **Event-carried-state is the anti-pattern; event-triggered-re-evaluation is the discipline.**

### Anti-nag controls
- **Escalating backoff, not repetition** — an unanswered nudge escalates *later and differently*, never the same ping again. If genuinely urgent and repeatedly unanswered → escalate to the **trusted circle** (loop in a human) rather than continuing to nag a vulnerable person.
- **Quiet hours + channel-awareness** from the profile — never during sleep hours; only in a modality the user can perceive.
- **Consolidation** — multiple due items batched into one contact.
- **Learned frequency** — if the user reliably handles a refill early themselves, dial back proactive contact for it (adaptation applied to re-engagement itself).

### Demo note
Async is hard to show live (it happens over days). Demo with a **triggered/time-compressed simulation**: fire the event on demand, and show Lantern **correctly aborting a stale reorder** because the Rx was changed behind the scenes. The abort is a *stronger* judge moment than a successful reorder — it proves the safety design is real.

## 5e. Life Graph correctness over time (correctness & trust)

The moat is that Lantern learns you; the failure is that it learns you *wrong* and then acts on it confidently and silently. Failure modes: a **one-off learned as a standing rule** ("smaller pack just this once" → every refill wrong); a **misheard/misparsed correction** poisoning the graph (live risk for African-accented STT); **contradictory corrections** with naive last-write-wins; **stale facts** that were once true (old pharmacy/address).

### Every learned fact carries provenance + confidence; nothing silently hardens into truth
A preference node is `{ value, source_utterance, confidence, observation_count, last_confirmed, is_override }` — metadata that lets Lantern reason about its own memory instead of blindly trusting it.

- **One-off vs. durable is decided explicitly, not assumed.** When a correction could be either, ask at capture time: *"Just this once, or always from now on?"* One-offs are written as `is_override: true` on the transaction, never as a standing preference. Single highest-leverage safeguard.
- **Preferences earn confidence through repetition.** A first-time correction is provisional (low confidence) — *applied but flagged*, so Lantern still confirms it ("that's what you asked last time — still right?") until observed enough to harden. A single mishear can't silently become permanent truth.
- **Tiered write-trust: the more dangerous the field, the more verification to change it.** Changing a **dose or drug** re-enters the trusted-enrollment path (verify vs Rx / pharmacist / trusted circle) — never a casual voice write. Low-stakes prefs (pack size, delivery time) can be learned lightly. What-drug-at-what-dose can never be changed by an unverified voice turn.
- **User-inspectable memory.** The user or trusted circle can hear "here's what I believe about your meds and preferences" and correct it. Auditable memory is both a trust feature and a correctness safeguard (wrong facts surface because someone can review them), and satisfies NDPA-style data-access expectations.
- **Freshness where it matters.** Stale-prone fields (pharmacy, address, payment, active-med list) carry `last_confirmed` and get *periodic* gentle re-verification, not eternal trust.
- **Contradiction → resolution question, not silent overwrite.** New correction conflicting with an established high-confidence preference is surfaced for the user to resolve. Last-write-wins is banned for high-confidence fields.

---

## 6. Multi-agent architecture (Google ADK)

ADK orchestrates a small team of specialised agents. Keep the topology legible — judges reward clear decoupling.

```
                         ┌─────────────────────────┐
        voice + video →  │   Live Session Gateway   │  (Cloud Run, holds Gemini Live socket)
                         └───────────┬─────────────┘
                                     │
                         ┌───────────▼─────────────┐
                         │   Orchestrator (ADK)     │  routes intent, sequences agents
                         └─┬───────┬────────┬──────┬┘
             ┌─────────────┘       │        │      └────────────┐
   ┌─────────▼────────┐ ┌──────────▼──┐ ┌───▼─────────┐ ┌──────▼────────┐
   │ Perception Agent │ │ Clarifier / │ │ Action /    │ │ Safety Router │
   │ (Gemini Live +   │ │ Dialogue    │ │ Executor    │ │ (crisis /     │
   │  Flash vision)   │ │ Agent       │ │ Agent       │ │  confidence)  │
   └────────┬─────────┘ └──────┬──────┘ └──────┬──────┘ └──────┬────────┘
            │                  │               │               │
            └──────────────────┴───────┬───────┴───────────────┘
                                       │
                         ┌─────────────▼──────────────┐
                         │  Memory Agent (Life Graph)  │  read/write personal model
                         └─────────────┬──────────────┘
                                       │
                 ┌─────────────────────┼─────────────────────┐
        ┌────────▼────────┐   ┌────────▼────────┐   ┌─────────▼─────────┐
        │  Firestore      │   │ Cloud SQL +     │   │  Pub/Sub          │
        │ (Life Graph,    │   │ pgvector (RAG   │   │ (async follow-up: │
        │  case state)    │   │ over user docs) │   │  refills, tracking│
        └─────────────────┘   └─────────────────┘   │  deliveries)      │
                                                     └───────────────────┘
```

**Agent roles**
- **Perception Agent** — Gemini Live for real-time voice+video; Gemini Flash for discrete visual detection (recognise the pill bottle / read the label). Mirrors the Drone Co-Pilot pattern (Live API session + Flash for targeted vision).
- **Clarifier / Dialogue Agent** — leads the conversation, asks clarifying questions, guides step-by-step, adapts pacing/format to the user. The Collaborative Partner heart.
- **Action / Executor Agent** — calls external tools (pharmacy aggregator, Paystack, calendar, forms). Owns the confirmation-gate protocol.
- **Safety Router** — evaluates every turn for crisis/low-confidence; can halt the pipeline and hand off.
- **Memory Agent** — the only writer to the Life Graph; enforces the schema, dedup, and consent rules.
- **Orchestrator (ADK)** — sequences the above; manages state across the multi-turn, multi-session interaction.

## 7. Tech stack (required-stack mapping — every box ticked)

| Requirement | Where it lives in Lantern |
|---|---|
| **Gemini 3.5 via Vertex AI** | Flash → real-time vision + voice streaming + label recognition; Pro → harder reasoning (interpret a medical letter, plan a multi-step task, resolve ambiguity) |
| **Gemini Live API** | The real-time voice+video loop (Perception Agent) — the Drone Co-Pilot architecture |
| **Google ADK** | Multi-agent orchestration topology above |
| **GenAI SDK** | Structured output for Life-Graph nodes, action plans, confirmation payloads |
| **Firestore** | Persistent Life Graph + per-user case state across sessions (the load-bearing memory) |
| **Cloud SQL + pgvector** | RAG over the user's own documents (prescriptions, letters, labels) |
| **Cloud Run** | Scale-to-zero services: Live Session Gateway + each stateless agent service |
| **Pub/Sub** | Async backbone: refill-due events, delivery tracking, follow-up re-engagement |

**Bonus surfaces** (explicitly rewarded by the hackathon): accessibility framing → strong **Best Multimodal UX** contender from the same build; optional short Veo verdict/briefing clip; build blog + hashtag.

## 8. Life Graph — schema sketch (Firestore)

```
users/{userId}
  profile:        { name, language, literacy_level, abilities: {...}, pacing_pref }
  medications/{medId}:  { name, dose, condition, pharmacy_ref, last_refill, cadence, rx_ref }
  people/{personId}:    { name, relation, roles: [emergency, groceries, ...], contact }
  payment:        { method_ref (tokenised), threshold_auto_confirm }
  documents/{docId}:    { type, uri, extracted_fields, vector_ref → Cloud SQL }
  preferences/{prefId}: { domain, learned_value, source_correction, updated_at }
  cases/{caseId}:       { task, state, steps[], pending_async_ref, created_at }
  audit/{eventId}:      { action, proposed, confirmed_by, result, ts }   ← every action logged
```

- **Memory Agent** is the sole writer. Every correction becomes a `preferences` node → adaptation.
- **No raw payment credentials stored** — tokenised references only (§ credential isolation).
- `audit` gives the demo a visible, judge-friendly trail and satisfies the "handle failures / traceability" ask.

## 9. How Lantern scores against the judging criteria

- **Innovation & Operational Utility (40%)** — removes concrete, autonomous, multi-step friction for the largest digitally-excluded population; *completes tasks* where every competitor only describes; sidesteps the crowded/unsafe "AI therapist" and "seeing-aid" lanes.
- **Architectural Discipline & Tech Stack (30%)** — clean multi-agent decoupling (ADK), durable cross-session memory (Firestore), RAG (Cloud SQL/pgvector), async workflows (Pub/Sub), credential isolation, explicit failure handling, and a safety-router designed against real 2026 e-pharmacy law.
- **Demo & Production Readiness (30%)** — one flawless unbroken chain, live and unedited; clean architecture diagram (above); reproducible single-script deploy; Cloud Console visible during the demo to prove it runs on Google Cloud.

## 10. Build discipline (protect the wedge)

- **Expansive vision in the pitch, surgical focus in the build.** Ship ONE flagship chain (medication/health-admin) end-to-end and flawless. Everything else (trusted circle, proactive refills, forms, groceries, language/literacy) is *roadmap*, shown as slides, not half-built.
- The moment Lantern becomes a do-everything assistant, it loses the sharp "it acts, they only describe" story that wins the 40%. Stay narrow.
- Privacy/credential story must be real from day one — it's a 30% win if done well, a fatal flaw if careless.

## 11. Roadmap (pitch as platform, don't build yet)

- **Trusted-circle layer** — family/caregiver visibility ("Mum's meds refilled, appt booked"). Huge for the caregiver population.
- **Proactive action** — Lantern notices a refill is due and surfaces it before the user runs out (Pub/Sub scheduled events).
- **Language & literacy adaptation** — operate in the user's language and reading level; folds in the low-literacy/non-native population for free.
- **More task chains** — bureaucracy/forms, groceries/daily living, bills/money — same engine, same Life Graph.
