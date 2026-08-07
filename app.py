import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).parent
app = FastAPI(title="Agent Tower")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

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


@app.post("/runs")
def create_run(body: RunIn):
    job_id = start_run(body.scenario, body.mode, body.task, body.pack)
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
