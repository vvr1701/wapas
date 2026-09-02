"use client";

import Link from "next/link";
import { useState } from "react";
import { ChainTimeline } from "@/components/chain";
import { Card, Loading, SectionTitle, StateBadge } from "@/components/ui";
import { inr, type CaseRow, type TimelineEntry } from "@/lib/api";
import { useApi } from "@/lib/hooks";

const STATES = [
  "",
  "AWAITING_OUTCOME",
  "PROMISE_PENDING",
  "RECOVERED",
  "ESCALATED",
  "STOPPED",
  "EXHAUSTED",
];
const TERMINAL = new Set(["RECOVERED", "ESCALATED", "STOPPED", "EXHAUSTED"]);
const CATS = ["", "L1", "L2", "L3"];

function Select({
  value,
  onChange,
  options,
  all,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
  all: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md border border-edge bg-panel2 px-3 py-1.5 text-sm text-ink"
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o || all}
        </option>
      ))}
    </select>
  );
}

export default function CaseExplorer() {
  const [state, setState] = useState("");
  const [cat, setCat] = useState("");
  const [selected, setSelected] = useState<CaseRow | null>(null);
  const query = new URLSearchParams();
  if (state) query.set("state", state);
  if (cat) query.set("category", cat);
  // 5s poll: a live call on another tab flips state/timeline before your eyes
  const { data: cases, error } = useApi<CaseRow[]>(`/api/cases?${query}`, 5000);
  const { data: timeline } = useApi<TimelineEntry[]>(
    selected ? `/api/cases/${selected.case_id}/timeline` : "/api/cases/0/timeline",
    5000
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="mr-auto font-display text-xl font-semibold">Case explorer</h1>
        <Select value={state} onChange={setState} options={STATES} all="All states" />
        <Select value={cat} onChange={setCat} options={CATS} all="All categories" />
      </div>

      {!cases ? (
        <Loading error={error} />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[1fr_460px]">
          <Card className="overflow-hidden !p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-edge text-left text-xs uppercase tracking-wider text-sub">
                  <th className="px-4 py-3">Case</th>
                  <th className="px-4 py-3">Cat</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                  <th className="px-4 py-3">Root cause</th>
                  <th className="px-4 py-3">State</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {cases.map((c) => (
                  <tr
                    key={c.case_id}
                    onClick={() => setSelected(c)}
                    className={`cursor-pointer border-b border-edge/50 transition-colors hover:bg-panel2/70 ${
                      selected?.case_id === c.case_id ? "bg-panel2" : ""
                    }`}
                  >
                    <td className="px-4 py-2.5 font-mono text-xs text-sub">
                      #{c.case_id} · {c.entity}
                    </td>
                    <td className="px-4 py-2.5">{c.category}</td>
                    <td className="px-4 py-2.5 text-right font-mono tabular-nums">
                      {inr(c.amount_inr)}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-sub">{c.root_cause}</td>
                    <td className="px-4 py-2.5">
                      <StateBadge state={c.state} />
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {!TERMINAL.has(c.state) && (
                        <Link
                          href={`/call?case=${c.case_id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="rounded-full bg-peri px-3 py-1 text-xs font-medium text-white transition-transform hover:bg-perihi active:scale-95"
                        >
                          ◉ Call
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="px-4 py-2 text-xs text-faint">{cases.length} cases</p>
          </Card>

          <Card className="max-h-[78vh] overflow-y-auto">
            {selected ? (
              <>
                <SectionTitle sub="rendered from the hash-chained audit log — nothing else">
                  Case #{selected.case_id} · {inr(selected.amount_inr)}
                </SectionTitle>
                {timeline ? <ChainTimeline entries={timeline} /> : <Loading />}
              </>
            ) : (
              <p className="py-16 text-center text-sm text-faint">
                Select a case to unroll its audit chain
              </p>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
