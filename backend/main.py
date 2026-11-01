"""FastAPI app: call endpoints, TTS proxy, and the browser test client.

Run:  uvicorn backend.main:app --reload   then open http://localhost:8000
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import speech
from backend.agent import GREETING, CallSession
from backend.db import ROOT, get_conn

app = FastAPI(title="Amina - Banking Voice AI Support Agent")
sessions: dict[int, CallSession] = {}


class Utterance(BaseModel):
    text: str


@app.post("/call/start")
def start_call() -> dict:
    session = CallSession()
    sessions[session.state.call_id] = session
    return {"call_id": session.state.call_id, "reply": GREETING}


@app.post("/call/{call_id}/say")
def say(call_id: int, body: Utterance) -> dict:
    session = sessions.get(call_id)
    if session is None:
        raise HTTPException(404, "call not found")
    if session.state.transferred:
        return {"reply": "جاري تحويلك لزميل دلوقتي.", "trace": [],
                "verified": session.state.verified, "transferred": True}
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty utterance")
    return session.respond(text)


@app.post("/tts")
def tts(body: Utterance) -> Response:
    if not speech.is_configured():
        raise HTTPException(503, "Azure Speech not configured")
    try:
        return Response(speech.synthesize(body.text), media_type="audio/mpeg")
    except Exception as exc:
        raise HTTPException(502, f"speech failed: {type(exc).__name__}")


@app.get("/tickets")
def tickets() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tickets ORDER BY ticket_id DESC").fetchall()
    return [dict(r) for r in rows]


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse("/web/index.html")


app.mount("/web", StaticFiles(directory=ROOT / "web"), name="web")
