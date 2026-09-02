"""Call console + JSON API (FR-7.1, FR-7.4, PRD v1.1).

Single responsibility: the HTTP surface — mic audio or typed text in, agent
speech (Sarvam TTS) or text out with a mid-session audio/text toggle, plus thin
/api/* JSON wrappers over dashboard/data.py for the Next.js demo UI (webapp/).
No business logic lives here. Run: uv run uvicorn channels.voice.console:app
"""

from __future__ import annotations

import base64
import json
import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from agent import webhooks
from agent.cases import TERMINAL, CaseState, DuplicateCase, open_case, transition
from channels.voice import call_agent, stt_tts
from channels.voice.policy import CallSession, respond
from dashboard import data
from ledger.db import DEFAULT_DB, RecoveryCaseRow, get_engine
from simulator.seed_razorpay import synthetic_customer


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # live, callable demo cases must exist before anyone opens the explorer
    with Session(get_engine(_DB)) as db:
        _ensure_demo_cases(db)
    yield


app = FastAPI(title="Wapas console & API", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server (local demo only)
    allow_methods=["*"],
    allow_headers=["*"],
)
_calls: dict[str, CallSession] = {}


def _demo_db() -> Path:
    """The UI serves a *copy* of the eval artifact so live calls can mutate real
    cases (voice → promise → timeline, on screen) without touching the pristine
    reproducible eval DB. Delete data/demo.db to reset the demo world."""
    demo = Path("data/demo.db")
    if not demo.exists() and data.DEFAULT_EVAL_DB.exists():
        shutil.copyfile(data.DEFAULT_EVAL_DB, demo)
    return demo if demo.exists() else DEFAULT_DB


_DB = _demo_db()
webhooks.DB_PATH = _DB
app.include_router(webhooks.router)  # FR-2.3: same HMAC-verified path production uses


# --- JSON API for the Next.js UI: 3-line wrappers over dashboard/data.py -------


@app.get("/api/metrics")
def api_metrics() -> dict:
    return data.load_metrics()


@app.get("/api/manifest")
def api_manifest() -> dict:
    return data.load_manifest()


@app.get("/api/variance")
def api_variance() -> dict:
    return json.loads((data.RESULTS / "variance.json").read_text())


@app.get("/api/cases")
def api_cases(state: str | None = None, category: str | None = None) -> list[dict]:
    with data.session(_DB) as db:
        return data.list_cases(db, state=state, category=category)


@app.get("/api/cases/{case_id}/timeline")
def api_timeline(case_id: int) -> list[dict]:
    with data.session(_DB) as db:
        return data.case_timeline(db, case_id)


@app.get("/api/overview")
def api_overview() -> dict:
    with data.session(_DB) as db:
        return {
            "kpis": data.kpis(),
            "by_state": data.cases_by_state(db),
            "by_category": data.recovery_by_category(db),
            "razorpay": data.razorpay_status(),
        }


@app.get("/api/guardrails")
def api_guardrails() -> dict:
    with data.session(_DB) as db:
        return {
            **data.guardrails_view(db),
            "heatmap_ist": data.contact_hour_histogram(db),
        }


@app.get("/api/escalations")
def api_escalations() -> list[dict]:
    with data.session(_DB) as db:
        return data.escalation_queue(db)


@app.get("/api/promises")
def api_promises() -> list[dict]:
    with data.session(_DB) as db:
        return data.promises_list(db)


@app.get("/api/exceptions")
def api_exceptions() -> dict:
    return {"markdown": data.exceptions_table()}


# After a full eval every case is terminal, so the demo copy gets a few live,
# callable cases — real registry customers, honest demo_* entity ids, advanced
# through the state machine (never poked into a state directly).
_DEMO_CASES = [
    ("demo_call_case", "cust_0042", "L3", 18000, "2026-08-17", "INVOICE_FORGOTTEN"),
    ("demo_call_card", "cust_0007", "L1", 4999, "2026-08-25", "CARD_EXPIRED"),
    ("demo_call_cash", "cust_0113", "L2", 52000, "2026-08-20", "CLIENT_CASHFLOW_DELAY"),
]


