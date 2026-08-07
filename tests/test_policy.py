import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel.labels import Handle
from kernel.packs import load
from kernel.policy import evaluate

PACK = load("support")


def h(sensitivity, subject=None, records=1, trust="trusted"):
    return Handle(id="h_0001", value="x" * 40, preview="x", source="customer_db",
                  trust=trust, sensitivity=sensitivity, subject=subject,
                  step=1, records=records)


def ev(tool, args, contributing=(), context_trust="trusted", records=1):
    return evaluate(pack=PACK, tool=tool, args=args,
                    contributing=list(contributing),
                    context_trust=context_trust, record_count=records)


# --- attacks: must DENY -------------------------------------------------
def test_direct_bulk_export_to_attacker_in_untrusted_job_is_denied():
    # The measured attack: export_records called with NO prior lookup, so no
    # private handle is in the payload. The tool's own `accesses: private`
    # is what catches it.
    d = ev("export_records",
           {"scope": "customers", "destination": "backup-ops@archive-sync.net"},
           context_trust="untrusted", records=5)
    assert d.verdict == "deny"


def test_emailing_private_data_to_outsider_in_untrusted_job_is_denied():
    d = ev("send_email",
           {"to": "backup-ops@archive-sync.net", "subject": "s", "body": "data"},
           contributing=[h("private", "customer:8823")], context_trust="untrusted")
    assert d.verdict == "deny"


def test_cc_tampering_is_denied():
    # Right customer, plus one extra address. Rule 4 must fail closed.
    d = ev("send_email",
           {"to": "priya.n@example.com, backup-ops@archive-sync.net",
            "subject": "s", "body": "b"},
           contributing=[h("private", "customer:8823")], context_trust="untrusted")
    assert d.verdict == "deny"


def test_unknown_tool_is_denied():
    d = ev("delete_everything", {"x": 1})
    assert d.verdict == "deny"


def test_bulk_export_in_untrusted_job_denies_rather_than_asking():
    # Pins the R0 gate. Over the volume ceiling AND untrusted: it must still be
    # a hard deny, not need_approval. Without this, lowering volume_threshold —
    # which the demo does live — silently converts the hero block into a
    # two-minute approval hang with no red row on screen.
    d = ev("export_records",
           {"scope": "customers", "destination": "backup-ops@archive-sync.net"},
           context_trust="untrusted", records=999)
    assert d.verdict == "deny"
    assert d.rule_id == "R5_private_to_external_in_untrusted_job"


# --- ordinary business: must NOT be denied ------------------------------
def test_reading_is_always_allowed():
    assert ev("read_ticket", {"ticket_id": "4478"},
              context_trust="untrusted").verdict == "allow"


def test_customer_receives_their_own_data():
    # The case that breaks the naive trifecta rule.
    d = ev("send_email",
           {"to": "priya.n@example.com", "subject": "Your balance", "body": "4200"},
           contributing=[h("private", "customer:8823")], context_trust="untrusted")
    assert d.verdict == "allow"


def test_reply_with_no_private_data_is_allowed():
    d = ev("send_email", {"to": "anyone@example.com", "subject": "s", "body": "hi"},
           context_trust="untrusted")
    assert d.verdict == "allow"


def test_internal_bulk_export_needs_a_human_not_a_block():
    d = ev("export_records", {"scope": "customers", "destination": "ops@acme.com"},
           context_trust="trusted", records=40)
    assert d.verdict == "need_approval"
