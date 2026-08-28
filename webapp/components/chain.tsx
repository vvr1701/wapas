"use client";

// The signature element: the audit hash chain, drawn as what it is — linked
// blocks where each record carries the previous record's hash.
import type { TimelineEntry } from "@/lib/api";

const ACTOR_TONE: Record<string, string> = {
  system: "text-sub",
  agent: "text-perihi",
  customer: "text-turmerichi",
  human: "text-rosehi",
};

export function ChainTimeline({ entries }: { entries: TimelineEntry[] }) {
  return (
    <ol className="relative ml-2">
      {entries.map((e, i) => (
        <li key={i} className="relative border-l border-edge pb-4 pl-5 last:pb-0">
          <span
            className={`absolute -left-[5px] top-1 h-2.5 w-2.5 rounded-sm border ${
              e.event === "state_transition"
                ? "border-jadehi bg-jade/30"
                : e.event === "action_blocked"
                  ? "border-rosehi bg-rose/30"
                  : "border-faint bg-panel2"
            }`}
          />
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className={`text-xs font-medium ${ACTOR_TONE[e.actor] ?? "text-sub"}`}>
              {e.actor}
            </span>
            <span className="font-mono text-xs text-ink">{e.event}</span>
            {e.rule_id && (
              <span className="rounded border border-edge bg-panel2 px-1.5 font-mono text-[10px] text-sub">
                {e.rule_id}
              </span>
            )}
          </div>
          {typeof e.detail.rationale === "string" ? (
            <p className="mt-1 max-w-xl text-xs leading-relaxed text-sub">
              {e.detail.rationale}
            </p>
          ) : (
            <p className="mt-1 max-w-xl truncate font-mono text-[11px] text-faint">
              {JSON.stringify(e.detail)}
            </p>
          )}
          <p className="mt-1 font-mono text-[10px] text-faint">
            {e.prev} ⛓ <span className="text-jadehi/70">{e.hash}</span>
          </p>
        </li>
      ))}
    </ol>
  );
}