def _ensure_demo_cases(db: Session) -> RecoveryCaseRow:
    first = None
    for entity_id, customer_id, category, amount, due, cause in _DEMO_CASES:
        try:
            case = open_case(
                db,
                entity_id=entity_id,
                customer_id=customer_id,
                category=category,
                amount_inr=amount,
                due_date=datetime.fromisoformat(due).replace(tzinfo=UTC).isoformat(),
            )
            case.root_cause = cause
            for st in (
                CaseState.DIAGNOSED,
                CaseState.PLANNED,
                CaseState.GATED,
                CaseState.EXECUTING,
                CaseState.AWAITING_OUTCOME,
            ):
                transition(db, case, st)
            db.commit()
        except DuplicateCase:
            case = db.query(RecoveryCaseRow).filter_by(entity_id=entity_id).one()
        first = first or case
    return first


def _demo_case(db: Session) -> RecoveryCaseRow:
    """The console needs a case to talk about; reuse or create the demo set."""
    return _ensure_demo_cases(db)


def _customer_name(customer_id: str) -> str:
    """Recover the deterministic seeded name; demo/unknown ids get the stock one."""
    try:
        return synthetic_customer(int(customer_id.rsplit("_", 1)[1]))["name"]
    except (ValueError, IndexError):
        return "Vikram Singh"


@app.post("/call/start", response_model=None)
def start_call(case_id: int | None = None) -> dict | JSONResponse:
    with Session(get_engine(_DB)) as db:
        case = db.get(RecoveryCaseRow, case_id) if case_id is not None else _demo_case(db)
        if case is None:
            return JSONResponse({"error": "no_such_case"}, status_code=404)
        if CaseState(case.state) in TERMINAL:
            # guardrail, not a bug: the agent never contacts a closed case
            return JSONResponse({"error": "case_terminal", "state": case.state}, status_code=409)
        name = _customer_name(case.customer_id)
        call = call_agent.new_call(case, name, datetime.now(UTC).date().isoformat())
        call.facts.context = (case.root_cause or "pending payment").replace("_", " ").lower()
        session_id = f"call_{case.id}_{len(_calls)}"
        _calls[session_id] = call
        return {
            "session_id": session_id,
            "case_id": case.id,
            "amount_inr": case.amount_due_inr,
            "customer_name": name,
            "due_date": case.due_date,
            "state": case.state,
            "context": call.facts.context,
        }


@app.post("/call/turn")
async def call_turn(
    session_id: Annotated[str, Form()],
    mode: Annotated[str, Form()] = "text",  # "text" | "audio" — switchable per turn (FR-7.4)
    text: Annotated[str, Form()] = "",
    audio: Annotated[UploadFile | None, File()] = None,
) -> dict:
    call = _calls[session_id]
    degraded = None
    if mode == "audio" and audio is not None:
        try:
            text, call.language = stt_tts.speech_to_text(await audio.read())
        except stt_tts.SpeechUnavailable as e:
            return {"error": "stt_unavailable", "detail": str(e), "degraded": "text"}
    with Session(get_engine(_DB)) as db:
        case = db.get(RecoveryCaseRow, call.facts.case_id)
        turn = respond(call, text, call_agent.claude_conversation(db))
        call_agent.apply_turn_effects(db, case, turn)
        db.commit()
    audio_b64 = None
    if mode == "audio":
        try:
            audio_b64 = base64.b64encode(
                stt_tts.text_to_speech(turn.text, lang=call.language)
            ).decode()
        except stt_tts.SpeechUnavailable:
            degraded = "text"  # graceful: text still flows (NFR-7)
    return {
        "customer_text": text,
        "agent_text": turn.text,
        "agent_audio_b64": audio_b64,
        "ended": turn.end_call,
        "llm_used": turn.llm_used,
        "language": call.language,
        "degraded": degraded,
    }


