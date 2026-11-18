"""Agent 07 Social Media & Content Director (SOP 3)."""
from __future__ import annotations

from hermes.agents.common import HOUSE_RULES, Ctx
from hermes.models import BrandSystem, CreativeBrief, SocialPackage
from hermes.safety import LintFinding, lint_public_copy

PURPOSES = [
    "Brand introduction", "Core narrative", "Character or concept reveal", "Original meme", "Cultural reference",
    "Community invitation", "Visual storytelling", "Project explanation", "Launch announcement draft",
    "Post-launch community engagement",
]

SOCIAL_SYSTEM = f"""You are the Social Media & Content Director. Write in the brand voice; every post must have a distinct job.
No fake testimonials, fabricated partnerships, engagement bait promising rewards, return claims or price talk. Do not put a contract
address in any post (it does not exist yet); the launch post must say the CA will only be posted from this account after launch.
Posts must be <= 280 characters. Handles: 4-15 chars, letters/digits/underscore.
{HOUSE_RULES}"""


def social_package(ctx: Ctx, brand: BrandSystem, brief: CreativeBrief, site_url: str, feedback: str = "") -> SocialPackage:
    fb = f"\nRejected previous attempt: {feedback}" if feedback else ""
    pkg = ctx.llm.structured(
        SOCIAL_SYSTEM,
        f"Brand:\n{brand.model_dump_json(indent=2)}\n\nBrief:\n{brief.model_dump_json(indent=2)}\n\nWebsite: {site_url or 'pending deploy'}\n\n"
        "Write: display name, 5 handle candidates, bio, pinned post, and ten posts n=1..10 with these purposes in order: "
        + "; ".join(PURPOSES) + ". Set image_key to post_<n> for each post (launch post: launch_art; meme post: meme_template)."
        + fb,
        SocialPackage,
    )
    return pkg


def validate(pkg: SocialPackage) -> list[str]:
    problems: list[str] = []
    if len(pkg.posts) != 10:
        problems.append(f"expected 10 posts, got {len(pkg.posts)}")
    for p in pkg.posts:
        if len(p.text) > 280:
            problems.append(f"post {p.n} is {len(p.text)} chars")
    import re

    for h in pkg.handle_candidates:
        if not re.fullmatch(r"[A-Za-z0-9_]{4,15}", h.lstrip("@")):
            problems.append(f"invalid handle {h}")
    findings: list[LintFinding] = lint_public_copy(pkg.bio, "bio") + lint_public_copy(pkg.pinned_post, "pinned")
    for p in pkg.posts:
        findings += lint_public_copy(p.text, f"post {p.n}")
    problems += [f"{f.where}: {f.reason} ('{f.excerpt}')" for f in findings]
    return problems


def posts_md(pkg: SocialPackage, brand: BrandSystem) -> str:
    out = [f"# {brand.name} — X content (ready to publish)\n",
           "Status: **drafts** — not posted. Native X drafts require an authorised X session; publish from the project's own browser profile.\n",
           f"## Pinned\n\n{pkg.pinned_post}\n", f"## Sequencing\n\n{pkg.sequencing}\n"]
    for p in pkg.posts:
        out.append(f"## {p.n}. {p.purpose}  _(timing: {p.timing})_\n\n{p.text}\n\nImage: `{p.image_key or 'none'}`  ·  {len(p.text)}/280\n")
    return "\n".join(out)
