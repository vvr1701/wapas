// Thin client for the FastAPI JSON layer — all logic lives server-side in Python.
export const API = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000";

export async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

// Indian digit grouping — a ledger writes ₹34,49,427, not ₹3,449,427.
const fmt = new Intl.NumberFormat("en-IN");
export const inr = (n: number) => `₹${fmt.format(Math.round(n))}`;
export const pct = (x: number, digits = 0) => `${(x * 100).toFixed(digits)}%`;

export type Kpis = {
  at_risk_inr: number;
  recovered_raw_c_inr: number;
  recovered_adj_c_inr: number;
  lift_relative: number;
  stops_honored: number;
  promises_kept_rate: number;
  exceptions_count: number;
  natural_rate: number;
};

export type Overview = {
  kpis: Kpis;
  by_state: Record<string, number>;
  by_category: {
    category: string;
    cases: number;
    at_risk_inr: number;
    recovered_inr: number;
    rate: number;
  }[];
  razorpay: "live" | "unavailable";
};

export type CaseRow = {
  case_id: number;
  entity: string;
  customer: string;
  category: string;
  amount_inr: number;
  state: string;
  root_cause: string | null;
  confidence: number | null;
};

export type TimelineEntry = {
  ts: string;
  actor: string;
  event: string;
  rule_id: string | null;
  detail: Record<string, unknown>;
  hash: string;
  prev: string;
};

export type Guardrails = {
  stops_honored: number;
  actions_after_optout: number;
  opt_out_registry_size: number;
  cancelled_actions: number;
  blocked_by_reason: Record<string, number>;
  heatmap_ist: Record<string, number>;
};

export type Escalation = {
  escalation_id: number;
  case_id: number;
  reason: string;
  acked_by: string | null;
  packet: {
    case_summary: Record<string, unknown>;
    diagnosis: Record<string, unknown>;
    actions_tried: Record<string, unknown>[];
    timeline: unknown[];
    recommended_next_step: string;
  };
};
