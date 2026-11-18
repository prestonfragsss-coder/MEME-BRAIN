"""Parse operator messages into BuildRequests (SOP section 2 & 8)."""
from __future__ import annotations

import re

from hermes.models import BuildRequest, Mode

_URL = re.compile(r"https?://[^\s|]+", re.I)


def parse_build(text: str) -> BuildRequest:
    body = re.sub(r"^/build(@\w+)?\s*", "", text.strip(), flags=re.I).strip()
    if not body or body.lower() == "auto":
        return BuildRequest(mode=Mode.AUTO, raw=body or "auto")

    urls = _URL.findall(body)
    parts = [p.strip() for p in body.split("|") if p.strip()]
    prefs: dict[str, str] = {}
    notes: list[str] = []
    for p in parts:
        if _URL.fullmatch(p):
            continue
        m = re.match(r"^([a-zA-Z _-]{2,20}):\s*(.+)$", p)
        if m:
            prefs[m.group(1).strip().lower()] = m.group(2).strip()
        else:
            notes.append(_URL.sub("", p).strip())
    notes = [n for n in notes if n]

    if urls and not prefs and not notes:
        mode = Mode.URL
    elif urls:
        mode = Mode.HYBRID
    else:
        mode = Mode.GUIDED
    return BuildRequest(mode=mode, raw=body, urls=urls, preferences=prefs, notes=notes)


def wants_research(req: BuildRequest) -> bool:
    if req.mode in (Mode.AUTO, Mode.HYBRID):
        return True
    joined = " ".join(req.notes).lower() + " " + " ".join(req.preferences.values()).lower()
    return any(k in joined for k in ("trend", "meta", "surprise", "research", "auto"))
