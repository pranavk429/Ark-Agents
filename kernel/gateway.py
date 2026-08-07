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


def _producing_tool(pack, source):
    """Which tool in this pack produces data carrying that source label."""
    for t in pack["tools"]:
        if (t.get("produces") or {}).get("source") == source:
            return t["name"]
    return source


def _provenance(job_id, pack, tool, decision, context_trust):
    """Attribution lines for the UI: which earlier step caused each label.

    These are the arrows in spec section 11 — the thing a payload-only
    guardrail cannot draw. Every string here is composed from enumerated
    kernel-side values (tool names, source labels, handle ids). No tool
    output and no ticket text ever reaches this function.
    """
    spec = pack["tool_index"].get(tool)
    if spec is None:
        return []
    lines = []

    payload_private = [h for h in (STORE.get(job_id, i) for i in decision.contributing)
                       if h is not None and h.sensitivity == "private"]
    for h in payload_private:
        lines.append(f"carries PRIVATE ← from {_producing_tool(pack, h.source)} ({h.id})")
    # The measured attack calls export_records with nothing in the payload.
    # The label comes from the tool's own declaration, so say that plainly.
    if not payload_private and spec.get("accesses") == "private":
        lines.append(f"carries PRIVATE ← {tool} reaches private data directly")

    if context_trust == "untrusted":
        first = next((h for h in STORE.all(job_id) if h.trust == "untrusted"), None)
        if first:
            lines.append(f"job context UNTRUSTED ← from "
                         f"{_producing_tool(pack, first.source)} ({first.id})")
        else:
            lines.append("job context UNTRUSTED ← an earlier step read untrusted content")
    return lines


def execute(job_id: str, tool: str, args: dict, step: int,
            governed: bool = True) -> dict:
    started = time.time()
    job = db.get_job(job_id)
    pack_name = job["pack"] if job else "support"
    context_trust = job["context_trust"] if job else "trusted"
    pack = load(pack_name)

    # Ungoverned demo mode: record what WOULD have happened, then run it anyway.
    # This is the comparison, not a security hole — it exists only so a judge can
    # watch the same attack succeed without the kernel.
    if not governed:
        db.append_event(job_id, step, "decision",
                        {"tool": tool, "args_preview": str(args)[:300],
                         "rule_id": "TOWER_OFF", "reasons": ["kernel_disabled"],
                         "labels_in": [], "contributing": [], "matched_rules": [],
                         "duration_ms": 0.0},
                        tool=tool, decision="ungoverned")
        try:
            result = REGISTRY[tool](args)
        except Exception as exc:      # an unknown tool must not 500 the demo
            result = f"tool_error:{type(exc).__name__}"
        return {"status": "allowed", "result": result}

    try:
        contributing = STORE.contributing(job_id, args)
        count = record_count(pack, tool, args)
        d = evaluate(pack=pack, tool=tool, args=args, contributing=contributing,
                     context_trust=context_trust, record_count=count)
    except Exception as exc:                                  # fail closed
        d = Decision("deny", "R_kernel_error", [f"kernel_error:{type(exc).__name__}"],
                     [], [], ["R_kernel_error"])

    # Computed once, from the labels as they stood at decision time. Approval
    # can change the verdict but never changes where the data came from.
    prov = _provenance(job_id, pack, tool, d, context_trust)

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
                         "rule_id": d.rule_id, "reasons": d.reasons,
                         "provenance": prov},
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
        "provenance": prov,
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
