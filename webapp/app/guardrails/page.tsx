"use client";

import { useState } from "react";
import { ContactHeatmap, ReasonBars } from "@/components/charts";
import { Card, Loading, SectionTitle, Stat } from "@/components/ui";
import { inr, pct, type Escalation, type Guardrails } from "@/lib/api";
import { useApi } from "@/lib/hooks";

export default function GuardrailsPage() {
  const { data, error } = useApi<Guardrails>("/api/guardrails");
  const { data: escalations } = useApi<Escalation[]>("/api/escalations");
  const [open, setOpen] = useState<number | null>(null);
  if (!data) return <Loading error={error} />;

  return (
    <div className="space-y-6">
      <h1 className="font-display text-xl font-semibold">Guardrails & compliance</h1>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="stops honored" value={pct(data.stops_honored)} tone="jade"
          hint="the number that must print 100%" />
        <Stat label="actions after opt-out" value={data.actions_after_optout}
          tone={data.actions_after_optout === 0 ? "jade" : "rose"}
          hint="counted from the audit log" />
        <Stat label="opt-out registry" value={data.opt_out_registry_size} tone="ink"
          hint="permanent · instant · multi-trigger" />
        <Stat label="actions cancelled by opt-out" value={data.cancelled_actions} tone="ink"
          hint="queued work dies with the case" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle sub="blocked ≠ silent death — every block is audited; window blocks auto-replan">
            Blocked actions, by gate reason
          </SectionTitle>
          <ReasonBars entries={Object.entries(data.blocked_by_reason)} />
        </Card>
        <Card>
          <SectionTitle sub="every executed customer contact, by IST hour — the empty hours are the proof">
            Contact-window enforcement
          </SectionTitle>
          <div className="pt-4">
            <ContactHeatmap hours={data.heatmap_ist} />
          </div>
        </Card>
      </div>

      <Card>
        <SectionTitle sub="self-sufficient context packets — a human can act without reading code">
          Escalation queue · {escalations?.length ?? "…"}
        </SectionTitle>
        <div className="divide-y divide-edge/60">
          {escalations?.slice(0, 25).map((e) => (
            <div key={e.escalation_id}>
              <button
                onClick={() => setOpen(open === e.escalation_id ? null : e.escalation_id)}
                className="flex w-full items-center gap-3 py-2.5 text-left text-sm hover:text-jadehi"
              >
                <span className="font-mono text-xs text-faint">#{e.escalation_id}</span>
                <span className="rounded border border-turmeric/40 bg-turmeric/10 px-2 py-0.5 text-[11px] text-turmerichi">
                  {e.reason}
                </span>
                <span className="text-sub">case {e.case_id}</span>
                <span className="ml-auto font-mono tabular-nums">
                  {inr(Number(e.packet.case_summary.amount_due_inr ?? 0))}
                </span>
              </button>
              {open === e.escalation_id && (
                <div className="mb-3 rounded-lg bg-panel2 p-4 text-xs">
                  <p className="mb-2 text-sub">
                    <span className="text-ink">Recommended:</span>{" "}
                    {e.packet.recommended_next_step}
                  </p>
                  <p className="mb-2 font-mono text-faint">
                    diagnosis: {JSON.stringify(e.packet.diagnosis)}
                  </p>
                  <p className="font-mono text-faint">
                    actions tried: {e.packet.actions_tried.map((a) => String(a.action_type)).join(" → ") || "none"}
                  </p>
                </div>
              )}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
