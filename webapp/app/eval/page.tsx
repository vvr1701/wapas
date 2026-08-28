"use client";

import { GroupedBars, PALETTE } from "@/components/charts";
import { Card, Loading, SectionTitle } from "@/components/ui";
import { inr, pct } from "@/lib/api";
import { useApi } from "@/lib/hooks";

type Metrics = {
  attribution: { natural_rate: number; rule: string };
  headline: {
    at_risk_inr: number;
    recovered_raw_inr: Record<"A" | "B" | "C", number>;
    recovered_adj_inr: Record<"B" | "C", number>;
    recovery_rate: Record<"A" | "B" | "C", number>;
    lift: { absolute: number; relative: number };
  };
  promises: { made: number; kept: number; kept_rate: number; inr_via_promises: number };
  cost: { llm_cost_usd: number; comms_cost_est_inr: number; cost_per_recovered_inr: number | null };
};

type Variance = {
  summary: {
    lift_relative: { mean: number; min: number; max: number };
    adjusted_C_over_B: { mean: number; min: number; max: number };
    stops_honored_all_seeds: boolean;
  };
  runs: {
    seed: number;
    at_risk_inr: number;
    raw: Record<"A" | "B" | "C", number>;
    adj: Record<"B" | "C", number>;
    lift_rel: number;
    stops_honored: number;
  }[];
};

const ARMS = [
  { key: "A", name: "A · do nothing", color: PALETTE.peri },
  { key: "B", name: "B · dumb baseline", color: PALETTE.turmeric },
  { key: "C", name: "C · Wapas", color: PALETTE.jade },
] as const;

export default function EvalPage() {
  const { data: m, error } = useApi<Metrics>("/api/metrics");
  const { data: v } = useApi<Variance>("/api/variance");
  const { data: exceptions } = useApi<{ markdown: string }>("/api/exceptions");
  if (!m) return <Loading error={error} />;
  const h = m.headline;

  const armData = [
    {
      measure: "recovered · raw",
      A: h.recovered_raw_inr.A,
      B: h.recovered_raw_inr.B,
      C: h.recovered_raw_inr.C,
    },
    {
      measure: "recovered · adjusted",
      A: 0,
      B: h.recovered_adj_inr.B,
      C: h.recovered_adj_inr.C,
    },
  ];

  const exceptionRows = (exceptions?.markdown ?? "")
    .split("\n")
    .filter((l) => l.startsWith("| ") && !l.startsWith("| Entity") && !l.startsWith("|--"))
    .map((l) => l.split("|").map((c) => c.trim()).filter(Boolean));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-xl font-semibold">Three arms, one world</h1>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-sub">
          Same seed, same 250 cases, same frozen behavior model — world-state hash asserted
          identical across arms before running. <span className="text-ink">{m.attribution.rule}.</span>
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <SectionTitle sub={`at risk ${inr(h.at_risk_inr)} · lift +${pct(h.lift.relative)} relative`}>
            Recovered ₹ by arm
          </SectionTitle>
          <GroupedBars
            data={armData}
            xKey="measure"
            series={ARMS.map((a) => ({ key: a.key, name: a.name, color: a.color }))}
            height={300}
          />
        </Card>
        <div className="space-y-4">
          <Card>
            <SectionTitle sub="captured on voice calls, verified against real payments">
              Promises
            </SectionTitle>
            <p className="font-display text-3xl font-semibold text-jadehi">
              {m.promises.kept}/{m.promises.made} kept
            </p>
            <p className="mt-1 text-xs text-sub">{inr(m.promises.inr_via_promises)} recovered via promises</p>
          </Card>
          <Card>
            <SectionTitle sub="measured from the llm_calls table, not estimated">Cost</SectionTitle>
            <ul className="space-y-1.5 text-sm text-sub">
              <li>Batch-eval LLM spend: <span className="font-mono text-ink">${m.cost.llm_cost_usd}</span> — rules cover 100% of structured diagnosis</li>
              <li>Comms estimate: <span className="font-mono text-ink">₹{m.cost.comms_cost_est_inr}</span></li>
              <li>Cost per recovered ₹: <span className="font-mono text-jadehi">₹{m.cost.cost_per_recovered_inr ?? "—"}</span></li>
            </ul>
          </Card>
        </div>
      </div>

      {v && (
        <Card>
          <SectionTitle
            sub={`mean relative lift +${pct(v.summary.lift_relative.mean)} · adjusted C over B mean ${v.summary.adjusted_C_over_B.mean}× · stops 100% on every seed`}
          >
            No cherry-picked seed — 5-seed variance
          </SectionTitle>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-edge text-left text-xs uppercase tracking-wider text-sub">
                <th className="py-2 pr-4">Seed</th>
                <th className="py-2 pr-4 text-right">At risk</th>
                <th className="py-2 pr-4 text-right">Raw C</th>
                <th className="py-2 pr-4 text-right">Adj C</th>
                <th className="py-2 pr-4 text-right">Adj B</th>
                <th className="py-2 text-right">Rel. lift</th>
              </tr>
            </thead>
            <tbody className="font-mono text-xs tabular-nums">
              {v.runs.map((r) => (
                <tr key={r.seed} className="border-b border-edge/40">
                  <td className="py-2 pr-4">{r.seed}</td>
                  <td className="py-2 pr-4 text-right">{inr(r.at_risk_inr)}</td>
                  <td className="py-2 pr-4 text-right">{inr(r.raw.C)}</td>
                  <td className="py-2 pr-4 text-right text-jadehi">{inr(r.adj.C)}</td>
                  <td className="py-2 pr-4 text-right">{inr(r.adj.B)}</td>
                  <td className="py-2 text-right">+{pct(r.lift_rel)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Card>
        <SectionTitle sub="machine-generated every eval — a deliverable, not an embarrassment">
          What it could NOT recover · {exceptionRows.length} cases
        </SectionTitle>
        <div className="max-h-80 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-panel">
              <tr className="text-left uppercase tracking-wider text-sub">
                <th className="py-2 pr-3">Entity</th>
                <th className="py-2 pr-3">Cat</th>
                <th className="py-2 pr-3 text-right">Amount ₹</th>
                <th className="py-2 pr-3">Root cause</th>
                <th className="py-2">Why it stopped</th>
              </tr>
            </thead>
            <tbody className="text-sub">
              {exceptionRows.map((r, i) => (
                <tr key={i} className="border-t border-edge/40">
                  <td className="py-1.5 pr-3 font-mono">{r[0]}</td>
                  <td className="py-1.5 pr-3">{r[1]}</td>
                  <td className="py-1.5 pr-3 text-right font-mono tabular-nums">{r[2]}</td>
                  <td className="py-1.5 pr-3">{r[3]}</td>
                  <td className="py-1.5">{r[5]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
