"use client";

// Recharts wrappers implementing the mark spec: thin bars with 4px rounded data
// ends, 2px surface gaps, recessive grid, dark tooltip, legend when >= 2 series.
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { inr } from "@/lib/api";

// Blade steps, categorical order validated: emerald, azure, cider, crimson.
export const PALETTE = {
  jade: "#008f47", // emerald.600 — recovered / Wapas
  peri: "#1364f1", // azure.500 — Razorpay primary / arm A
  turmeric: "#e05e00", // cider.600 — at risk / baseline
  rose: "#aa190e", // crimson.700 — stopped
} as const;

const AXIS = { fill: "#616d75", fontSize: 11 };
const tooltipStyle = {
  background: "#ffffff",
  border: "1px solid #dee2e4",
  borderRadius: 8,
  fontSize: 12,
  color: "#292e31",
  boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
};

export function GroupedBars({
  data,
  series,
  xKey,
  money = true,
  height = 260,
}: {
  data: Record<string, unknown>[];
  series: { key: string; name: string; color: string }[];
  xKey: string;
  money?: boolean;
  height?: number;
}) {
  const fmt = (v: number) => (money ? inr(v) : String(v));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} barCategoryGap="24%" barGap={2}>
        <CartesianGrid stroke="#e6e9ea" strokeDasharray="0" vertical={false} />
        <XAxis dataKey={xKey} tick={AXIS} axisLine={{ stroke: "#dee2e4" }} tickLine={false} />
        <YAxis
          tick={AXIS}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v: number) => (money ? `₹${(v / 100000).toFixed(1)}L` : String(v))}
          width={56}
        />
        <Tooltip
          contentStyle={tooltipStyle}
          cursor={{ fill: "#e6e9ea", opacity: 0.5 }}
          formatter={(v) => fmt(Number(v))}
        />
        {series.length > 1 && (
          <Legend wrapperStyle={{ fontSize: 12, color: "#616d75" }} iconSize={9} />
        )}
        {series.map((s) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.name}
            fill={s.color}
            radius={[4, 4, 0, 0]}
            maxBarSize={34}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ReasonBars({
  entries,
  color = PALETTE.turmeric,
  height = 220,
}: {
  entries: [string, number][];
  color?: string;
  height?: number;
}) {
  const data = entries.map(([reason, count]) => ({ reason, count }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" barCategoryGap="28%">
        <CartesianGrid stroke="#e6e9ea" horizontal={false} />
        <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} allowDecimals={false} />
        <YAxis
          type="category"
          dataKey="reason"
          tick={{ ...AXIS, fill: "#292e31" }}
          width={180}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "#e6e9ea", opacity: 0.5 }} />
        <Bar dataKey="count" fill={color} radius={[0, 4, 4, 0]} maxBarSize={18} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** 24 IST hours; the enforced 10:00–19:00 window is shaded. Zero bars outside it
 *  is the compliance proof, so the empty hours are the point. */
export function ContactHeatmap({ hours }: { hours: Record<string, number> }) {
  const max = Math.max(1, ...Object.values(hours));
  return (
    <div>
      <div className="flex items-end gap-[2px]">
        {Array.from({ length: 24 }, (_, h) => {
          const n = hours[String(h)] ?? 0;
          const inWindow = h >= 10 && h < 19;
          return (
            <div key={h} className="group relative flex-1">
              <div
                className={`w-full rounded-t-[3px] ${inWindow ? "bg-jade" : "bg-rose"}`}
                style={{ height: `${8 + (n / max) * 96}px`, opacity: n ? 1 : 0.16 }}
                title={`${String(h).padStart(2, "0")}:00 IST — ${n} contacts`}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-faint">
        <span>00</span>
        <span className="text-jadehi">10:00 ─ window ─ 19:00</span>
        <span>23</span>
      </div>
    </div>
  );
}

export function StateDots({ byState }: { byState: Record<string, number> }) {
  const colors: Record<string, string> = {
    RECOVERED: PALETTE.jade,
    ESCALATED: PALETTE.turmeric,
    STOPPED: PALETTE.rose,
    EXHAUSTED: "#7b878e",
    PROMISE_PENDING: PALETTE.peri,
  };
  const total = Object.values(byState).reduce((a, b) => a + b, 0);
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full">
        {Object.entries(byState).map(([state, n]) => (
          <div
            key={state}
            style={{
              width: `${(n / total) * 100}%`,
              background: colors[state] ?? "#7b878e",
              marginRight: 2,
            }}
            title={`${state}: ${n}`}
          />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-sub">
        {Object.entries(byState).map(([state, n]) => (
          <span key={state} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ background: colors[state] ?? "#7b878e" }}
            />
            {state} · {n}
          </span>
        ))}
      </div>
    </div>
  );
}

export { Cell };
