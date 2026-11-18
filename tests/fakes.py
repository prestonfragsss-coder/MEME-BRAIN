"""Deterministic stand-ins for Claude, the image API and hosting, so the pipeline is testable offline."""
from __future__ import annotations

import io

from PIL import Image

from hermes.llm import Research
from hermes.models import (BrandSystem, Candidate, CandidateSet, CreativeBrief, CriterionScores, ImageReview, NameCheck,
                           Palette, Post, QAReview, SiteCopy, SiteSection, SocialPackage, Source, VisualSpec, AssetPrompt)
from hermes.agents.visual import REQUIRED

URLS = [f"https://news.example.org/story-{i}" for i in range(12)]


def _cand(i: int, strong: bool) -> Candidate:
    return Candidate(
        id=f"c{i}", title=f"Concept {i}", what_is_getting_attention="x", why_people_care="y", trajectory="accelerating",
        emotional_driver="joy", three_second_read="a crab in a tuxedo", visual_identity="tuxedo crab", token_concept="mascot",
        content_potential="daily comics", market_crowding="low", differentiation="hand-drawn", authenticity_notes="organic",
        existing_competitors=[], confidence="high", classification="character_mascot", positioning="absurd luxury crab",
        sources=[Source(url=URLS[2 * i], observed_at="2026-11-17", evidence="post"),
                 Source(url=URLS[2 * i + 1], observed_at="2026-11-17", evidence="post"),
                 Source(url="https://fabricated.example/never-retrieved", observed_at="2026-11-17", evidence="?")],
    )


class FakeLLM:
    def __init__(self, scores_high: bool = True, qa_pass: bool = True):
        self.scores_high, self.qa_pass = scores_high, qa_pass
        self.calls: list[str] = []

    def research(self, system, prompt, *, fetch=False, max_searches=12):
        self.calls.append("research")
        return Research(text="research notes", source_urls=set(URLS))

    def structured(self, system, prompt, schema, *, images=None, effort="high"):
        self.calls.append(schema.__name__)
        if schema is CandidateSet:
            return CandidateSet(researched_at="2026-11-18", research_summary="s", candidates=[_cand(i, True) for i in range(5)])
        if schema is CriterionScores:
            v = 9.0 if self.scores_high else 6.0
            return CriterionScores(attention_momentum=v, originality=v, comprehensibility=v, visual_meme_potential=v,
                                   cultural_relevance=v, content_longevity=v, execution_feasibility=v, brand_expansion=v,
                                   rationale="r")
        if schema is CreativeBrief:
            return CreativeBrief(candidate_id="c0", target_audience="a", emotional_hook="h", brand_personality="p",
                                 three_second_impression="t", visual_positioning="v", cultural_relevance="c", differentiation="d",
                                 storytelling="s", website_experience="playful_meme", social_strategy="ss",
                                 consistency_rules=["same crab"], avoid=["neon"])
        if schema is BrandSystem:
            return BrandSystem(name="Tux Crab", ticker="TUXC", positioning="A crab who dresses for dinner.", story="Once...",
                               voice="dry", palette=Palette(primary="#111111", secondary="#C9A227", accent="#E4572E",
                                                            background="#F7F3EA", text="#1B1B1B"),
                               display_font="Playfair Display", body_font="Inter", logo_concept="crab bowtie",
                               mascot_direction="tux crab", website_direction="playful", x_positioning="x",
                               banner_concept="b", image_style_guide="ink", social_templates=["t1"],
                               token_description="A community meme about a crab who always overdresses.")
        if schema is NameCheck:
            return NameCheck(conflicts=[], impersonation_risk="none", notes="clear", passed=True)
        if schema is VisualSpec:
            return VisualSpec(character_sheet="crab", style_rules=["ink"], negative_rules=["text"],
                              prompts=[AssetPrompt(key=r.key, prompt=f"draw {r.key}") for r in REQUIRED])
        if schema is ImageReview:
            return ImageReview(passed=True, defects=[])
        if schema is SiteCopy:
            return SiteCopy(title="Tux Crab", meta_description="A crab who overdresses.", hero_headline="Dress for dinner",
                            hero_subline="Always.", footer_disclaimer="Community meme token. No intrinsic value or expectation of financial return.",
                            sections=[SiteSection(id="story", heading="Story", body="He wore a tux.", image_key="support_1"),
                                      SiteSection(id="crew", heading="Crew", body="Join in.", image_key="support_2")])
        if schema is SocialPackage:
            return SocialPackage(display_name="Tux Crab", handle_candidates=["tuxcrab", "tux_crab_sol"], bio="Dressed for dinner.",
                                 pinned_post="Hello.", sequencing="daily",
                                 posts=[Post(n=i, purpose="p", text=f"post {i}", image_key=f"post_{i}", timing="d1") for i in range(1, 11)])
        if schema is QAReview:
            return QAReview(matches_strategy=self.qa_pass, issues=[], summary="ok")
        raise AssertionError(f"unexpected schema {schema}")


class FakeImageGen:
    def __init__(self):
        self.n = 0

    def generate(self, prompt: str, size: str) -> bytes:
        self.n += 1
        w, h = (int(x) for x in size.split("x"))
        buf = io.BytesIO()
        Image.new("RGB", (w, h), (200, 50, 50)).save(buf, "PNG")
        return buf.getvalue()


def fake_deploy(ctx, src, site_name):
    assert (src / "index.html").exists()
    info = {"provider": "fake", "site_id": "s1", "url": "https://tux-crab.example.app", "deploy_id": "d1", "state": "ready",
            "verification": {"ok": True, "index": 200, "https": True}}
    ctx.ws.write_json("website/deployment.json", info)
    return info