@app.post("/call/finish")
def call_finish(session_id: Annotated[str, Form()]) -> dict:
    call = _calls.pop(session_id)
    with Session(get_engine(_DB)) as db:
        case = db.get(RecoveryCaseRow, call.facts.case_id)
        result = call_agent.finish_call(db, case, call)
        db.commit()
    return result


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return _PAGE


_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Wapas call console</title>
<style>
 body{font-family:system-ui;max-width:640px;margin:2rem auto;padding:0 1rem}
 #log{border:1px solid #ccc;border-radius:8px;padding:1rem;min-height:280px}
 .agent{color:#0a5} .customer{color:#06c} .sys{color:#999;font-style:italic}
 #controls{margin-top:1rem;display:flex;gap:.5rem}
 input[type=text]{flex:1;padding:.5rem}
 button{padding:.5rem 1rem}
</style></head><body>
<h2>Wapas · Call console <small id="mode-label">(text mode)</small></h2>
<label><input type="checkbox" id="audio-mode"> Audio mode (Sarvam STT/TTS)</label>
<div id="log"></div>
<div id="controls">
 <input type="text" id="text" placeholder="Customer says... (text fallback)">
 <button id="send">Send</button>
 <button id="rec">🎤 Hold to talk</button>
 <button id="finish">End call</button>
</div>
<script>
let sid=null, mediaRec=null, chunks=[];
const log=(cls,t)=>{const d=document.createElement('div');d.className=cls;d.textContent=t;
 document.getElementById('log').appendChild(d);d.scrollIntoView();};
const audioMode=()=>document.getElementById('audio-mode').checked;
document.getElementById('audio-mode').onchange=()=>{
 document.getElementById('mode-label').textContent=audioMode()?'(audio mode)':'(text mode)';};
async function start(){const r=await fetch('/call/start',{method:'POST'});const j=await r.json();
 sid=j.session_id;log('sys',`Call started · case ${j.case_id} · ₹${j.amount_inr} due`);}
async function turn(fd){fd.append('session_id',sid);fd.append('mode',audioMode()?'audio':'text');
 const r=await fetch('/call/turn',{method:'POST',body:fd});const j=await r.json();
 if(j.error){log('sys','⚠ '+j.error+' — degraded to text mode');return;}
 log('customer','🧑 '+j.customer_text);log('agent','🤖 '+j.agent_text);
 if(j.degraded)log('sys','⚠ TTS unavailable — text only');
 if(j.agent_audio_b64){new Audio('data:audio/wav;base64,'+j.agent_audio_b64).play();}
 if(j.ended)log('sys','— call ended by policy —');}
document.getElementById('send').onclick=async()=>{if(!sid)await start();
 const t=document.getElementById('text');const fd=new FormData();fd.append('text',t.value);
 t.value='';await turn(fd);};
document.getElementById('rec').onmousedown=async()=>{if(!sid)await start();
 const stream=await navigator.mediaDevices.getUserMedia({audio:true});
 mediaRec=new MediaRecorder(stream);chunks=[];mediaRec.ondataavailable=e=>chunks.push(e.data);
 mediaRec.start();};
document.getElementById('rec').onmouseup=()=>{if(!mediaRec)return;
 mediaRec.onstop=async()=>{const blob=new Blob(chunks,{type:'audio/wav'});
  const fd=new FormData();fd.append('audio',blob,'utt.wav');await turn(fd);};
 mediaRec.stop();};
document.getElementById('finish').onclick=async()=>{const fd=new FormData();
 fd.append('session_id',sid);const r=await fetch('/call/finish',{method:'POST',body:fd});
 log('sys','Post-call: '+JSON.stringify(await r.json()));sid=null;};
</script></body></html>"""
