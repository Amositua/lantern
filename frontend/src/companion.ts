import "./style.css";
import { Case, confirmReorder, describeFailure, fetchCases } from "./api";
import { el } from "./dom";

const USER_ID = (import.meta.env.VITE_DEMO_USER_ID as string | undefined) ?? "demo-user";

interface PendingItem {
  case_id: string;
  summary: string;
}

const app = document.querySelector<HTMLDivElement>("#app");

if (app) {
  app.innerHTML = `
    <div class="app-shell">
      <header class="app-header">
        <div class="brand">
          <span class="brand-mark" aria-hidden="true"></span>
          <div class="brand-text">
            <h1>Lantern — Trusted Circle</h1>
            <p class="lede">Some things Amara asked you to approve, or that went unanswered long enough to loop you in.</p>
          </div>
        </div>
      </header>

      <main class="dashboard companion-dashboard">
        <section aria-label="Your name" class="panel">
          <h2>Your name</h2>
          <p class="lede">This has to match how you're recorded in Amara's trusted circle -- Lantern checks it before approving anything.</p>
          <input id="approver-name" class="field-input" type="text" placeholder="e.g. Aunty Bisi" value="Aunty Bisi" />
        </section>

        <section aria-label="Needs your approval" class="panel">
          <div class="panel-heading-row">
            <h2>Needs your approval</h2>
            <button id="refresh" class="link-button" type="button">Refresh</button>
          </div>
          <div id="pending-body"><p class="empty-state">Loading…</p></div>
        </section>
      </main>
    </div>
  `;

  wireUp();
}

function wireUp(): void {
  const nameInput = document.querySelector<HTMLInputElement>("#approver-name")!;
  const refreshButton = document.querySelector<HTMLButtonElement>("#refresh")!;
  const body = document.querySelector<HTMLDivElement>("#pending-body")!;

  const refresh = async (): Promise<void> => {
    body.replaceChildren(el("p", { className: "empty-state", text: "Loading…" }));
    try {
      const cases = await fetchCases(USER_ID);
      render(cases, nameInput, body, refresh);
    } catch (error) {
      const message = describeFailure(
        "companion cases fetch failed",
        error,
        "Lantern can't check right now. Try refreshing in a moment.",
      );
      body.replaceChildren(el("p", { className: "empty-state", text: message }));
    }
  };

  refreshButton.addEventListener("click", () => void refresh());
  void refresh();
}

function render(cases: Case[], nameInput: HTMLInputElement, body: HTMLDivElement, refresh: () => Promise<void>): void {
  const pending = pendingItems(cases);

  if (pending.length === 0) {
    body.replaceChildren(el("p", { className: "empty-state", text: "Nothing needs your approval right now." }));
    return;
  }

  const list = el("ul", { className: "medication-list" });
  for (const item of pending) {
    const line = el("li", { className: "medication-item companion-item" });
    line.appendChild(el("span", { className: "medication-label", text: item.summary }));

    const actions = el("div", { className: "companion-actions" });
    const approveButton = el("button", { className: "primary-button", text: "Approve" });
    approveButton.type = "button";
    const declineButton = el("button", { className: "secondary-button", text: "Decline" });
    declineButton.type = "button";
    const statusLine = el("p", { className: "proposal-status" });
    statusLine.setAttribute("aria-live", "polite");

    const respond = async (confirmed: boolean): Promise<void> => {
      approveButton.disabled = true;
      declineButton.disabled = true;
      statusLine.textContent = "";
      try {
        const confirmedBy = nameInput.value.trim() || "Trusted circle";
        const result = await confirmReorder(USER_ID, item.case_id, confirmed, { confirmedBy });
        statusLine.textContent = result.message;
        if (result.status === "executed" || result.status === "declined") {
          await refresh();
        } else {
          approveButton.disabled = false;
          declineButton.disabled = false;
        }
      } catch (error) {
        statusLine.textContent = describeFailure("companion confirm failed", error, "Lantern couldn't send that. Try again.");
        approveButton.disabled = false;
        declineButton.disabled = false;
      }
    };

    approveButton.addEventListener("click", () => void respond(true));
    declineButton.addEventListener("click", () => void respond(false));
    actions.append(approveButton, declineButton);
    line.append(actions, statusLine);
    list.appendChild(line);
  }
  body.replaceChildren(list);
}

function pendingItems(cases: Case[]): PendingItem[] {
  const items: PendingItem[] = [];

  for (const c of cases) {
    if (c.task === "medication_reorder" && c.state === "proposed" && c.data.required_confirmation === "trusted_circle") {
      items.push({ case_id: c.id, summary: summarize(c) });
    }
  }

  // an escalated re-engagement nudge points at the reorder case it last
  // proposed -- that's what actually needs approving, not the nudge itself
  for (const c of cases) {
    if (c.task === "medication_reengagement" && c.state === "escalated_to_trusted_circle") {
      const reorderCaseId = c.data.reorder_case_id as string | undefined;
      if (reorderCaseId && !items.some((item) => item.case_id === reorderCaseId)) {
        items.push({
          case_id: reorderCaseId,
          summary: "A refill reminder went unanswered a few times and was escalated to you.",
        });
      }
    }
  }

  return items;
}

function summarize(c: Case): string {
  const amountKobo = c.data.amount_kobo as number | undefined;
  const amount = amountKobo != null ? `₦${(amountKobo / 100).toLocaleString()}` : "an amount";
  return `Medication reorder from ${String(c.data.pharmacy_ref ?? "the pharmacy")} -- ${amount}.`;
}
