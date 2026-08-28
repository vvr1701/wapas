import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-xl border border-edge bg-panel p-5 shadow-[0_1px_3px_rgba(16,24,40,0.06)] ${className}`}>
      {children}
    </div>
  );
}

export function SectionTitle({ children, sub }: { children: ReactNode; sub?: string }) {
  return (
    <div className="mb-3">
      <h2 className="font-display text-lg font-semibold">{children}</h2>
      {sub && <p className="mt-0.5 text-xs text-sub">{sub}</p>}
    </div>
  );
}

export function Stat({
  label,
  value,
  tone = "ink",
  hint,
}: {
  label: string;
  value: ReactNode;
  tone?: "ink" | "jade" | "turmeric" | "rose";
  hint?: string;
}) {
  const tones = {
    ink: "text-ink",
    jade: "text-jadehi",
    turmeric: "text-turmerichi",
    rose: "text-rosehi",
  } as const;
  return (
    <Card>
      <p className="text-xs uppercase tracking-wider text-sub">{label}</p>
      <p className={`mt-1 font-display text-2xl font-semibold ${tones[tone]}`}>{value}</p>
      {hint && <p className="mt-1 text-[11px] text-faint">{hint}</p>}
    </Card>
  );
}

const STATE_TONES: Record<string, string> = {
  RECOVERED: "bg-jade/15 text-jadehi border-jade/40",
  PROMISE_PENDING: "bg-peri/15 text-perihi border-peri/40",
  ESCALATED: "bg-turmeric/15 text-turmerichi border-turmeric/40",
  STOPPED: "bg-rose/15 text-rosehi border-rose/40",
  EXHAUSTED: "bg-panel2 text-sub border-edge",
};

export function StateBadge({ state }: { state: string }) {
  const tone = STATE_TONES[state] ?? "bg-panel2 text-sub border-edge";
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${tone}`}>
      {state}
    </span>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[11px] text-faint">{children}</span>;
}

export function Loading({ error }: { error?: string | null }) {
  if (error)
    return (
      <Card className="border-rose/40">
        <p className="text-sm text-rosehi">API unreachable — start it with `make api`.</p>
        <p className="mt-1 font-mono text-xs text-faint">{error}</p>
      </Card>
    );
  return <p className="animate-pulse py-10 text-sm text-faint">reading the ledger…</p>;
}
