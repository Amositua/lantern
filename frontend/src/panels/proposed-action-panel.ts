import {
  ActionResult,
  AppointmentProposal,
  AppointmentResult,
  ConfirmOptions,
  Proposal,
  ReorderProposal,
  ReorderResult,
  confirmAppointmentAction,
  confirmReorder,
  describeFailure,
} from "../api";
import { el } from "../dom";

interface ActionKind {
  confirmVerb: string; // "Reorder", "Confirm"
  confirmingVerb: string; // "Reordering…", "Paying…"
  confirm: (userId: string, caseId: string, confirmed: boolean, options: ConfirmOptions) => Promise<ActionResult>;
  resultLabel: (status: string) => string;
}

const REORDER_KIND: ActionKind = {
  confirmVerb: "Reorder",
  confirmingVerb: "Reordering…",
  confirm: (userId, caseId, confirmed, options) =>
    confirmReorder(userId, caseId, confirmed, options) as Promise<ReorderResult>,
  resultLabel: (status) =>
    ({
      executed: "Reordered",
      declined: "Declined",
      aborted_duplicate: "Already reordered",
      requires_step_up: "Needs a one-time code",
      requires_trusted_circle: "Needs trusted-circle approval",
    })[status] ?? status,
};

const APPOINTMENT_VERBS: Record<AppointmentProposal["intent"], string> = {
  confirm_attendance: "Confirm",
  reschedule: "Reschedule",
  cancel: "Cancel",
};

function appointmentKind(intent: AppointmentProposal["intent"]): ActionKind {
  return {
    confirmVerb: APPOINTMENT_VERBS[intent],
    confirmingVerb: "Sending…",
    confirm: (userId, caseId, confirmed) =>
      confirmAppointmentAction(userId, caseId, confirmed) as Promise<AppointmentResult>,
    resultLabel: (status) => ({ executed: "Done", declined: "Left as is" })[status] ?? status,
  };
}

export class ProposedActionPanel {
  constructor(
    private container: HTMLElement,
    private userId: string,
    private onSettled: () => void,
  ) {
    this.renderIdle();
  }

  renderIdle(): void {
    this.container.replaceChildren(
      el("p", {
        className: "empty-state",
        text: 'Nothing proposed right now. Choose "Reorder" next to a medication, or "Confirm" next to an appointment, to start one.',
      }),
    );
  }

  showReorderProposal(proposal: ReorderProposal): void {
    this.showProposal(proposal, REORDER_KIND);
  }

  showAppointmentProposal(proposal: AppointmentProposal): void {
    this.showProposal(proposal, appointmentKind(proposal.intent));
  }

  private showProposal(proposal: Proposal, kind: ActionKind): void {
    this.container.replaceChildren();

    this.container.appendChild(el("p", { className: "proposal-readback", text: proposal.read_back }));
    this.container.appendChild(el("p", { className: "proposal-note", text: confirmationLevelNote(proposal.required_confirmation) }));

    const form = document.createElement("form");
    form.className = "proposal-actions";
    form.setAttribute("aria-label", `Confirm or decline this ${kind.confirmVerb.toLowerCase()}`);

    let stepUpInput: HTMLInputElement | null = null;
    let approverInput: HTMLInputElement | null = null;

    if (proposal.required_confirmation === "step_up") {
      const label = el("label", { className: "field-label", text: "One-time code" });
      stepUpInput = document.createElement("input");
      stepUpInput.type = "text";
      stepUpInput.required = true;
      stepUpInput.autocomplete = "one-time-code";
      stepUpInput.className = "field-input";
      label.appendChild(stepUpInput);
      form.appendChild(label);
    }

    if (proposal.required_confirmation === "trusted_circle") {
      const label = el("label", { className: "field-label", text: "Approved by" });
      approverInput = document.createElement("input");
      approverInput.type = "text";
      approverInput.required = true;
      approverInput.placeholder = "Name of your trusted contact";
      approverInput.className = "field-input";
      label.appendChild(approverInput);
      form.appendChild(label);
    }

    const confirmButton = el("button", { className: "primary-button", text: kind.confirmVerb });
    confirmButton.type = "submit";

    const declineButton = el("button", { className: "secondary-button", text: "Not now" });
    declineButton.type = "button";

    const statusLine = el("p", { className: "proposal-status" });
    statusLine.setAttribute("aria-live", "polite");

    form.append(confirmButton, declineButton);
    this.container.append(form, statusLine);

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const options: ConfirmOptions = { confirmedBy: approverInput?.value, stepUpToken: stepUpInput?.value };
      void this.submit(proposal, kind, true, options, statusLine, confirmButton, declineButton);
    });

    declineButton.addEventListener("click", () => {
      void this.submit(proposal, kind, false, {}, statusLine, confirmButton, declineButton);
    });
  }

  private async submit(
    proposal: Proposal,
    kind: ActionKind,
    confirmed: boolean,
    options: ConfirmOptions,
    statusLine: HTMLParagraphElement,
    confirmButton: HTMLButtonElement,
    declineButton: HTMLButtonElement,
  ): Promise<void> {
    confirmButton.disabled = true;
    declineButton.disabled = true;
    if (confirmed) confirmButton.textContent = kind.confirmingVerb;
    statusLine.textContent = "";

    try {
      const result = await kind.confirm(this.userId, proposal.case_id, confirmed, options);
      this.showResult(result, proposal, kind);
    } catch (error) {
      statusLine.textContent = describeFailure(
        "confirm action failed",
        error,
        "Lantern couldn't send that just now. Try again in a moment.",
      );
      confirmButton.disabled = false;
      declineButton.disabled = false;
      confirmButton.textContent = kind.confirmVerb;
    } finally {
      this.onSettled();
    }
  }

  private showResult(result: ActionResult, proposal: Proposal, kind: ActionKind): void {
    this.container.replaceChildren();
    this.container.appendChild(el("p", { className: `proposal-result proposal-result-${resultTone(result.status)}`, text: kind.resultLabel(result.status) }));
    this.container.appendChild(el("p", { className: "proposal-detail", text: result.message }));

    if (result.status === "requires_step_up" || result.status === "requires_trusted_circle") {
      const retryButton = el("button", { className: "secondary-button", text: "Try again" });
      retryButton.type = "button";
      retryButton.addEventListener("click", () => this.showProposal(proposal, kind));
      this.container.appendChild(retryButton);
    } else {
      const doneButton = el("button", { className: "secondary-button", text: "Done" });
      doneButton.type = "button";
      doneButton.addEventListener("click", () => this.renderIdle());
      this.container.appendChild(doneButton);
    }
  }
}

function confirmationLevelNote(level: Proposal["required_confirmation"]): string {
  switch (level) {
    case "simple":
      return "A quick yes will confirm this.";
    case "step_up":
      return "This needs a one-time code to confirm.";
    case "trusted_circle":
      return "This needs approval from someone in your trusted circle.";
  }
}

function resultTone(status: string): "good" | "warn" | "neutral" {
  if (status === "executed") return "good";
  if (status === "requires_step_up" || status === "requires_trusted_circle") return "warn";
  return "neutral";
}
