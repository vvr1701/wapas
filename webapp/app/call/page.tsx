"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Card } from "@/components/ui";
import { API, inr } from "@/lib/api";

type OrbState = "idle" | "listening" | "thinking" | "speaking";
type Turn = { role: "customer" | "agent"; text: string };

function Orb({ state }: { state: OrbState }) {
  return (
    <div className="relative flex h-44 w-44 items-center justify-center">
      {state === "listening" && (
        <>
          <span className="orb-ring absolute inset-0 rounded-full border-2 border-turmerichi/60" />
          <span className="orb-ring absolute inset-0 rounded-full border-2 border-turmerichi/40 [animation-delay:0.5s]" />
        </>
      )}
      {state === "speaking" && (
        <>
          <span className="orb-ring absolute inset-0 rounded-full border-2 border-jadehi/60" />
          <span className="orb-ring absolute inset-0 rounded-full border-2 border-jadehi/40 [animation-delay:0.45s]" />
        </>
      )}
      {state === "thinking" && (
        <span className="orb-think absolute inset-2 rounded-full border-2 border-dashed border-perihi/70" />
      )}
      <div
        className={`h-28 w-28 rounded-full transition-colors duration-500 ${
          state === "listening"
            ? "orb-listen bg-turmeric/60"
            : state === "speaking"
              ? "orb-breathe bg-jade/70"
              : state === "thinking"
                ? "bg-peri/40"
                : "orb-breathe bg-panel2"
        }`}
        style={{ boxShadow: "0 0 70px -8px rgba(19,100,241,0.25)" }}
      />
      <span className="absolute -bottom-7 font-mono text-[11px] uppercase tracking-widest text-sub">
        {state}
      </span>
    </div>
  );
}

type SessionInfo = {
  id: string;
  caseId: number;
  amount: number;
  name: string;
  due?: string;
  context?: string;
};

