"""Agent 01 Market Intelligence Director + Agent 02 Cultural Meta Strategist + scoring (SOP 3, 4)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from hermes import scoring
from hermes.agents.common import HOUSE_RULES, Ctx
from hermes.models import BuildRequest, CandidateSet, CriterionScores, Mode

INTEL_SYSTEM = f"""You are the Market Intelligence Director of a creative studio that builds Solana meme/culture token brands.
Your only job is finding opportunities with evidence, before anything is created.
Investigate: new Solana / Pump.fun launches and trending categories, X discussions, Google Trends and news,
Reddit and subcultures, TikTok/Instagram formats, AI/tech/robotics/gaming/animals/celebrities/pop culture, new slang and visual formats.
Separate organic attention from bots, coordinated shilling, paid engagement and wash volume. Prefer opportunities that are rising but
not yet saturated. A popular topic is not automatically a viable project.
{HOUSE_RULES}"""

STRATEGIST_SYSTEM = f"""You are the Cultural Meta Strategist. Classify each opportunity and choose its most authentic positioning.
Do not force utility into something that works as a pure meme, and do not wrap a real technology in a forced meme.
{HOUSE_RULES}"""

SCORER_SYSTEM = f"""You are an independent investment-committee style reviewer for a creative studio. Score ONE candidate on each
criterion from 0-10 using only the evidence provided. Be harsh: 8+ means genuinely exceptional on that axis.
These are creative decision-support scores, NOT price predictions. List any legal, ethical, impersonation, tragedy-exploitation,
minor-related, or authenticity concern in blocking_concerns.
{HOUSE_RULES}"""


def _request_brief(req: BuildRequest) -> str:
    lines = [f"Mode: {req.mode.value}", f"Raw instruction: {req.raw}"]
    if req.urls:
        lines.append("Reference URLs (creative/structural reference only, never clone branding): " + ", ".join(req.urls))
    for k, v in req.preferences.items():
        lines.append(f"Operator preference - {k}: {v}")
    for n in req.notes:
        lines.append(f"Operator note: {n}")
    return "\n".join(lines)


def dexscreener_solana(query: str, limit: int = 8) -> list[dict]:
    """Real existing-token lookup (public API). Returns [] on failure; callers must say 'lookup failed', not 'none exist'."""
    r = httpx.get("https://api.dexscreener.com/latest/dex/search", params={"q": query}, timeout=20)
    r.raise_for_status()
    out, seen = [], set()
    for p in r.json().get("pairs") or []:
        if p.get("chainId") != "solana":
            continue
        bt = p.get("baseToken") or {}
        key = bt.get("address")
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": bt.get("name"), "symbol": bt.get("symbol"), "address": key, "url": p.get("url"),
                    "pairCreatedAt": p.get("pairCreatedAt")})
        if len(out) >= limit:
            break
    return out


def discover(ctx: Ctx, req: BuildRequest) -> CandidateSet:
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    focus = _request_brief(req)
    reference = ""
    if req.urls:
        ref = ctx.llm.research(
            "You are a senior creative director auditing a website as design reference.",
            f"Fetch and analyse {req.urls[0]}. Describe its visual language, page hierarchy, layout patterns, motion, typography, "
            "conversion flow, imagery and overall presentation. Note any protected branding that must NOT be reused.",
            fetch=True, max_searches=2,
        )
        ctx.ws.write_text("strategy/reference_analysis.md", f"# Reference analysis: {req.urls[0]}\n\n{ref.text}\n")
        reference = ref.text[:6000]

    guided = req.mode in (Mode.GUIDED, Mode.URL)
    task = (
        "Develop five distinct concept candidates that honour the operator's direction, each grounded in current, verifiable cultural evidence."
        if guided else
        "Find the five strongest current opportunities in the market right now."
    )
    ref_block = ("Reference site analysis:\n" + reference) if reference else ""
    research = ctx.llm.research(
        INTEL_SYSTEM,
        f"Current time: {now}\n{focus}\n\n{ref_block}\n\n"
        f"{task}\nFor each: what is getting attention, why, whether attention is accelerating or declining, the emotional driver, whether "
        "it reads in three seconds, its visual identity, whether it supports a distinctive token concept and ongoing content, how crowded "
        "the existing Solana token field is, what would make our execution different, organic-vs-manufactured signals, existing competitor "
        "tokens, and at least two sources with URL, date and what each shows. Search broadly before concluding.",
    )
    ctx.ws.write_text("strategy/market_research_raw.md", research.text)
    ctx.ws.write_json("strategy/source_urls.json", sorted(research.source_urls))

    cands = ctx.llm.structured(
        STRATEGIST_SYSTEM,
        f"Research time: {now}\nOperator request:\n{focus}\n\nResearch notes:\n{research.text[:60000]}\n\n"
        "Turn this into exactly five candidates (ids c1..c5). Only cite sources whose URLs appear in the research notes. "
        "Classify each and write its most authentic positioning.",
        CandidateSet,
    )
    return _verify_sources(cands, research.source_urls)


def _verify_sources(cs: CandidateSet, seen: set[str]) -> CandidateSet:
    """Drop any cited source the research step never actually retrieved; downgrade weakly evidenced candidates."""
    norm = {u.rstrip("/") for u in seen}
    for c in cs.candidates:
        before = len(c.sources)
        c.sources = [s for s in c.sources if s.url.rstrip("/") in norm]
        dropped = before - len(c.sources)
        if dropped:
            c.authenticity_notes += f" [verifier: {dropped} cited source(s) removed - not found in retrieved results]"
        if len(c.sources) < 2:
            c.confidence = "low"
    return cs


def score_all(ctx: Ctx, cs: CandidateSet) -> list[dict]:
    rows = []
    for c in cs.candidates:
        competitors: list[dict] | str
        try:
            competitors = dexscreener_solana(c.title)
        except Exception as e:  # noqa: BLE001
            competitors = f"lookup failed: {e.__class__.__name__}"
        s = ctx.llm.structured(
            SCORER_SYSTEM,
            f"Candidate:\n{c.model_dump_json(indent=2)}\n\nExisting Solana tokens matching the title (live DexScreener lookup):\n"
            f"{json.dumps(competitors, indent=2)[:4000]}\n\nWeights for context: {scoring.WEIGHTS}",
            CriterionScores,
        )
        if len(c.sources) < 2:
            s.blocking_concerns.append("fewer than two verified sources")
        ok, why = scoring.eligible(s, ctx.settings.score_threshold)
        rows.append({"candidate_id": c.id, "title": c.title, "total": scoring.total(s), "eligible": ok, "reason": why,
                     "scores": s.model_dump(), "dexscreener_matches": competitors})
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows


def write_research_md(ctx: Ctx, cs: CandidateSet, rows: list[dict]) -> None:
    by_id = {r["candidate_id"]: r for r in rows}
    out = [f"# Market research\n\nResearched at: {cs.researched_at}\n\n{cs.research_summary}\n"]
    for c in cs.candidates:
        r = by_id.get(c.id, {})
        out.append(f"## {c.id}: {c.title}  —  score {r.get('total', '?')} ({r.get('reason', '')})\n")
        out.append(f"- **Classification:** {c.classification}  |  **Confidence:** {c.confidence}  |  **Trajectory:** {c.trajectory}")
        out.append(f"- **Attention:** {c.what_is_getting_attention}\n- **Why:** {c.why_people_care}\n- **Emotion:** {c.emotional_driver}")
        out.append(f"- **3-second read:** {c.three_second_read}\n- **Visual identity:** {c.visual_identity}")
        out.append(f"- **Token concept:** {c.token_concept}\n- **Positioning:** {c.positioning}")
        out.append(f"- **Crowding:** {c.market_crowding}\n- **Differentiation:** {c.differentiation}")
        out.append(f"- **Authenticity:** {c.authenticity_notes}")
        out.append(f"- **Competitors:** {', '.join(c.existing_competitors) or 'none identified'}")
        out.append("- **Sources:**")
        out += [f"  - [{s.title or s.url}]({s.url}) ({s.observed_at}) — {s.evidence}" for s in c.sources]
        out.append("")
    ctx.ws.write_text("strategy/market_research.md", "\n".join(out))
