"""Agent 03 E-commerce Creative Strategist + Agent 04 Brand Architect (SOP 3, phase 3)."""
from __future__ import annotations

import json

from hermes.agents.common import HOUSE_RULES, Ctx
from hermes.agents.research import dexscreener_solana
from hermes.models import BrandSystem, Candidate, CreativeBrief, NameCheck
from hermes.safety import lint_public_copy

CREATIVE_SYSTEM = f"""You are the creative director of a top-performing direct-to-consumer brand studio, now applying that
methodology to an internet-culture token brand. Website, token image, X account, banner and posts must feel like ONE brand.
The goal is not to look expensive; it is to make an original concept feel intentional, memorable and culturally relevant.
{HOUSE_RULES}"""

BRAND_SYSTEM = f"""You are the Brand Architect. Produce a complete, internally consistent brand system from the approved creative brief.
Names must be original, pronounceable, and must not copy an existing token, brand, person or trademark. Ticker: 2-10 uppercase
letters/digits. Fonts must be real Google Fonts families. Colours as #RRGGBB with sufficient text/background contrast.
{HOUSE_RULES}"""


def creative_brief(ctx: Ctx, cand: Candidate, operator_prefs: dict[str, str], reference: str) -> CreativeBrief:
    return ctx.llm.structured(
        CREATIVE_SYSTEM,
        f"Selected opportunity:\n{cand.model_dump_json(indent=2)}\n\nOperator preferences: {json.dumps(operator_prefs)}\n"
        f"Reference website analysis (structure/pacing inspiration only):\n{reference[:5000] or 'none'}\n\n"
        "Write the unified creative brief every downstream agent will follow.",
        CreativeBrief,
    )


def brand_system(ctx: Ctx, cand: Candidate, brief: CreativeBrief, feedback: str = "") -> BrandSystem:
    fb = f"\n\nPrevious attempt was rejected: {feedback}\nFix these problems." if feedback else ""
    return ctx.llm.structured(
        BRAND_SYSTEM,
        f"Opportunity:\n{cand.model_dump_json(indent=2)}\n\nCreative brief:\n{brief.model_dump_json(indent=2)}{fb}",
        BrandSystem,
    )


def name_check(ctx: Ctx, brand: BrandSystem) -> NameCheck:
    lookups: dict[str, object] = {}
    for q in (brand.ticker, brand.name):
        try:
            lookups[q] = dexscreener_solana(q, limit=10)
        except Exception as e:  # noqa: BLE001
            lookups[q] = f"lookup failed: {e.__class__.__name__}"
    web = ctx.llm.research(
        "You check proposed brand names for conflicts. Report only what you actually find.",
        f"Search for existing crypto tokens, companies, trademarks, public figures or popular accounts named '{brand.name}' "
        f"or using ticker ${brand.ticker}. Report conflicts with URLs.",
        max_searches=5,
    )
    lint = lint_public_copy(" ".join([brand.positioning, brand.story, brand.token_description]), "brand")
    result = ctx.llm.structured(
        BRAND_SYSTEM,
        f"Proposed: {brand.name} (${brand.ticker}).\nLive Solana token matches (DexScreener):\n{json.dumps(lookups, indent=2)[:6000]}\n\n"
        f"Web check:\n{web.text[:8000]}\n\nCopy lint findings: {[f.model_dump() for f in lint]}\n\n"
        "Decide: passed=false if an exact or confusingly similar Solana token with real activity exists, if it impersonates a "
        "person/brand, or if lint findings exist.",
        NameCheck,
    )
    if lint:
        result.passed = False
    return result


def brand_guide_md(b: BrandSystem, brief: CreativeBrief) -> str:
    p = b.palette
    return f"""# {b.name} (${b.ticker}) — Brand guide

**Positioning:** {b.positioning}

## Story
{b.story}

## Voice
{b.voice}

## Palette
| Role | Hex |
|---|---|
| Primary | `{p.primary}` |
| Secondary | `{p.secondary}` |
| Accent | `{p.accent}` |
| Background | `{p.background}` |
| Text | `{p.text}` |

## Typography
Display: **{b.display_font}** · Body: **{b.body_font}**

## Logo / token icon
{b.logo_concept}

## Mascot / character
{b.mascot_direction or 'n/a'}

## Website direction ({brief.website_experience})
{b.website_direction}

## X positioning
{b.x_positioning}

## Banner
{b.banner_concept}

## Image style guide
{b.image_style_guide}

## Social templates
{chr(10).join('- ' + t for t in b.social_templates)}

## Consistency rules
{chr(10).join('- ' + r for r in brief.consistency_rules)}

## Avoid
{chr(10).join('- ' + r for r in brief.avoid)}

## Launch-platform description
> {b.token_description}
"""
