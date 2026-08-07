import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel.packs import load
from kernel.policy import evaluate

PACK = load("support")


def ev(tool, args, context_trust="trusted", records=1, pack=None):
    return evaluate(pack=pack or PACK, tool=tool, args=args, contributing=[],
                    context_trust=context_trust, record_count=records)


def test_bulk_export_step1_is_green_at_the_default_threshold():
    d = ev("export_records", {"scope": "customers", "destination": "ops@acme.com"},
           records=5)
    assert (d.verdict, d.rule_id) == ("allow", "R3_internal_destination")


def test_bulk_export_step2_holds_for_a_human():
    # The Approvals beat. This is the only scripted call that ever produces one.
    d = ev("export_records",
           {"scope": "customers", "destination": "finance@partner.com"}, records=5)
    assert (d.verdict, d.rule_id) == ("need_approval", "R6_trusted_external")


def test_live_edit_flips_step1_from_allow_to_approval():
    # The Q21 moment: threshold 25 -> 3 must change the verdict, not just the rule.
    d = ev("export_records", {"scope": "customers", "destination": "ops@acme.com"},
           records=5, pack=dict(PACK, volume_threshold=3))
    assert (d.verdict, d.rule_id) == ("need_approval", "R0_volume_exceeds_threshold")


def test_lowered_threshold_does_not_soften_the_poisoned_run():
    # The hero block must survive an edited threshold. Without R0's trusted-only
    # gate this returns need_approval and the demo becomes a 120s silent hold.
    d = ev("export_records",
           {"scope": "customers", "destination": "backup-ops@archive-sync.net"},
           context_trust="untrusted", records=5,
           pack=dict(PACK, volume_threshold=3))
    assert (d.verdict, d.rule_id) == ("deny", "R5_private_to_external_in_untrusted_job")


def test_clean_ticket_reply_cannot_demonstrate_the_live_edit():
    # Documents why step 7 uses bulk_export: the clean reply carries no private
    # data and is scope 'one', so it exits at R2 whatever the threshold is.
    for threshold in (25, 3, 1):
        d = ev("send_email", {"to": "tom.h@example.com", "subject": "Order update",
                              "body": "Your order is in transit."},
               context_trust="untrusted", pack=dict(PACK, volume_threshold=threshold))
        assert (d.verdict, d.rule_id) == ("allow", "R2_no_private"), threshold
