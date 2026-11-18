"""Agent 11 Quality Assurance Director: deterministic checks + independent creative review (SOP 3, phase 6)."""
from __future__ import annotations

import json

from hermes.agents.common import HOUSE_RULES, Ctx
from hermes.agents.visual import REQUIRED
from hermes.agents.website import check_local
from hermes.models import QAReview

QA_SYSTEM = f"""You are the QA Director. You did not make any of this work. Judge whether the finished project actually matches the
strategy and brief — not merely whether files exist. Flag research weaknesses, brand inconsistency, generic design, misleading
statements, fabricated utility, impersonation, and compliance problems. Attribute each issue to the responsible agent.
{HOUSE_RULES}"""


def deterministic(ctx: Ctx) -> list[dict]:
    issues: list[dict] = []
    ws = ctx.ws

    def need(rel: str, agent: str) -> None:
        if not ws.exists(rel):
            issues.append({"agent": agent, "severity": "blocker", "problem": f"missing {rel}", "fix": "re-run task"})

    for rel, agent in [("strategy/market_research.md", "market"), ("strategy/candidate_scores.json", "market"),
                       ("strategy/creative_brief.md", "creative"), ("brand/brand_guide.md", "brand"),
                       ("social/profile.json", "social"), ("social/ten_posts.md", "social")]:
        need(rel, agent)
    for r in REQUIRED:
        need(r.path, "visual")
    if ws.exists("website/source/index.html"):
        for p in check_local(ws.path("website/source")):
            issues.append({"agent": "website", "severity": "major", "problem": p, "fix": "regenerate copy / rebuild"})
    else:
        issues.append({"agent": "website", "severity": "blocker", "problem": "site not built", "fix": "build site"})
    if ws.exists("website/deployment.json"):
        v = ws.read_json("website/deployment.json").get("verification", {})
        if not v.get("ok"):
            issues.append({"agent": "website", "severity": "blocker", "problem": f"live verification failed: {v}", "fix": "redeploy"})
    if ws.exists("social/profile.json"):
        from hermes.agents.social import validate
        from hermes.models import SocialPackage

        for p in validate(SocialPackage.model_validate(ws.read_json("social/profile.json"))):
            issues.append({"agent": "social", "severity": "major", "problem": p, "fix": "rewrite post"})
    return issues


def review(ctx: Ctx) -> QAReview:
    ws = ctx.ws
    bundle = {}
    for rel in ["strategy/selected_candidate.json", "strategy/creative_brief.json", "brand/brand.json", "website/copy.json",
                "social/profile.json", "launch/metadata.json"]:
        if ws.exists(rel):
            bundle[rel] = ws.read_json(rel)
    images = [ws.path(r).read_bytes() for r in ("brand/token_icon.png", "brand/x_banner.png", "website/assets/hero.png")
              if ws.exists(r)]
    return ctx.llm.structured(
        QA_SYSTEM,
        "Images attached in order: token icon, X banner, website hero (where present).\n\n"
        + json.dumps(bundle, indent=1, ensure_ascii=False)[:90000],
        QAReview, images=images,
    )


def audit_md(det: list[dict], rv: QAReview | None, passed: bool) -> str:
    out = ["# QA audit", "", f"**Result: {'PASS' if passed else 'FAIL'}**", ""]
    out.append("## Deterministic checks")
    out += [f"- [{i['severity']}] ({i['agent']}) {i['problem']}" for i in det] or ["- all passed"]
    if rv:
        out += ["", "## Creative / strategy review", "", rv.summary, "",
                f"Matches strategy: {'yes' if rv.matches_strategy else 'no'}", ""]
        out += [f"- [{i.severity}] ({i.agent}) {i.problem} → {i.fix}" for i in rv.issues] or ["- no issues"]
    return "\n".join(out) + "\n"
