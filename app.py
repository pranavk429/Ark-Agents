import os
import time as _time
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).parent
app = FastAPI(title="Agent Tower")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

# An audit record is read by a human. Wall-clock beats a unix epoch on screen.
templates.env.filters["clock"] = lambda ts: _time.strftime("%H:%M:%S",
                                                           _time.localtime(ts))

# Spec section 11: the approvals screen owes the human a plain-English reason.
# Every key here is a reason token this kernel emits itself (kernel/policy.py) —
# no tool output and no ticket text is ever looked up or rendered through this.
RISK_ENGLISH = {
    "private_data": "the payload carries private customer data",
    "external_destination": "the destination is outside the company",
    "internal_destination": "the destination is inside the company",
    "untrusted_context": "this job has already read untrusted outside content",
    "volume_exceeds_threshold": "this call moves more records than the pack allows at once",
}


def _plain_risk(risk: str) -> str:
    parts = [RISK_ENGLISH.get(t.strip(), t.strip()) for t in (risk or "").split(",")]
    return "; ".join(p for p in parts if p) or "held for human review"


templates.env.filters["plain_risk"] = _plain_risk

import db


@app.on_event("startup")
def _startup():
    db.init()


@app.get("/health")
def health():
    return {"status": "ok"}


from pydantic import BaseModel
from kernel.gateway import execute as gateway_execute


class ExecuteIn(BaseModel):
    job_id: str
    tool: str
    args: dict = {}
    step: int = 0


@app.post("/gateway/execute")
def gateway(body: ExecuteIn):
    return gateway_execute(body.job_id, body.tool, body.args, body.step)


from agent.worker import start as start_run


class RunIn(BaseModel):
    scenario: str = "clean"
    mode: str = "scripted"
    task: str | None = None
    pack: str = "support"
    governed: bool = True


@app.post("/runs")
def create_run(body: RunIn):
    job_id = start_run(body.scenario, body.mode, body.task, body.pack,
                       body.governed)
    return {"job_id": job_id}


from fastapi import Request


@app.get("/", response_class=HTMLResponse)
def run_page(request: Request, job: str | None = None):
    return templates.TemplateResponse(
        "run.html", {"request": request, "page": "run", "job_id": job})


@app.get("/runs/{job_id}/events", response_class=HTMLResponse)
def run_events(request: Request, job_id: str):
    return templates.TemplateResponse(
        "_events.html", {"request": request, "events": db.events_for(job_id)})


@app.get("/timeline", response_class=HTMLResponse)
def timeline(request: Request):
    return templates.TemplateResponse(
        "timeline.html", {"request": request, "page": "timeline",
                          "rows": db.all_decisions()})


@app.get("/approvals", response_class=HTMLResponse)
def approvals_page(request: Request):
    return templates.TemplateResponse(
        "approvals.html", {"request": request, "page": "approvals"})


@app.get("/approvals/list", response_class=HTMLResponse)
def approvals_list(request: Request):
    with db.connect() as c:
        rows = c.execute(
            "SELECT * FROM approvals WHERE status='pending' ORDER BY id").fetchall()
    return templates.TemplateResponse(
        "_approvals.html", {"request": request, "rows": rows})


@app.post("/approvals/{aid}/decide")
def decide(aid: int, d: str = "rejected"):
    # Fail closed: only the exact string 'approved' releases the hold. Anything
    # else — a typo, a stale button, a malformed request — is a denial.
    status = "approved" if d == "approved" else "rejected"
    # 'AND status=pending' matters: an expired hold's thread is already dead, so
    # approving it would report a release that can never happen.
    with db.connect() as c:
        cur = c.execute(
            "UPDATE approvals SET status=?, decided_at=? WHERE id=? AND status='pending'",
            (status, _time.time(), aid))
    return {"ok": cur.rowcount == 1, "status": status}
