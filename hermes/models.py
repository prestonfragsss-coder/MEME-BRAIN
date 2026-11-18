"""Shared data contracts between agents. Every agent reads/writes these via the workspace."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Mode(str, Enum):
    URL = "url"            # Mode A
    GUIDED = "guided"      # Mode B
    AUTO = "auto"          # Mode C
    HYBRID = "hybrid"      # Mode D


class BuildRequest(BaseModel):
    mode: Mode
    raw: str
    urls: list[str] = []
    preferences: dict[str, str] = {}
    notes: list[str] = []


# ---------- Agent 01 / 02 ----------
class Source(BaseModel):
    url: str
    title: str = ""
    observed_at: str = Field(description="ISO timestamp or date the evidence was observed/published, as stated by the source")
    evidence: str = Field(description="What this source shows, quoted or paraphrased. No invented numbers.")


class Candidate(BaseModel):
    id: str
    title: str
    what_is_getting_attention: str
    why_people_care: str
    trajectory: Literal["accelerating", "steady", "declining", "unclear"]
    emotional_driver: str
    three_second_read: str
    visual_identity: str
    token_concept: str
    content_potential: str
    market_crowding: str
    differentiation: str
    authenticity_notes: str = Field(description="Signals of organic vs bot/paid attention, and what could not be verified")
    existing_competitors: list[str] = []
    sources: list[Source]
    confidence: Literal["low", "medium", "high"]
    classification: Literal[
        "pure_meme", "technology_utility", "ai_agent", "internet_culture", "news_cultural_reference",
        "character_mascot", "community", "experimental_digital_product", "hybrid_meme_tech",
    ] = "pure_meme"
    positioning: str = ""


class CandidateSet(BaseModel):
    researched_at: str
    candidates: list[Candidate]
    research_summary: str


class CriterionScores(BaseModel):
    """Each criterion 0-10; weighted to 100 in hermes.scoring."""
    attention_momentum: float = Field(ge=0, le=10)
    originality: float = Field(ge=0, le=10)
    comprehensibility: float = Field(ge=0, le=10)
    visual_meme_potential: float = Field(ge=0, le=10)
    cultural_relevance: float = Field(ge=0, le=10)
    content_longevity: float = Field(ge=0, le=10)
    execution_feasibility: float = Field(ge=0, le=10)
    brand_expansion: float = Field(ge=0, le=10)
    rationale: str
    blocking_concerns: list[str] = Field(default=[], description="Legal/ethical/impersonation/authenticity issues that should disqualify it")


# ---------- Agent 03 / 04 ----------
class CreativeBrief(BaseModel):
    candidate_id: str
    target_audience: str
    emotional_hook: str
    brand_personality: str
    three_second_impression: str
    visual_positioning: str
    cultural_relevance: str
    differentiation: str
    storytelling: str
    website_experience: Literal[
        "premium_editorial", "playful_meme", "retro_internet", "experimental_interactive",
        "tech_product", "cinematic_universe", "minimal_statement", "gamified_community",
    ]
    social_strategy: str
    consistency_rules: list[str]
    avoid: list[str]


class Palette(BaseModel):
    primary: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    background: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    text: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class BrandSystem(BaseModel):
    name: str
    ticker: str = Field(pattern=r"^[A-Z0-9]{2,10}$")
    positioning: str
    story: str
    voice: str
    palette: Palette
    display_font: str = Field(description="A Google Fonts family name")
    body_font: str = Field(description="A Google Fonts family name")
    logo_concept: str
    mascot_direction: str = ""
    website_direction: str
    x_positioning: str
    banner_concept: str
    image_style_guide: str
    social_templates: list[str]
    token_description: str = Field(description="<= 280 chars, launch-platform description. No financial promises.")


class NameCheck(BaseModel):
    conflicts: list[str]
    impersonation_risk: Literal["none", "low", "medium", "high"]
    notes: str
    passed: bool


# ---------- Agent 05 ----------
class AssetPrompt(BaseModel):
    key: str = Field(description="Must be one of the required asset keys given in the prompt")
    prompt: str = Field(description="Full image-generation prompt, self-contained, restating the character sheet and style")


class VisualSpec(BaseModel):
    character_sheet: str
    style_rules: list[str]
    negative_rules: list[str]
    prompts: list[AssetPrompt]


class ImageReview(BaseModel):
    passed: bool
    defects: list[str]


# ---------- Agent 06 ----------
class SiteSection(BaseModel):
    id: str
    heading: str
    body: str
    image_key: str = ""


class SiteCopy(BaseModel):
    title: str
    meta_description: str
    hero_headline: str
    hero_subline: str
    sections: list[SiteSection]
    footer_disclaimer: str


# ---------- Agent 07 ----------
class Post(BaseModel):
    n: int
    purpose: str
    text: str = Field(description="<= 280 chars")
    image_key: str = ""
    timing: str


class SocialPackage(BaseModel):
    display_name: str = Field(max_length=50)
    handle_candidates: list[str]
    bio: str = Field(max_length=160)
    location: str = ""
    pinned_post: str
    posts: list[Post]
    sequencing: str


# ---------- Agent 11 ----------
class QAIssue(BaseModel):
    agent: Literal["market", "strategy", "creative", "brand", "visual", "website", "social", "browser", "wallet", "launch"]
    severity: Literal["blocker", "major", "minor"]
    problem: str
    fix: str


class QAReview(BaseModel):
    matches_strategy: bool
    issues: list[QAIssue]
    summary: str
