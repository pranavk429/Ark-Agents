"""Gemini via stdlib urllib. No SDK, no extra dependency."""
import json
import os
import time
import urllib.error
import urllib.request

ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
MODEL = os.environ.get("TOWER_MODEL", "gemini-2.5-flash")
TIMEOUT_S = 45


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def complete(system: str, contents: list, tools: list | None = None) -> dict:
    """Returns {'calls': [{'name','args'}], 'text': str}. Raises on failure."""
    key = os.environ["GEMINI_API_KEY"]
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents}
    if tools:
        body["tools"] = [{"functionDeclarations": tools}]

    last = None
    for attempt in range(4):                       # free tier is ~10 rpm
        req = urllib.request.Request(
            f"{ROOT}/{MODEL}:generateContent?key={key}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                data = json.loads(r.read().decode())
            calls, text = [], ""
            for cand in data.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    if "functionCall" in part:
                        fc = part["functionCall"]
                        calls.append({"name": fc.get("name"), "args": fc.get("args") or {}})
                    elif "text" in part:
                        text += part["text"]
            return {"calls": calls, "text": text}
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 and attempt < 3:
                time.sleep(20 + attempt * 10)
                continue
            raise
        except Exception as e:
            last = e
            if attempt < 3:
                time.sleep(5)
                continue
            raise
    raise last


def tool_declarations(pack) -> list:
    out = []
    for t in pack["tools"]:
        props = {k: {"type": "string"} for k in (t.get("args") or {})}
        out.append({"name": t["name"], "description": t["description"],
                    "parameters": {"type": "object", "properties": props,
                                   "required": list(props)}})
    return out
