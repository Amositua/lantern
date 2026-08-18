import { ConfirmOptions, ReorderProposal, ReorderResult, confirmReorder, describeFailure } from "../api";
import { el } from "../dom";

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
      el("p", { className: "empty-state", text: 'Nothing proposed right now. Choose "Reorder" next to a medication to start one.' }),
    );
  }

  showProposal(proposal: ReorderProposal): void {
    this.container.replaceChildren();

    this.container.appendChild(el("p", { className: "proposal-readback", text: proposal.read_back }));
    this.container.appendChild(el("p", { className: "proposal-note", text: confirmationLevelNote(proposal.required_confirmation) }));

    const form = document.createElement("form");
    form.className = "proposal-actions";
    form.setAttribute("aria-label", "Confirm or decline this reorder");

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

    const confirmButton = el("button", { className: "primary-button", text: "Reorder" });
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
      void this.submit(proposal, true, options, statusLine, confirmButton, declineButton);
    });

    declineButton.addEventListener("click", () => {
      void this.submit(proposal, false, {}, statusLine, confirmButton, declineButton);
    });
  }

  private async submit(
    proposal: ReorderProposal,
    confirmed: boolean,
    options: ConfirmOptions,
    statusLine: HTMLParagraphElement,
    confirmButton: HTMLButtonElement,
    declineButton: HTMLButtonElement,
  ): Promise<void> {
    confirmButton.disabled = true;
    declineButton.disabled = true;
    if (confirmed) confirmButton.textContent = "Reordering…";
    statusLine.textContent = "";

    try {
      const result = await confirmReorder(this.userId, proposal.case_id, confirmed, options);
      this.showResult(result, proposal);
    } catch (error) {
      statusLine.textContent = describeFailure(
        "confirm reorder failed",
        error,
        "Lantern couldn't send that just now. Try again in a moment.",
      );
      confirmButton.disabled = false;
      declineButton.disabled = false;
      confirmButton.textContent = "Reorder";
    } finally {
      this.onSettled();
    }
  }

  private showResult(result: ReorderResult, proposal: ReorderProposal): void {
    this.container.replaceChildren();
    this.container.appendChild(el("p", { className: `proposal-result proposal-result-${resultTone(result.status)}`, text: resultLabel(result.status) }));
    this.container.appendChild(el("p", { className: "proposal-detail", text: result.message }));

    if (result.status === "requires_step_up" || result.status === "requires_trusted_circle") {
      const retryButton = el("button", { className: "secondary-button", text: "Try again" });
      retryButton.type = "button";
      retryButton.addEventListener("click", () => this.showProposal(proposal));
      this.container.appendChild(retryButton);
    } else {
      const doneButton = el("button", { className: "secondary-button", text: "Done" });
      doneButton.type = "button";
      doneButton.addEventListener("click", () => this.renderIdle());
      this.container.appendChild(doneButton);
    }
  }
}

function confirmationLevelNote(level: ReorderProposal["required_confirmation"]): string {
  switch (level) {
    case "simple":
      return "A quick yes will confirm this.";
    case "step_up":
      return "This needs a one-time code to confirm.";
    case "trusted_circle":
      return "This needs approval from someone in your trusted circle.";
  }
}

function resultLabel(status: ReorderResult["status"]): string {
  switch (status) {
    case "executed":
      return "Reordered";
    case "declined":
      return "Declined";
    case "aborted_duplicate":
      return "Already reordered";
    case "requires_step_up":
      return "Needs a one-time code";
    case "requires_trusted_circle":
      return "Needs trusted-circle approval";
  }
}

function resultTone(status: ReorderResult["status"]): "good" | "warn" | "neutral" {
  if (status === "executed") return "good";
  if (status === "requires_step_up" || status === "requires_trusted_circle") return "warn";
  return "neutral";
}
