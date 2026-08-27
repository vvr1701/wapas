"""Call console (FR-7.1, FR-7.4): browser page driving one call session.

Single responsibility: HTTP surface over the call agent — mic audio or typed
text in, agent speech (Sarvam TTS) or text out, with a mid-session audio/text
toggle. Speech failure degrades to text with a visible banner instead of
crashing (NFR-7). Run: uv run uvicorn channels.voice.console:app --reload
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Annotated

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from agent.cases import CaseState, DuplicateCase, open_case, transition
from channels.voice import call_agent, stt_tts
from channels.voice.policy import CallSession, respond
from ledger.db import RecoveryCaseRow, get_engine

app = FastAPI(title="Wapas call console")
_calls: dict[str, CallSession] = {}


def _demo_case(db: Session) -> RecoveryCaseRow:
    """The console needs a case to talk about; reuse or create the demo one."""
    try:
        case = open_case(
            db,
            entity_id="demo_call_case",
            customer_id="cust_demo",
            category="L3",
            amount_inr=18000,
            due_date=datetime(2026, 8, 17, tzinfo=UTC).isoformat(),
        )
        case.root_cause = "INVOICE_FORGOTTEN"
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
        case = db.query(RecoveryCaseRow).filter_by(entity_id="demo_call_case").one()
    return case


@app.post("/call/start")
def start_call() -> dict:
    with Session(get_engine()) as db:
        case = _demo_case(db)
        call = call_agent.new_call(case, "Vikram Singh", datetime.now(UTC).date().isoformat())
        session_id = f"call_{case.id}_{len(_calls)}"
        _calls[session_id] = call
        return {"session_id": session_id, "case_id": case.id, "amount_inr": case.amount_due_inr}


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
            text = stt_tts.speech_to_text(await audio.read())
        except stt_tts.SpeechUnavailable as e:
            return {"error": "stt_unavailable", "detail": str(e), "degraded": "text"}
    with Session(get_engine()) as db:
        case = db.get(RecoveryCaseRow, call.facts.case_id)
        turn = respond(call, text, call_agent.claude_conversation(db))
        call_agent.apply_turn_effects(db, case, turn)
        db.commit()
    audio_b64 = None
    if mode == "audio":
        try:
            audio_b64 = base64.b64encode(stt_tts.text_to_speech(turn.text)).decode()
        except stt_tts.SpeechUnavailable:
            degraded = "text"  # graceful: text still flows (NFR-7)
    return {
        "customer_text": text,
        "agent_text": turn.text,
        "agent_audio_b64": audio_b64,
        "ended": turn.end_call,
        "llm_used": turn.llm_used,
        "degraded": degraded,
    }


@app.post("/call/finish")
def call_finish(session_id: Annotated[str, Form()]) -> dict:
    call = _calls.pop(session_id)
    with Session(get_engine()) as db:
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