function LiveCall() {
  const caseParam = useSearchParams().get("case");
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [orb, setOrb] = useState<OrbState>("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [audioMode, setAudioMode] = useState(true);
  const [note, setNote] = useState<string | null>(null);
  const [lang, setLang] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Record<string, unknown> | null>(null);
  const [text, setText] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const held = useRef(false); // survives the mic-permission prompt on first press

  async function start(): Promise<string | null> {
    const q = caseParam ? `?case_id=${caseParam}` : "";
    const r = await fetch(`${API}/call/start${q}`, { method: "POST" });
    const j = await r.json();
    if (!r.ok) {
      setNote(
        j.error === "case_terminal"
          ? `case is ${j.state} — the agent stands down on closed cases`
          : "case not found"
      );
      return null;
    }
    setSession({
      id: j.session_id,
      caseId: j.case_id,
      amount: j.amount_inr,
      name: j.customer_name,
      due: j.due_date,
      context: j.context,
    });
    setOutcome(null);
    setTurns([]);
    setNote(null);
    return j.session_id as string;
  }

  // arriving via a case's Call button: dial immediately so the header names them
  useEffect(() => {
    if (caseParam) start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseParam]);

  async function sendTurn(fd: FormData) {
    const sid = session?.id ?? (await start());
    if (!sid) {
      setOrb("idle");
      return;
    }
    fd.append("session_id", sid);
    fd.append("mode", audioMode ? "audio" : "text");
    setOrb("thinking");
    const r = await fetch(`${API}/call/turn`, { method: "POST", body: fd });
    const j = await r.json();
    if (j.error) {
      // one bad utterance never disables voice for the session — show why, let them retry
      setNote(`speech failed: ${j.detail ?? j.error} — try again or switch to text`);
      setOrb("idle");
      return;
    }
    setTurns((t) => [
      ...t,
      { role: "customer", text: j.customer_text },
      { role: "agent", text: j.agent_text },
    ]);
    if (j.language) setLang(j.language);
    if (j.degraded) setNote("TTS unavailable — text only");
    if (j.agent_audio_b64) {
      const audio = new Audio(`data:audio/wav;base64,${j.agent_audio_b64}`);
      setOrb("speaking");
      audio.onended = () => setOrb("idle");
      audio.play().catch(() => setOrb("idle"));
    } else {
      setOrb("idle");
    }
    if (j.ended) setNote("call ended by policy");
  }

  async function pttDown() {
    held.current = true;
    if (!session && !(await start())) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (!held.current) {
      // released while the permission prompt was up — don't start a recorder nobody will stop
      stream.getTracks().forEach((t) => t.stop());
      setNote("hold the button while you speak");
      return;
    }
    recorder.current = new MediaRecorder(stream);
    chunks.current = [];
    recorder.current.ondataavailable = (e) => chunks.current.push(e.data);
    recorder.current.start();
    setOrb("listening");
  }

  function pttUp() {
    held.current = false;
    const rec = recorder.current;
    if (!rec || rec.state !== "recording") return;
    recorder.current = null;
    rec.onstop = async () => {
      rec.stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
      if (blob.size < 2000) {
        setNote("too short — hold the button while you speak");
        setOrb("idle");
        return;
      }
      const fd = new FormData();
      fd.append("audio", blob, "utt.webm");
      await sendTurn(fd);
    };
    rec.stop();
  }

  async function finish() {
    if (!session) return;
    const fd = new FormData();
    fd.append("session_id", session.id);
    const r = await fetch(`${API}/call/finish`, { method: "POST", body: fd });
    setOutcome(await r.json());
    setSession(null);
    setOrb("idle");
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="text-center">
        <h1 className="font-display text-xl font-semibold">Live call</h1>
        <p className="mt-1 text-xs text-sub">
          mic → Sarvam Saarika STT (any of 11 Indian languages + English) → Claude Sonnet 5
          (inside code rails) → Sarvam Bulbul TTS
        </p>
        {session && (
          <p className="mx-auto mt-3 inline-flex items-center gap-2 rounded-full border border-edge bg-panel px-4 py-1.5 text-sm">
            <span className="h-2 w-2 rounded-full bg-jade" />
            Calling <span className="font-medium">{session.name}</span>
            <span className="text-faint">·</span> case #{session.caseId}
            <span className="text-faint">·</span> {inr(session.amount)} due
            {session.context && (
              <>
                <span className="text-faint">·</span>
                <span className="text-sub">{session.context}</span>
              </>
            )}
          </p>
        )}
      </div>

      <div className="flex flex-col items-center gap-8 py-4">
        <Orb state={orb} />
        <div className="flex items-center gap-3">
          <button
            onPointerDown={pttDown}
            onPointerUp={pttUp}
            onPointerLeave={() => orb === "listening" && pttUp()}
            className="select-none rounded-full bg-peri px-6 py-3 font-medium text-white shadow-sm transition-transform active:scale-95"
          >
            🎤 hold to talk
          </button>
          <label className="flex items-center gap-2 text-xs text-sub">
            <input
              type="checkbox"
              checked={audioMode}
              onChange={(e) => setAudioMode(e.target.checked)}
              className="accent-peri"
            />
            voice replies
          </label>
          <button
            onClick={finish}
            disabled={!session}
            className="rounded-full border border-edge px-4 py-2 text-sm text-sub transition-colors hover:text-rosehi disabled:opacity-40"
          >
            end call
          </button>
        </div>
        {lang && (
          <p className="font-mono text-[11px] uppercase tracking-widest text-faint">
            speaking {lang}
          </p>
        )}
        {note && <p className="text-xs text-turmerichi">{note}</p>}
      </div>

      <Card className="min-h-40 space-y-3">
        {turns.length === 0 && !outcome && (
          <p className="py-8 text-center text-sm text-faint">
            Hold the mic and speak — try &ldquo;paise abhi nahi hain, salary 1 tarikh ko
            aayegi&rdquo; · or type below
          </p>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`flex ${t.role === "agent" ? "justify-start" : "justify-end"}`}>
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm leading-relaxed ${
                t.role === "agent"
                  ? "rounded-bl-sm bg-panel2 text-ink"
                  : "rounded-br-sm bg-peri/10 text-ink"
              }`}
            >
              {t.text}
            </div>
          </div>
        ))}
        {outcome && (
          <div className="rounded-lg border border-jade/40 bg-jade/10 p-4">
            <p className="font-display text-sm font-semibold text-jadehi">
              Post-call extraction · {String(outcome.outcome)}
            </p>
            <pre className="mt-2 overflow-x-auto font-mono text-xs text-sub">
              {JSON.stringify(outcome, null, 2)}
            </pre>
          </div>
        )}
      </Card>

      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (!text.trim()) return;
          const fd = new FormData();
          fd.append("text", text);
          setText("");
          await sendTurn(fd);
        }}
        className="flex gap-2"
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="…or type as the customer (text fallback always works)"
          className="flex-1 rounded-md border border-edge bg-panel px-4 py-2.5 text-sm text-ink placeholder:text-faint"
        />
        <button className="rounded-md bg-panel2 px-5 text-sm text-ink transition-colors hover:bg-edge">
          send
        </button>
      </form>
    </div>
  );
}

export default function LiveCallPage() {
  return (
    <Suspense>
      <LiveCall />
    </Suspense>
  );
}
