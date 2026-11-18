"""Guardrails shared by every agent.

* secret detection: refuse to persist/log anything that looks like a seed phrase or private key
* claims linting: block guaranteed-return / fake-affiliation / placeholder language in public copy
* address validation: public Solana addresses only
"""
from __future__ import annotations

import re

from pydantic import BaseModel

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_RE = re.compile(rf"[{_B58}]+")


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        idx = _B58.find(ch)
        if idx < 0:
            raise ValueError("invalid base58 character")
        n = n * 58 + idx
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + raw


def is_solana_public_address(s: str) -> bool:
    s = s.strip()
    if not 32 <= len(s) <= 44 or not _B58_RE.fullmatch(s):
        return False
    try:
        return len(b58decode(s)) == 32
    except ValueError:
        return False


class SecretDetected(Exception):
    pass


_HEX_KEY = re.compile(r"\b(?:0x)?[0-9a-fA-F]{64}\b")
_BYTE_ARRAY_KEY = re.compile(r"\[\s*(?:\d{1,3}\s*,\s*){63}\d{1,3}\s*\]")
_MNEMONIC_HINT = re.compile(r"\b(seed|recovery|secret|mnemonic|private)\s*(phrase|key|words?)\b", re.I)


def _looks_like_mnemonic(text: str) -> bool:
    # 12/15/18/21/24 consecutive short lowercase words on their own is the BIP39 shape.
    for line in re.split(r"[\n;]", text):
        words = line.strip().split()
        if len(words) in (12, 15, 18, 21, 24) and all(re.fullmatch(r"[a-z]{3,8}", w) for w in words):
            return True
    return False


def find_secret(text: str) -> str | None:
    """Return a reason string if text looks like it contains wallet secret material."""
    if _BYTE_ARRAY_KEY.search(text):
        return "byte-array private key"
    if _looks_like_mnemonic(text):
        return "mnemonic-shaped word list"
    for tok in _B58_RE.findall(text):
        if 80 <= len(tok) <= 90:
            try:
                if len(b58decode(tok)) == 64:
                    return "base58 64-byte keypair"
            except ValueError:
                pass
    if _HEX_KEY.search(text) and _MNEMONIC_HINT.search(text):
        return "hex private key"
    return None


def assert_no_secrets(text: str, where: str = "") -> None:
    reason = find_secret(text)
    if reason:
        raise SecretDetected(f"refusing to persist {reason}{' in ' + where if where else ''}")


# ---------- public copy linting ----------
_BANNED = [
    (r"\bguarantee[sd]?\b.*\b(return|profit|gain|moon|x\b)", "guaranteed-return claim"),
    (r"\b(risk[- ]?free|can'?t lose|no risk)\b", "risk-free claim"),
    (r"\b\d{2,5}\s?x\b(?!\s*(account|handle|profile|post))", "price-multiple promise"),
    (r"\b(to the moon|next 100x|1000x|get rich)\b", "financial hype promise"),
    (r"\bofficial(ly)?\b.*\b(partner|partnership|endorse|affiliat)", "claimed official affiliation"),
    (r"\b(endorsed by|backed by|in partnership with)\b", "claimed endorsement/partnership"),
    (r"\b(investment|passive income|dividend|yield|apy|apr)\b", "investment framing"),
    (r"\blorem ipsum\b|\bTODO\b|\bTBD\b|\bplaceholder\b|\[insert|\{\{|XXX", "placeholder text"),
    (r"\b(roadmap)\b.*\bQ[1-4]\b", "dated roadmap commitment"),
]
_BANNED_RE = [(re.compile(p, re.I), why) for p, why in _BANNED]


class LintFinding(BaseModel):
    where: str
    reason: str
    excerpt: str


def lint_public_copy(text: str, where: str) -> list[LintFinding]:
    out: list[LintFinding] = []
    for rx, why in _BANNED_RE:
        m = rx.search(text)
        if m:
            s = max(0, m.start() - 30)
            out.append(LintFinding(where=where, reason=why, excerpt=text[s : m.end() + 30]))
    return out
