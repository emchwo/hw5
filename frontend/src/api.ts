// Thin client for the FastAPI desk routes in backend/main.py.
// Default backend: http://localhost:8000 (VITE_API_URL overrides it, e.g. for a test backend).

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type AgentName = "boss" | "inventory" | "accounting" | "facilities" | "customer_service";

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  status: string;
  resolved: boolean;
  sku: string | null;
  size: string | null;
  qty: number | null;
  notes: string | null;
}

export interface TicketsResponse {
  date_today: string;
  tickets: Ticket[];
}

export interface PendingApproval {
  kind: string;
  summary: string;
  amount: number | null;
  status: string;
}

export interface Resolution {
  ticket_id: number;
  status: string;
  decision: string;
  assigned_to: AgentName[];
  actions_taken: string[];
  pending_approvals: PendingApproval[];
  drafts: { recipient: string; subject: string; body: string; saved: boolean }[];
  next_steps: string[];
  ticket_note: string;
}

export interface RunResult {
  ticket_id: number;
  status: string;
  note: string;
  resolution: Resolution | null;
  usage: { requests: number; tool_calls: number; total_tokens: number };
}

export interface RunState {
  state: "idle" | "running" | "done" | "error";
  run_id: string | null;
  ticket_id: number | null;
  started_at: string | null;
  finished_at: string | null;
  result: (RunResult & { error?: string }) | null;
  pending_approvals: number;
}

export interface AgentEvent {
  index: number;
  ts: string;
  run_id: string;
  ticket_id: number | null;
  agent: AgentName | null;
  depth: number | null;
  kind: string;
  text: string;
  tool: string | null;
  approval_id: string | null;
}

export interface EventsResponse {
  last_index: number;
  events: AgentEvent[];
}

export interface ApprovalRequest {
  id: string;
  kind: "payment" | "purchase_order" | "discount";
  tool: string;
  requested_by: AgentName;
  ticket_id: number | null;
  amount: number | null;
  payee: string | null;
  summary: string;
}

export interface Approval {
  id: string;
  created_at: string;
  request: ApprovalRequest;
}

export interface Cash {
  account: string;
  balance: number;
  date: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not json */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  tickets: () => call<TicketsResponse>("/api/tickets"),
  run: (id: number) => call<RunState>(`/api/tickets/${id}/run`, { method: "POST" }),
  runState: () => call<RunState>("/api/run"),
  pastRun: (runId: string) => call<RunState>(`/api/runs/${encodeURIComponent(runId)}`),
  events: (after: number, runId?: string) =>
    call<EventsResponse>(`/api/events?after=${after}&limit=500${runId ? `&run_id=${encodeURIComponent(runId)}` : ""}`),
  approvals: () => call<Approval[]>("/api/approvals"),
  decide: (id: string, approved: boolean, approver?: string, reason?: string) =>
    call<{ approved: boolean }>(`/api/approvals/${id}`, {
      method: "POST",
      body: JSON.stringify({ approved, approver, reason }),
    }),
  cash: () => call<Cash>("/api/cash"),
  reset: () => call<{ reset: boolean; checking_balance: number }>("/api/reset", { method: "POST" }),
};

export const AGENTS: { id: AgentName; title: string; codename: string; role: string }[] = [
  { id: "boss", title: "The Director", codename: "BOSS", role: "Reads the ticket, assigns agents, makes the final call" },
  { id: "inventory", title: "Inventory", codename: "STOCKPILE", role: "Stock by SKU + size, restock vendor" },
  { id: "accounting", title: "Accounting", codename: "COINS", role: "Cash, invoices, margins, approvals" },
  { id: "facilities", title: "Facilities", codename: "IGLOO", role: "Lease, rent, landlord" },
  { id: "customer_service", title: "Customer Service", codename: "POSTCARD", role: "Drafts customer messages" },
];
