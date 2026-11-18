"""End-to-end orchestration with fakes: verifies phases, blocking on operator steps, resume, and handoff."""
import dataclasses

import pytest

from hermes.agents import research, website
from hermes.cli import main as cli
from hermes.config import Settings
from hermes.orchestrator import Pipeline, start
from hermes.workspace import Workspace

from tests.fakes import FakeImageGen, FakeLLM, fake_deploy

ADDR = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "dexscreener_solana", lambda q, limit=8: [])
    monkeypatch.setattr(website, "deploy", fake_deploy)
    monkeypatch.setenv("HERMES_LAUNCHES_DIR", str(tmp_path))
    s = dataclasses.replace(Settings(), launches_dir=tmp_path, openai_api_key="test", netlify_token="test")
    return s


def _pipe(s, llm=None, ws=None):
    if ws is None:
        p = start("/build auto", settings=s, llm=llm or FakeLLM())
        p.image_gen = FakeImageGen()
        return p
    return Pipeline(ws, llm=llm or FakeLLM(), settings=s, image_gen=FakeImageGen())


def test_full_run_blocks_only_on_operator_steps(env):
    p = _pipe(env)
    out = p.run()
    st = p.ws.load_state()
    s = {k: t.status for k, t in st.tasks.items()}
    for t in ("research", "creative_brief", "brand", "visual", "social", "site_copy", "browser", "website", "qa"):
        assert s[t] == "verified", (t, st.tasks[t])
    assert s["x_account"] == "blocked" and s["wallet"] == "blocked"
    assert not out["launch_ready"]
    assert st.name == "Tux Crab" and st.ticker == "TUXC"
    html = p.ws.path("website/source/index.html").read_text()
    assert "Not launched yet" in html and "https://tux-crab.example.app" in html
    for rel in ("brand/token_icon.png", "brand/x_banner.png", "website/assets/og.png", "social/post_assets/post_10.png",
                "HANDOFF.md", "qa/audit.md", "wallet/SETUP.md"):
        assert p.ws.exists(rel), rel


def test_operator_steps_then_launch_ready(env):
    p = _pipe(env)
    p.run()
    pid = p.ws.project_id
    assert cli(["wallet", pid, "set", ADDR]) == 0
    assert cli(["wallet", pid, "set", "abandon ability able about above absent absorb abstract absurd abuse access accident"]) == 2
    assert cli(["set-x", pid, "tuxcrab"]) == 0
    assert cli(["launch", pid, "--dev-buy", "0.5"]) == 0
    p2 = _pipe(env, ws=Workspace.load(env.launches_dir, pid))
    out = p2.run()
    assert p2.ws.task("launch").status == "blocked"  # form prefill must happen on the operator's machine
    p2.ws.write_json("launch/form_status.json", {"status": "prefilled_verified"})
    p2.ws.update_task("launch", "launch", status="pending")
    out = p2.run()
    assert out["launch_ready"], out["outstanding"]
    meta = p2.ws.read_json("launch/metadata.json")
    assert meta["contract_address"] is None and meta["dev_wallet_public_address"] == ADDR
    assert meta["x_url"] == "https://x.com/tuxcrab"
    assert "x.com/tuxcrab" in p2.ws.path("website/source/index.html").read_text()


def test_resume_is_idempotent(env):
    p = _pipe(env)
    p.run()
    llm = FakeLLM()
    p2 = _pipe(env, llm=llm, ws=p.ws)
    p2.run()
    assert "CandidateSet" not in llm.calls and "BrandSystem" not in llm.calls  # completed work not redone
    assert p2.image_gen.n == 0


def test_no_suitable_concept_stops(env):
    p = _pipe(env, llm=FakeLLM(scores_high=False))
    out = p.run()
    assert p.ws.load_state().phase == "no_suitable_concept"
    assert not out["launch_ready"]
    assert not p.ws.exists("brand/brand.json")


def test_missing_image_key_blocks_without_placeholders(env):
    s = dataclasses.replace(env, openai_api_key="")
    p = start("/build auto", settings=s, llm=FakeLLM())
    p.run()
    assert p.ws.task("visual").status == "blocked"
    assert not p.ws.exists("brand/token_icon.png")
    assert p.ws.task("website").status == "pending"


def test_pause(env):
    p = _pipe(env)
    st = p.ws.load_state(); st.paused = True; p.ws.save_state(st)
    p.run()
    assert not p.ws.load_state().tasks


def test_chatgpt_import_path(env, tmp_path):
    import io

    from PIL import Image

    from hermes.agents.visual import REQUIRED

    s = dataclasses.replace(env, openai_api_key="", image_source="chatgpt")
    p = start("/build auto", settings=s, llm=FakeLLM())
    p.run()
    assert p.ws.task("visual").status == "blocked"
    prompts = p.ws.path("brand/IMAGE_PROMPTS.md").read_text()
    assert "token_icon" in prompts and "post_10" in prompts and not p.ws.exists("brand/token_icon.png")
    folder = tmp_path / "from_chatgpt"
    folder.mkdir()
    for r in REQUIRED:
        Image.new("RGB", (1536, 1024), (10, 120, 200)).save(folder / f"{r.key}.png")
    import hermes.orchestrator as orch
    orig = orch.ClaudeLLM
    orch.ClaudeLLM = lambda *a, **k: FakeLLM()
    try:
        assert cli(["import-assets", p.ws.project_id, str(folder)]) == 0
    finally:
        orch.ClaudeLLM = orig
    ws = Workspace.load(s.launches_dir, p.ws.project_id)
    assert ws.task("visual").status == "verified"
    assert Image.open(ws.path("brand/x_banner.png")).size == (1500, 500)
    assert Image.open(ws.path("brand/token_icon.png")).size == (1024, 1024)
    assert ws.task("website").status == "verified"
