import json, pathlib
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .agent import run_conversation

app = FastAPI(title="Clinic Front Desk Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
RUNS: dict = {}
RESOLVED: set = set()
ROOT = pathlib.Path(__file__).resolve().parents[2]


class RunRequest(BaseModel):
    conversation_id: str
    today: str
    turns: list[str]


def _store(cid, turns, res):
    RUNS[cid] = {"turns": turns, "result": res}


@app.on_event("startup")
def seed():
    for p in sorted((ROOT / "conversations").glob("*.json")):
        s = json.load(open(p, encoding="utf-8"))
        _store(s["id"], s["turns"], run_conversation(s["id"], s["today"], s["turns"]))


@app.post("/agent/run")
def run(req: RunRequest):
    try:
        res = run_conversation(req.conversation_id, req.today, req.turns)
    except ValueError as e:
        raise HTTPException(422, f"invalid request: {e}")
    _store(req.conversation_id, req.turns, res)
    return res


@app.get("/conversations")
def conversations():
    return RUNS


@app.get("/stats")
def stats():
    rs = [v["result"] for v in RUNS.values()]
    esc = [r for r in rs if r["terminal_state"] == "escalated"]
    open_ = [r for r in esc if r["conversation_id"] not in RESOLVED]
    return {"total": len(rs),
            "completed": sum(r["terminal_state"] in ("booked", "rescheduled", "cancelled") for r in rs),
            "escalated": len(esc), "open": len(open_),
            "urgent": sum(r["escalation_reason"] == "clinical_urgent" for r in open_)}


@app.get("/handoffs")
def handoffs():
    return [{"conversation_id": cid, "caller_said": v["turns"][-1], "reason": v["result"]["escalation_reason"]}
            for cid, v in RUNS.items()
            if v["result"]["terminal_state"] == "escalated" and cid not in RESOLVED]


@app.post("/handoffs/{cid}/resolve")
def resolve(cid: str):
    if cid not in RUNS:
        raise HTTPException(404, f"unknown conversation {cid}")
    RESOLVED.add(cid)
    return {"ok": True}
