"""Mock tool implementations. These are the ONLY side-effecting functions and
they are reachable only from kernel/gateway.py."""
import json
from pathlib import Path

from kernel.packs import directory

BASE = Path(__file__).parent.parent


def read_ticket(args):
    tid = str(args.get("ticket_id", "")).strip()
    name = "injected" if tid in ("4478", "injected") else "clean"
    return (BASE / "seed" / "tickets" / f"{name}.txt").read_text()


def lookup_customer(args):
    key = f"customer:{str(args.get('customer_id','')).strip()}"
    rec = directory().get(key)
    return json.dumps(rec) if rec else "no such customer"


def search_kb(args):
    return f"KB article: standard policy for '{args.get('query','')}' is a 14-day window."


def send_email(args):
    return f"email delivered to {args.get('to')}"


def export_records(args):
    n = 1 if str(args.get("scope", "")).isdigit() else len(directory())
    return f"exported {n} records to {args.get('destination')}"


REGISTRY = {
    "read_ticket": read_ticket,
    "lookup_customer": lookup_customer,
    "search_kb": search_kb,
    "send_email": send_email,
    "export_records": export_records,
}


def record_count(pack, tool, args) -> int:
    """How many people's data this call touches. Drives the volume ceiling."""
    spec = pack["tool_index"].get(tool, {})
    if spec.get("scope") == "many":
        return 1 if str(args.get("scope", "")).isdigit() else len(directory())
    return 1
