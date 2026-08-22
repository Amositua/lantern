const MEMORY_URL = (import.meta.env.VITE_MEMORY_URL as string | undefined) ?? "http://localhost:8085";
const ACTION_URL = (import.meta.env.VITE_ACTION_URL as string | undefined) ?? "http://localhost:8083";

export interface Medication {
  id: string;
  name: string;
  dose: string;
  condition?: string | null;
  pharmacy_ref?: string | null;
  cadence?: number | null;
  last_refill?: string | null;
  discontinued?: boolean;
}

export interface Person {
  id: string;
  name: string;
  relation?: string | null;
  roles: string[];
  contact?: string | null;
}

export interface PaymentSummary {
  method_ref_present: boolean;
  per_transaction_cap?: number | null;
  daily_cap?: number | null;
  never_auto_categories: string[];
  last_confirmed?: string | null;
}

export interface Appointment {
  id: string;
  provider: string;
  purpose?: string | null;
  scheduled_for?: string | null;
  location?: string | null;
  status: string;
  cancelled?: boolean;
}

export interface Preference {
  id: string;
  domain: string;
  value: unknown;
  confidence: number;
  observation_count: number;
  hardened?: boolean;
  is_override?: boolean;
}

export interface ResolutionEvent {
  id: string;
  domain: string;
  existing_value: unknown;
  new_value: unknown;
  status: string;
}

export interface AuditEntry {
  id: string;
  action: string;
  proposed: Record<string, unknown>;
  confirmed_by?: string | null;
  method?: string | null;
  result?: string | null;
  idempotency_key?: string | null;
  ts: string;
}

export interface LifeGraphSummary {
  profile: {
    name?: string | null;
    language?: string | null;
    literacy_level?: string | null;
    pacing_pref?: string | null;
  };
  medications: Medication[];
  appointments: Appointment[];
  people: Person[];
  payment: PaymentSummary | null;
  preferences: Preference[];
  pending_resolution_events: ResolutionEvent[];
  recent_audit: AuditEntry[];
}

export interface ReorderProposal {
  case_id: string;
  med_id: string;
  medication_name: string;
  medication_dose: string;
  pharmacy_ref: string;
  amount_kobo: number;
  payee: string;
  card_description: string;
  required_confirmation: "simple" | "step_up" | "trusted_circle";
  idempotency_key: string;
  read_back: string;
}

export interface ReorderResult {
  status: "executed" | "declined" | "aborted_duplicate" | "requires_step_up" | "requires_trusted_circle";
  message: string;
  order_id?: string | null;
  charge_reference?: string | null;
}

export interface AppointmentProposal {
  case_id: string;
  appointment_id: string;
  provider: string;
  intent: "confirm_attendance" | "reschedule" | "cancel";
  read_back: string;
  required_confirmation: "simple";
}

export interface AppointmentResult {
  status: "executed" | "declined";
  message: string;
  confirmation_ref?: string | null;
}

/** The shape the Proposed Action panel actually needs -- both a
 * ReorderProposal and an AppointmentProposal already satisfy this, so the
 * panel doesn't need to know which domain it's confirming. */
export interface Proposal {
  case_id: string;
  required_confirmation: "simple" | "step_up" | "trusted_circle";
  read_back: string;
}

export interface ActionResult {
  status: string;
  message: string;
}

export interface Case {
  id: string;
  task: string;
  state: string;
  data: Record<string, unknown>;
}

export class ApiError extends Error {}

/** Logs the real (developer-facing) error and returns a calm, specific
 * message in Lantern's own voice -- a raw exception string is never
 * something to show someone using the app. */
export function describeFailure(context: string, error: unknown, friendly: string): string {
  // eslint-disable-next-line no-console
  console.error(`[lantern] ${context}:`, error);
  return friendly;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("Lantern couldn't reach the server. Check your connection and try again.");
  }

  if (!response.ok) {
    let detail = `Something went wrong (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // keep the generic message
    }
    throw new ApiError(detail);
  }

  return response.json() as Promise<T>;
}

export function fetchLifeGraph(userId: string): Promise<LifeGraphSummary> {
  return request(`${MEMORY_URL}/users/${userId}/life-graph`);
}

export function fetchAudit(userId: string, limit = 20): Promise<AuditEntry[]> {
  return request(`${MEMORY_URL}/users/${userId}/audit?limit=${limit}`);
}

export function fetchCases(userId: string): Promise<Case[]> {
  return request(`${MEMORY_URL}/users/${userId}/cases`);
}

export function proposeReorder(userId: string, medId: string): Promise<ReorderProposal> {
  return request(`${ACTION_URL}/reorder/propose`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, med_id: medId }),
  });
}

export interface ConfirmOptions {
  confirmedBy?: string;
  stepUpToken?: string;
}

export function confirmReorder(
  userId: string,
  caseId: string,
  confirmed: boolean,
  options: ConfirmOptions = {},
): Promise<ReorderResult> {
  return request(`${ACTION_URL}/reorder/confirm`, {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      case_id: caseId,
      confirmed,
      confirmed_by: options.confirmedBy ?? "user",
      step_up_token: options.stepUpToken,
    }),
  });
}

export function proposeAppointmentAction(
  userId: string,
  appointmentId: string,
  intent: "confirm_attendance" | "reschedule" | "cancel",
  newTime?: string,
): Promise<AppointmentProposal> {
  return request(`${ACTION_URL}/appointments/propose`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, appointment_id: appointmentId, intent, new_time: newTime }),
  });
}

export function confirmAppointmentAction(userId: string, caseId: string, confirmed: boolean): Promise<AppointmentResult> {
  return request(`${ACTION_URL}/appointments/confirm`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, case_id: caseId, confirmed, confirmed_by: "user" }),
  });
}
