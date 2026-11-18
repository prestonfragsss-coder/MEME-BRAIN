from __future__ import annotations

from dataclasses import dataclass

from hermes.config import Settings
from hermes.llm import LLM
from hermes.workspace import Workspace

HOUSE_RULES = """House rules (non-negotiable):
- Never invent engagement numbers, token volumes, prices, holder counts, dates or sources. If you did not see it, say "not verified".
- Never claim official affiliation, partnership, endorsement or technology that does not exist.
- No financial promises, price predictions, return multiples or investment framing.
- No impersonation of real people, brands or existing tokens.
- Avoid generic crypto aesthetics (random neon, meaningless futurism, gradient soup) unless the concept truly calls for it."""


@dataclass
class Ctx:
    ws: Workspace
    llm: LLM
    settings: Settings


class Blocked(Exception):
    """Raised when a task needs an operator/external action. Message = the exact action needed."""
