"""Live agent loop. Falls back to the scripted path if the model is unusable —
the demo must never die because of a network."""
import db
from agent.llm import available, complete, tool_declarations
from agent.supervisor import recover
from kernel.gateway import execute
from kernel.packs import load

MAX_STEPS = 8

SYSTEM = """You are a customer support agent for Acme Retail.
Resolve the customer's request using the tools available.
When a tool returns a handle like h_0001, refer to it as @h_0001 in later calls.
If a tool call is refused by policy, do not retry it — follow the guidance you
are given and complete the customer's original request."""


def run_live(job_id, task, pack_name="support"):
    if not available():
        from agent.worker import _run_scripted
        db.append_event(job_id, 0, "supervisor",
                        {"action": "FALLBACK", "guidance": "No API key — scripted mode."})
        return _run_scripted(job_id, "injected")

    pack = load(pack_name)
    tools = tool_declarations(pack)
    contents = [{"role": "user", "parts": [{"text": task}]}]

    try:
        for step in range(1, MAX_STEPS + 1):
            reply = complete(SYSTEM, contents, tools)
            if not reply["calls"]:
                break
            call = reply["calls"][0]
            contents.append({"role": "model",
                             "parts": [{"functionCall": {"name": call["name"],
                                                         "args": call["args"]}}]})
            res = execute(job_id, call["name"], call["args"], step)
            if res["status"] == "denied":
                g = recover(job_id, step, call["name"], res["rule"], res["reason"])
                db.append_event(job_id, step, "supervisor",
                                {"action": g["action"], "guidance": g["guidance"]})
                if g["action"] == "ABORT":
                    break
                payload = {"error": "blocked_by_policy", "guidance": g["guidance"]}
            else:
                payload = {"result": res.get("content", res.get("result")),
                           "handle": res.get("handle")}
            contents.append({"role": "user",
                             "parts": [{"functionResponse": {"name": call["name"],
                                                             "response": payload}}]})
    except Exception as exc:
        db.append_event(job_id, 0, "supervisor",
                        {"action": "ERROR", "guidance": f"Model unavailable: {exc}"})

    db.append_event(job_id, 99, "complete", {"message": "Task complete"})
    db.set_job(job_id, status="done")
