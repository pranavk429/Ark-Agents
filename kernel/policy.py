"""The gate rule. Pure — no database, no network, no clock.

Effective private data = private handles in the payload
                       UNION what the tool itself accesses.
That union is load-bearing: the measured attack calls export_records directly
with no prior lookup, so a payload-only rule would allow it.
"""
from dataclasses import dataclass, field

from kernel.packs import registered_email


@dataclass
class Decision:
    verdict: str                       # allow | need_approval | deny
    rule_id: str
    reasons: list[str] = field(default_factory=list)
    labels_in: list[str] = field(default_factory=list)
    contributing: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)


def _destinations(args, spec):
    key = spec.get("destination_arg")
    raw = str(args.get(key, "")) if key else ""
    return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]


def _internal(addr, pack):
    return any(addr.lower().endswith("@" + d.lower())
               for d in pack.get("internal_domains", []))


def evaluate(*, pack, tool, args, contributing, context_trust, record_count):
    spec = pack["tool_index"].get(tool)
    matched = []

    # Unknown tool: fail closed. No rule covers it, so it does not run.
    if spec is None:
        return Decision("deny", "R_unknown_tool", ["tool_not_in_pack"],
                        [], [], ["R_unknown_tool"])

    ids = [h.id for h in contributing]
    labels = sorted({h.sensitivity.upper() for h in contributing})
    if context_trust == "untrusted":
        labels.append("UNTRUSTED")
    if spec.get("accesses") == "private" and "PRIVATE" not in labels:
        labels.append("PRIVATE")

    # R1 — not egress
    matched.append("R1_not_egress")
    if not spec.get("egress"):
        return Decision("allow", "R1_not_egress", ["tool_is_not_egress"],
                        labels, ids, matched)

    payload_private = [h for h in contributing if h.sensitivity == "private"]
    tool_private = spec.get("accesses") == "private"
    has_private = bool(payload_private) or tool_private

    # R0 — volume ceiling, overrides every permissive rule below.
    #
    # Trusted jobs only. In an untrusted job the call is already heading for
    # R5's deny, and a volume hit there would *downgrade* a hard block into a
    # 120-second approval hold — which is exactly what would happen on stage
    # the moment anyone edits volume_threshold below the directory size.
    # Deny beats approval: an untrusted job never gets to ask a human.
    matched.append("R0_volume")
    if (has_private and context_trust == "trusted"
            and record_count > pack["volume_threshold"]):
        return Decision("need_approval", "R0_volume_exceeds_threshold",
                        ["volume_exceeds_threshold"], labels, ids, matched)

    # R2 — nothing private involved
    matched.append("R2_no_private")
    if not has_private:
        return Decision("allow", "R2_no_private", ["no_private_data_in_payload"],
                        labels, ids, matched)

    dests = _destinations(args, spec)

    # R3 — destination is internal
    matched.append("R3_internal_destination")
    if dests and all(_internal(d, pack) for d in dests):
        if context_trust == "untrusted":
            return Decision("need_approval", "R3_internal_but_untrusted_job",
                            ["internal_destination", "untrusted_context"],
                            labels, ids, matched)
        return Decision("allow", "R3_internal_destination",
                        ["internal_destination"], labels, ids, matched)

    # R4 — data subject binding: one person's data, to that person's address.
    # A tool with scope 'many' can never qualify.
    matched.append("R4_subject_binding")
    subjects = {h.subject for h in payload_private if h.subject}
    if spec.get("scope") != "many" and len(subjects) == 1 and dests:
        expected = registered_email(next(iter(subjects)))
        if expected and all(d.lower() == expected.lower() for d in dests):
            return Decision("allow", "R4_subject_binding",
                            ["destination_is_data_subject"], labels, ids, matched)

    # R5 — private data leaving a job that touched untrusted content
    matched.append("R5_untrusted_context")
    if context_trust == "untrusted":
        return Decision("deny", "R5_private_to_external_in_untrusted_job",
                        ["private_data", "external_destination", "untrusted_context"],
                        labels, ids, matched)

    # R6 — trusted job, external destination: a human decides
    matched.append("R6_trusted_external")
    return Decision("need_approval", "R6_trusted_external",
                    ["private_data", "external_destination"], labels, ids, matched)
