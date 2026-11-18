"""SOP section 4 - weighted 100-point decision-support score (not a price prediction)."""
from __future__ import annotations

from hermes.models import CriterionScores

WEIGHTS: dict[str, int] = {
    "attention_momentum": 20,
    "originality": 20,
    "comprehensibility": 15,
    "visual_meme_potential": 15,
    "cultural_relevance": 10,
    "content_longevity": 10,
    "execution_feasibility": 5,
    "brand_expansion": 5,
}
assert sum(WEIGHTS.values()) == 100


def total(scores: CriterionScores) -> float:
    return round(sum(getattr(scores, k) / 10 * w for k, w in WEIGHTS.items()), 1)


def eligible(scores: CriterionScores, threshold: float) -> tuple[bool, str]:
    t = total(scores)
    if scores.blocking_concerns:
        return False, "blocked: " + "; ".join(scores.blocking_concerns)
    if t < threshold:
        return False, f"score {t} below threshold {threshold}"
    return True, f"score {t}"
