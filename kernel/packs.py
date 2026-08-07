import json
from functools import lru_cache
from pathlib import Path

import yaml

BASE = Path(__file__).parent.parent
_CACHE: dict[str, tuple[float, dict]] = {}


def load(name: str) -> dict:
    """Reload whenever the YAML changes on disk.

    NOT lru_cache. Editing packs/support.yaml and seeing the verdict change on
    the next run — with no restart — is a stage moment: live proof this is a
    real policy engine and not a hardcoded demo. A cache would silently make
    that claim false.
    """
    path = BASE / "packs" / f"{name}.yaml"
    mtime = path.stat().st_mtime
    cached = _CACHE.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path) as f:
        pack = yaml.safe_load(f)
    pack["tool_index"] = {t["name"]: t for t in pack["tools"]}
    _CACHE[name] = (mtime, pack)
    return pack


@lru_cache
def directory() -> dict:
    with open(BASE / "seed" / "customers.json") as f:
        return json.load(f)


def registered_email(subject: str) -> str | None:
    rec = directory().get(subject)
    return rec["email"] if rec else None


def tool_spec(pack_name: str, tool: str) -> dict | None:
    return load(pack_name)["tool_index"].get(tool)
