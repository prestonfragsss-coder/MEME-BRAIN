import pytest

from hermes import scoring
from hermes.agents.research import _verify_sources
from hermes.commands import parse_build
from hermes.models import CandidateSet, CriterionScores, Mode
from hermes.safety import SecretDetected, assert_no_secrets, find_secret, is_solana_public_address, lint_public_copy
from hermes.workspace import Workspace

from tests.fakes import URLS, _cand

SYSTEM_PROGRAM = "11111111111111111111111111111111"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def test_solana_address_validation():
    assert is_solana_public_address(SYSTEM_PROGRAM)
    assert is_solana_public_address(USDC_MINT)
    assert not is_solana_public_address("0xabc")
    assert not is_solana_public_address(USDC_MINT + "x")
    assert not is_solana_public_address("O0Il" * 10)


@pytest.mark.parametrize("text", [
    "abandon ability able about above absent absorb abstract absurd abuse access accident",
    "[" + ",".join(["12"] * 64) + "]",
])
def test_secret_detection(text):
    assert find_secret(text)
    with pytest.raises(SecretDetected):
        assert_no_secrets(text)


def test_public_address_is_not_secret():
    assert find_secret(f"wallet {USDC_MINT}") is None
    assert find_secret("a normal sentence about a crab wearing a tuxedo to dinner tonight with friends") is None


@pytest.mark.parametrize("bad", [
    "Guaranteed 10x returns", "risk-free fun", "next 100x gem", "officially partnered with Nike", "earn passive income",
    "lorem ipsum", "Backed by a16z",
])
def test_lint_flags(bad):
    assert lint_public_copy(bad, "t")


def test_lint_allows_clean_copy():
    assert not lint_public_copy("A crab who always overdresses. Join the dinner party on X.", "t")


def test_scoring_weights_and_threshold():
    s = CriterionScores(attention_momentum=10, originality=10, comprehensibility=10, visual_meme_potential=10,
                        cultural_relevance=10, content_longevity=10, execution_feasibility=10, brand_expansion=10, rationale="")
    assert scoring.total(s) == 100
    s.attention_momentum = 0
    assert scoring.total(s) == 80
    assert scoring.eligible(s, 80)[0]
    s.originality = 9.9
    assert not scoring.eligible(s, 80)[0]
    s.originality = 10
    s.blocking_concerns = ["impersonation"]
    assert not scoring.eligible(s, 80)[0]


def test_parse_modes():
    assert parse_build("/build auto").mode is Mode.AUTO
    assert parse_build("/build").mode is Mode.AUTO
    r = parse_build("/build https://example.com")
    assert r.mode is Mode.URL and r.urls == ["https://example.com"]
    g = parse_build("/build theme: viral AI lobster | vibe: absurd luxury | tech: none | style: cinematic")
    assert g.mode is Mode.GUIDED and g.preferences["theme"] == "viral AI lobster" and g.preferences["style"] == "cinematic"
    h = parse_build("/build https://example.com | find the best current meme meta | premium dark design | surprise me")
    assert h.mode is Mode.HYBRID and len(h.notes) == 3


def test_unretrieved_sources_are_dropped():
    cs = CandidateSet(researched_at="t", research_summary="s", candidates=[_cand(0, True)])
    out = _verify_sources(cs, set(URLS))
    assert all("fabricated" not in s.url for s in out.candidates[0].sources)
    assert len(out.candidates[0].sources) == 2
    out2 = _verify_sources(CandidateSet(researched_at="t", research_summary="s", candidates=[_cand(0, True)]), set())
    assert out2.candidates[0].confidence == "low" and not out2.candidates[0].sources


def test_workspace_refuses_secrets_and_escapes(tmp_path):
    ws = Workspace.create(tmp_path, {"mode": "auto", "raw": "auto"})
    with pytest.raises(SecretDetected):
        ws.write_text("wallet/notes.md", "abandon ability able about above absent absorb abstract absurd abuse access accident")
    with pytest.raises(ValueError):
        ws.path("../../etc/passwd")
    assert Workspace.load(tmp_path, ws.project_id).root == ws.root
