"""POST /gateway/execute — the only route from an agent to a tool.

Fail-closed: any exception, timeout, or unmatched request becomes DENY.
"""
import time

import db
from kernel.labels import STORE
from kernel.packs import load
from kernel.policy import Decision, evaluate
from kernel.tools import REGISTRY, record_count

APPROVAL_TIMEOUT_S = 120


def _wait_for_approval(approval_id):
    deadline = time.time() + APPROVAL_TIMEOUT_S
    while time.time() < deadline:
        with db.connect() as c:
            row = c.execute("SELECT status FROM approvals WHERE id=?",
                            (approval_id,)).fetchone()
        if row and row["status"] in ("approved", "rejected"):
            return row["status"]
        time.sleep(0.4)
    # Mark it. Otherwise the row stays 'pending' forever and reappears on the
    # approvals screen hours later as a stale WAITING item whose thread is long
    # dead — clicking Approve on it does nothing, on stage, in front of judges.
    with db.connect() as c:
        c.execute("UPDATE approvals SET status='expired', decided_at=? WHERE id=?",
                  (time.time(), approval_id))
    return "expired"          # timeout is a denial, never a silent allow


def execute(job_id: str, tool: str, args: dict, step: int) -> dict:
    started = time.time()
    job = db.get_job(job_id)
    pack_name = job["pack"] if job else "support"
    context_trust = job["context_trust"] if job else "trusted"
    pack = load(pack_name)

    try:
        contributing = STORE.contributing(job_id, args)
        count = record_count(pack, tool, args)
        d = evaluate(pack=pack, tool=tool, args=args, contributing=contributing,
                     context_trust=context_trust, record_count=count)
    except Exception as exc:                                  # fail closed
        d = Decision("deny", "R_kernel_error", [f"kernel_error:{type(exc).__name__}"],
                     [], [], ["R_kernel_error"])

    # Approval is a hold, not advice: the call does not proceed until a human says so.
    if d.verdict == "need_approval":
        with db.connect() as c:
            cur = c.execute(
                "INSERT INTO approvals (job_id,step,tool,args_preview,risk,status,created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (job_id, step, tool, str(args)[:300],
                 ", ".join(d.reasons), "pending", time.time()))
            approval_id = cur.lastrowid
        # Show the hold on the run screen too. The decision event below is only
        # written once a human decides, so without this the run looks frozen for
        # as long as the approval sits there.
        db.append_event(job_id, step, "pending",
                        {"tool": tool, "args_preview": str(args)[:300],
                         "rule_id": d.rule_id, "reasons": d.reasons},
                        tool=tool, decision="need_approval")
        outcome = _wait_for_approval(approval_id)
        if outcome != "approved":
            d = Decision("deny", f"R_approval_{outcome}", [f"approval_{outcome}"],
                         d.labels_in, d.contributing, d.matched_rules)
        else:
            d = Decision("allow", "R_human_approved", ["approved_by_human"],
                         d.labels_in, d.contributing, d.matched_rules)

    record = {
        "tool": tool, "args_preview": str(args)[:300], "rule_id": d.rule_id,
        "reasons": d.reasons, "labels_in": d.labels_in,
        "contributing": d.contributing, "matched_rules": d.matched_rules,
        "duration_ms": round((time.time() - started) * 1000, 1),
    }
    db.append_event(job_id, step, "decision", record, tool=tool, decision=d.verdict)

    if d.verdict != "allow":
        return {"status": "denied", "rule": d.rule_id, "reason": ", ".join(d.reasons)}

    result = REGISTRY[tool](args)
    spec = pack["tool_index"][tool]
    produces = spec.get("produces")
    if produces:
        subject = None
        if produces.get("subject_from"):
            subject = f"customer:{args.get(produces['subject_from'])}"
        h = STORE.put(job_id, value=result, source=produces["source"],
                      trust=produces["trust"], sensitivity=produces["sensitivity"],
                      subject=subject, step=step, records=record_count(pack, tool, args))
        if produces["trust"] == "untrusted":
            db.set_job(job_id, context_trust="untrusted")
        return {"status": "allowed", "handle": h.id, "preview": h.preview,
                "content": result}
    return {"status": "allowed", "result": result}
