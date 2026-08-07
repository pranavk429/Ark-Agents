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
