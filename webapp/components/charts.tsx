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

export const PALETTE = {
  peri: "#5F7ADB",
  jade: "#1FA976",
  turmeric: "#BB8426",
  rose: "#C9648B",
} as const;

const AXIS = { fill: "#8C99AD", fontSize: 11 };
const tooltipStyle = {
  background: "#1C2534",
  border: "1px solid #2A3547",
  borderRadius: 8,
  fontSize: 12,
  color: "#E9EDF5",
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
        <CartesianGrid stroke="#2A3547" strokeDasharray="0" vertical={false} />
        <XAxis dataKey={xKey} tick={AXIS} axisLine={{ stroke: "#2A3547" }} tickLine={false} />
        <YAxis
          tick={AXIS}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v: number) => (money ? `₹${(v / 100000).toFixed(1)}L` : String(v))}
          width={56}
        />
        <Tooltip
          contentStyle={tooltipStyle}
          cursor={{ fill: "#2A3547", opacity: 0.35 }}
          formatter={(v) => fmt(Number(v))}
        />
        {series.length > 1 && (
          <Legend wrapperStyle={{ fontSize: 12, color: "#8C99AD" }} iconSize={9} />
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
        <CartesianGrid stroke="#2A3547" horizontal={false} />
        <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} allowDecimals={false} />
        <YAxis
          type="category"
          dataKey="reason"
          tick={{ ...AXIS, fill: "#E9EDF5" }}
          width={180}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "#2A3547", opacity: 0.35 }} />
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
                style={{ height: `${8 + (n / max) * 96}px`, opacity: n ? 1 : 0.14 }}
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
    EXHAUSTED: "#5A6678",
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
              background: colors[state] ?? "#5A6678",
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
              style={{ background: colors[state] ?? "#5A6678" }}
            />
            {state} · {n}
          </span>
        ))}
      </div>
    </div>
  );
}

export { Cell };
