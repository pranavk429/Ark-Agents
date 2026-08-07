"""Data handles. A tool never returns raw data to the agent — it returns a
handle id plus a preview. The kernel keeps the value and its labels."""
import itertools
import re
from dataclasses import dataclass, field

MIN_MATCH = 12  # shorter overlaps are coincidence, not provenance
_counter = itertools.count(1)


@dataclass
class Handle:
    id: str
    value: str
    preview: str
    source: str
    trust: str          # trusted | untrusted
    sensitivity: str    # public | internal | private
    subject: str | None
    step: int
    records: int = 1


class HandleStore:
    """In-memory, per-job. Lives for the process; a restart clears it.
    That is acceptable for a demo — do not run uvicorn with --reload."""

    def __init__(self):
        self._by_job: dict[str, dict[str, Handle]] = {}

    def put(self, job_id, *, value, source, trust, sensitivity, subject, step, records=1):
        text = value if isinstance(value, str) else str(value)
        h = Handle(
            id=f"h_{next(_counter):04d}", value=text,
            preview=(text[:80] + "…") if len(text) > 80 else text,
            source=source, trust=trust, sensitivity=sensitivity,
            subject=subject, step=step, records=records,
        )
        self._by_job.setdefault(job_id, {})[h.id] = h
        return h

    def get(self, job_id, handle_id):
        return self._by_job.get(job_id, {}).get(handle_id)

    def all(self, job_id):
        return list(self._by_job.get(job_id, {}).values())

    def contributing(self, job_id, args: dict) -> list[Handle]:
        """Which handles flowed into this payload.

        Two mechanisms, both needed:
          1. explicit @h_xxxx references (what we instruct the agent to use)
          2. substring match on the handle's value (what actually happens when
             the model pastes the text instead)
        """
        blob = " ".join(str(v) for v in args.values())
        refs = set(re.findall(r"@(h_\d{4})", blob))
        out = []
        for h in self.all(job_id):
            if h.id in refs:
                out.append(h)
                continue
            probe = h.value[:60].strip()
            if len(probe) >= MIN_MATCH and probe in blob:
                out.append(h)
        return out


STORE = HandleStore()
