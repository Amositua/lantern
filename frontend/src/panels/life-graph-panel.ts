import { Appointment, Bill, LifeGraphSummary, Medication, Person, describeFailure, fetchLifeGraph } from "../api";
import { el } from "../dom";

export class LifeGraphPanel {
  constructor(
    private container: HTMLElement,
    private userId: string,
    private onRequestReorder: (medication: Medication) => void,
    private onRequestBillPay: (bill: Bill) => void,
    private onRequestAppointmentConfirm: (appointment: Appointment) => void,
  ) {}

  async refresh(): Promise<void> {
    try {
      const data = await fetchLifeGraph(this.userId);
      this.render(data);
    } catch (error) {
      const message = describeFailure(
        "life graph fetch failed",
        error,
        "Lantern can't check your information right now. Try refreshing in a moment.",
      );
      this.container.replaceChildren(el("p", { className: "empty-state", text: message }));
    }
  }

  private render(data: LifeGraphSummary): void {
    this.container.replaceChildren();

    if (data.pending_resolution_events.length > 0) {
      this.container.appendChild(this.renderResolutionEvents(data.pending_resolution_events));
    }

    this.container.appendChild(this.renderMedications(data.medications));
    this.container.appendChild(this.renderBills(data.bills));
    this.container.appendChild(this.renderAppointments(data.appointments));
    this.container.appendChild(this.renderPeople(data.people));
    this.container.appendChild(this.renderPayment(data.payment));
  }

  private renderMedications(medications: Medication[]): HTMLElement {
    const section = el("div", { className: "life-graph-section" });
    section.appendChild(el("h3", { text: "Medications" }));

    if (medications.length === 0) {
      section.appendChild(el("p", { className: "empty-state", text: "None on file yet." }));
      return section;
    }

    const list = el("ul", { className: "medication-list" });
    for (const med of medications) {
      const item = el("li", { className: "medication-item" });
      const label = med.condition ? `${med.name}, ${med.dose} — ${med.condition}` : `${med.name}, ${med.dose}`;
      item.appendChild(
        el("span", { className: "medication-label", text: med.discontinued ? `${label} (discontinued)` : label }),
      );

      if (!med.discontinued) {
        const button = el("button", { className: "reorder-button", text: "Reorder" });
        button.type = "button";
        button.addEventListener("click", () => this.onRequestReorder(med));
        item.appendChild(button);
      }

      list.appendChild(item);
    }
    section.appendChild(list);
    return section;
  }

  private renderBills(bills: Bill[]): HTMLElement {
    const section = el("div", { className: "life-graph-section" });
    section.appendChild(el("h3", { text: "Bills" }));

    if (bills.length === 0) {
      section.appendChild(el("p", { className: "empty-state", text: "None on file yet." }));
      return section;
    }

    const list = el("ul", { className: "medication-list" });
    for (const bill of bills) {
      const item = el("li", { className: "medication-item" });
      const label = `${bill.provider}, ${bill.category} — account ${bill.account_ref}`;
      item.appendChild(
        el("span", { className: "medication-label", text: bill.discontinued ? `${label} (discontinued)` : label }),
      );

      if (!bill.discontinued) {
        const button = el("button", { className: "reorder-button", text: "Pay" });
        button.type = "button";
        button.addEventListener("click", () => this.onRequestBillPay(bill));
        item.appendChild(button);
      }

      list.appendChild(item);
    }
    section.appendChild(list);
    return section;
  }

  private renderAppointments(appointments: Appointment[]): HTMLElement {
    const section = el("div", { className: "life-graph-section" });
    section.appendChild(el("h3", { text: "Appointments" }));

    if (appointments.length === 0) {
      section.appendChild(el("p", { className: "empty-state", text: "None on file yet." }));
      return section;
    }

    const list = el("ul", { className: "medication-list" });
    for (const appointment of appointments) {
      const item = el("li", { className: "medication-item" });
      const when = appointment.scheduled_for ? `, ${appointment.scheduled_for}` : "";
      const label = `${appointment.provider}${when} — ${appointment.status}`;
      item.appendChild(el("span", { className: "medication-label", text: label }));

      if (!appointment.cancelled && appointment.status === "scheduled") {
        const button = el("button", { className: "reorder-button", text: "Confirm" });
        button.type = "button";
        button.addEventListener("click", () => this.onRequestAppointmentConfirm(appointment));
        item.appendChild(button);
      }

      list.appendChild(item);
    }
    section.appendChild(list);
    return section;
  }

  private renderPeople(people: Person[]): HTMLElement {
    const section = el("div", { className: "life-graph-section" });
    section.appendChild(el("h3", { text: "People" }));
    if (people.length === 0) {
      section.appendChild(el("p", { className: "empty-state", text: "None on file yet." }));
      return section;
    }
    const list = el("ul", { className: "people-list" });
    for (const person of people) {
      const label = person.relation ? `${person.name} (${person.relation})` : person.name;
      list.appendChild(el("li", { text: label }));
    }
    section.appendChild(list);
    return section;
  }

  private renderPayment(payment: LifeGraphSummary["payment"]): HTMLElement {
    const section = el("div", { className: "life-graph-section" });
    section.appendChild(el("h3", { text: "Payment" }));
    if (!payment || !payment.method_ref_present) {
      section.appendChild(el("p", { className: "empty-state", text: "No card on file yet." }));
      return section;
    }
    const cap = payment.per_transaction_cap != null ? `₦${payment.per_transaction_cap.toLocaleString()} per order` : "no cap set";
    section.appendChild(el("p", { text: `Card on file. Limit: ${cap}.` }));
    return section;
  }

  private renderResolutionEvents(events: LifeGraphSummary["pending_resolution_events"]): HTMLElement {
    const section = el("div", { className: "life-graph-section life-graph-alert" });
    section.appendChild(el("h3", { text: "Needs your answer" }));
    const list = el("ul");
    for (const event of events) {
      list.appendChild(el("li", { text: `${event.domain}: ${String(event.existing_value)} or ${String(event.new_value)}?` }));
    }
    section.appendChild(list);
    return section;
  }
}
