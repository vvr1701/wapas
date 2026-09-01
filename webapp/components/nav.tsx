"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Command center", glyph: "◎" },
  { href: "/cases", label: "Case explorer", glyph: "⛓" },
  { href: "/call", label: "Live call", glyph: "◉" },
  { href: "/guardrails", label: "Guardrails", glyph: "▣" },
  { href: "/eval", label: "Evaluation", glyph: "≡" },
];

export function Nav() {
  const path = usePathname();
  return (
    <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col bg-sidebar px-3 py-6">
      <Link href="/" className="mb-8 block px-3">
        <span className="font-display text-2xl font-semibold tracking-tight text-white">
          🪃 Wapas
        </span>
        <span className="mt-1 block text-xs text-sidebartext">
          revenue, brought back
        </span>
      </Link>
      <nav className="flex flex-col gap-1">
        {LINKS.map((l) => {
          const active = path === l.href;
          return (
            <Link
              key={l.href}
              href={l.href}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-peri/20 font-medium text-white"
                  : "text-sidebartext hover:bg-sidebar2 hover:text-white"
              }`}
            >
              <span className={active ? "text-peri" : "text-sidebartext/70"}>{l.glyph}</span>
              {l.label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto space-y-1 px-3 text-[11px] leading-relaxed text-sidebartext/70">
        <p>Razorpay AI Buildathon 2026 · Track 3</p>
        <p className="font-mono">every action gated · every write chained</p>
      </div>
    </aside>
  );
}
