"use client";

import { GroupedBars, PALETTE, StateDots } from "@/components/charts";
import { Card, Loading, SectionTitle, Stat } from "@/components/ui";
import { inr, pct, type Overview } from "@/lib/api";
import { useApi, useCountUp } from "@/lib/hooks";

const LOOP = ["detect", "diagnose", "choose", "gate", "execute", "verify", "measure"];

function RecoveredHero({ adj, raw }: { adj: number; raw: number }) {
  const shown = useCountUp(adj, 1100);
  return (
    <div className="text-right">
      <p className="text-xs uppercase tracking-wider text-sub">recovered · adjusted</p>
      <p className="font-display text-5xl font-semibold tabular-nums text-jadehi">
        {inr(shown)}
      </p>
      <p className="mt-1 text-xs text-faint">raw {inr(raw)} — natural recovery subtracted</p>
    </div>
  );
}

export default function CommandCenter() {
  const { data, error } = useApi<Overview>("/api/overview");
  const { data: manifest } = useApi<Record<string, string | number | boolean>>("/api/manifest");
  if (!data) return <Loading error={error} />;
  const k = data.kpis;

  return (
    <div className="space-y-6">
      {data.razorpay === "unavailable" && (
        <Card className="border-turmeric/50 py-3 text-sm text-turmerichi">
          degraded: live Razorpay API unreachable — simulator-driven data only
        </Card>
      )}

      {/* The recovery equation: the whole product in one strip */}
      <Card className="flex flex-wrap items-center justify-between gap-6 !p-7">
        <div>
          <p className="text-xs uppercase tracking-wider text-sub">revenue at risk</p>
          <p className="font-display text-5xl font-semibold tabular-nums text-turmerichi">
            {inr(k.at_risk_inr)}
          </p>
          <p className="mt-1 text-xs text-faint">250 seeded cases · one merchant, three leaks</p>
        </div>
        <div className="flex flex-col items-center gap-2">
          <div className="flex items-center font-mono text-[11px] text-sub">
            {LOOP.map((stage, i) => (
              <span key={stage} className="flex items-center">
                {i > 0 && <span className="mx-1 text-faint">⛓</span>}
                <span className="rounded border border-edge bg-panel2 px-1.5 py-0.5">
                  {stage}
                </span>
              </span>
            ))}
          </div>
          <p className="text-[11px] text-faint">
            every action gated by deterministic code — the LLM never decides what&apos;s allowed
          </p>
        </div>
        <RecoveredHero adj={k.recovered_adj_c_inr} raw={k.recovered_raw_c_inr} />
      </Card>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="lift vs baseline" value={`+${pct(k.lift_relative)}`} tone="jade"
          hint="relative, raw recovery rate" />
        <Stat label="stops honored" value={pct(k.stops_honored)} tone="jade"
          hint="zero actions after any opt-out" />
        <Stat label="promises kept" value={pct(k.promises_kept_rate)} tone="ink"
          hint="voice promises, verified vs payments" />
        <Stat label="honest exceptions" value={k.exceptions_count} tone="turmeric"
          hint="cases it stopped trying, each with a reason" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle sub="at-risk vs recovered, per leak category">
            Recovery by category
          </SectionTitle>
          <GroupedBars
            data={data.by_category.map((c) => ({
              category: `${c.category} · ${c.cases} cases`,
              at_risk: c.at_risk_inr,
              recovered: c.recovered_inr,
            }))}
            xKey="category"
            series={[
              { key: "at_risk", name: "at risk", color: PALETTE.turmeric },
              { key: "recovered", name: "recovered", color: PALETTE.jade },
            ]}
          />
        </Card>
        <Card>
          <SectionTitle sub="terminal states across the batch — nothing left dangling">
            Where every case ended
          </SectionTitle>
          <div className="pt-6">
            <StateDots byState={data.by_state} />
          </div>
          <p className="mt-6 text-xs leading-relaxed text-sub">
            Natural recovery rate {pct(k.natural_rate, 1)} (measured by the do-nothing arm) —
            Wapas never takes credit for customers who would have paid anyway.
          </p>
        </Card>
      </div>

      {manifest && (
        <p className="font-mono text-[11px] leading-relaxed text-faint">
          seed {String(manifest.seed)} · batch {String(manifest.batch_hash).slice(0, 12)}… ⛓
          world {String(manifest.world_hash).slice(0, 12)}… (equal across arms) ⛓ policy{" "}
          {String(manifest.policy_version_hash).slice(0, 12)}… ⛓ {String(manifest.audit_chain)}
        </p>
      )}
    </div>
  );
}
