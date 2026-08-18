import { AuditEntry, describeFailure, fetchAudit } from "../api";
import { el } from "../dom";

export class AuditPanel {
  constructor(
    private container: HTMLElement,
    private userId: string,
  ) {}

  async refresh(): Promise<void> {
    try {
      const entries = await fetchAudit(this.userId, 20);
      this.render(entries);
    } catch (error) {
      const message = describeFailure(
        "audit fetch failed",
        error,
        "Lantern can't load the activity log right now. Try refreshing in a moment.",
      );
      this.container.replaceChildren(el("p", { className: "empty-state", text: message }));
    }
  }

  private render(entries: AuditEntry[]): void {
    if (entries.length === 0) {
      this.container.replaceChildren(el("p", { className: "empty-state", text: "Nothing here yet." }));
      return;
    }
    const list = el("ul", { className: "audit-list" });
    for (const entry of entries) {
      list.appendChild(this.renderEntry(entry));
    }
    this.container.replaceChildren(list);
  }

  private renderEntry(entry: AuditEntry): HTMLLIElement {
    const item = el("li", { className: `audit-entry audit-${resultTone(entry.result)}` });
    item.appendChild(el("p", { className: "audit-summary", text: describeEntry(entry) }));
    item.appendChild(el("p", { className: "audit-meta", text: formatTimestamp(entry.ts) }));
    return item;
  }
}

function describeEntry(entry: AuditEntry): string {
  const action = entry.action.replace(/_/g, " ");
  const result = (entry.result ?? "unknown").replace(/_/g, " ");
  return `${capitalize(action)} — ${result}`;
}

function resultTone(result?: string | null): "good" | "warn" | "neutral" {
  if (!result) return "neutral";
  if (result === "success" || result === "proposed") return "good";
  if (result.startsWith("failed") || result.includes("aborted") || result.includes("escalated")) return "warn";
  return "neutral";
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatTimestamp(ts: string): string {
  const parsed = new Date(ts);
  return Number.isNaN(parsed.getTime()) ? ts : parsed.toLocaleString();
}
