"""Executive orchestrator: SOP section 5 phases with idempotent, resumable tasks (section 9)."""
from __future__ import annotations

import json
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from hermes.agents import creative, ops, qa, research, social, visual, website
from hermes.agents.common import Blocked, Ctx
from hermes.commands import parse_build
from hermes.config import Settings, get_settings
from hermes.llm import LLM, ClaudeLLM
from hermes.models import (BrandSystem, BuildRequest, Candidate, CandidateSet, CreativeBrief, SiteCopy, SocialPackage,
                           VisualSpec)
from hermes.workspace import Workspace

log = logging.getLogger("hermes")


class NoSuitableConcept(Exception):
    pass


class Paused(Exception):
    pass


class Pipeline:
    def __init__(self, ws: Workspace, llm: LLM | None = None, settings: Settings | None = None,
                 progress: Callable[[str], None] | None = None, image_gen: Any = None):
        self.settings = settings or get_settings()
        self.ctx = Ctx(ws=ws, llm=llm or ClaudeLLM(self.settings.model), settings=self.settings)
        self.ws = ws
        self.say = progress or (lambda m: log.info(m))
        self.image_gen = image_gen

    # ------------------------------------------------------------------ task runner
    def step(self, task_id: str, agent: str, fn: Callable[[], Any], deps: tuple[str, ...] = (), retries: int = 2,
             force: bool = False) -> bool:
        st = self.ws.load_state()
        if st.paused:
            raise Paused()
        t = st.tasks.get(task_id)
        if t and t.status == "verified" and not force:
            return True
        for d in deps:
            dt = st.tasks.get(d)
            if not dt or dt.status != "verified":
                self.ws.update_task(task_id, agent, status="pending", depends_on=list(deps), next_action=f"waiting on {d}")
                return False
        attempts = (t.attempts if t else 0)
        for _ in range(retries + 1):
            attempts += 1
            self.ws.update_task(task_id, agent, status="running", depends_on=list(deps), attempts=attempts, failure_reason="")
            try:
                outputs = fn() or []
                self.ws.update_task(task_id, agent, status="verified", outputs=list(outputs), verification="ok",
                                    operator_action="", next_action="")
                self.say(f"✓ {task_id}")
                return True
            except (Blocked,) as b:
                self.ws.update_task(task_id, agent, status="blocked", operator_action=str(b), next_action="operator")
                self.say(f"⏸ {task_id}: {b}")
                return False
            except (NoSuitableConcept, Paused):
                raise
            except Exception as e:  # noqa: BLE001 - diagnose, retry, then record
                log.debug(traceback.format_exc())
                reason = f"{e.__class__.__name__}: {e}"[:800]
                self.ws.update_task(task_id, agent, status="failed", failure_reason=reason, next_action="retry")
                self.say(f"✗ {task_id} attempt {attempts}: {reason}")
        return False

    # ------------------------------------------------------------------ helpers
    def _j(self, rel: str, model: type) -> Any:
        return model.model_validate(self.ws.read_json(rel))

    def request(self) -> BuildRequest:
        return BuildRequest.model_validate(self.ws.load_state().request)

    def _reference(self) -> str:
        return self.ws.path("strategy/reference_analysis.md").read_text() if self.ws.exists("strategy/reference_analysis.md") else ""

    # ------------------------------------------------------------------ phases
    def p1_2_discovery(self) -> list[str]:
        req = self.request()
        cs = research.discover(self.ctx, req)
        rows = research.score_all(self.ctx, cs)
        research.write_research_md(self.ctx, cs, rows)
        self.ws.write_json("strategy/candidates.json", cs)
        self.ws.write_json("strategy/candidate_scores.json", rows)
        winner = next((r for r in rows if r["eligible"]), None)
        if not winner:
            raise NoSuitableConcept("No candidate met the threshold: " + "; ".join(f"{r['title']}={r['total']} ({r['reason']})" for r in rows))
        cand = next(c for c in cs.candidates if c.id == winner["candidate_id"])
        self.ws.write_json("strategy/selected_candidate.json", {**cand.model_dump(), "score": winner})
        return ["strategy/market_research.md", "strategy/candidate_scores.json", "strategy/selected_candidate.json"]

    def _candidate(self) -> Candidate:
        d = self.ws.read_json("strategy/selected_candidate.json")
        d.pop("score", None)
        return Candidate.model_validate(d)

    def p3_creative(self) -> list[str]:
        req = self.request()
        cand = self._candidate()
        brief = creative.creative_brief(self.ctx, cand, req.preferences | {"notes": "; ".join(req.notes)}, self._reference())
        self.ws.write_json("strategy/creative_brief.json", brief)
        md = "# Creative brief\n\n" + "\n".join(f"**{k.replace('_', ' ').title()}:** {v}\n" for k, v in brief.model_dump().items())
        self.ws.write_text("strategy/creative_brief.md", md)
        return ["strategy/creative_brief.md"]

    def p3_brand(self) -> list[str]:
        cand, brief = self._candidate(), self._j("strategy/creative_brief.json", CreativeBrief)
        feedback = ""
        for _ in range(3):
            b = creative.brand_system(self.ctx, cand, brief, feedback)
            chk = creative.name_check(self.ctx, b)
            self.ws.write_json("brand/name_check.json", {"name": b.name, "ticker": b.ticker, **chk.model_dump()})
            if chk.passed and chk.impersonation_risk in ("none", "low"):
                break
            feedback = f"{b.name} (${b.ticker}) rejected: {chk.notes}; conflicts: {chk.conflicts}"
        else:
            raise RuntimeError("could not find a conflict-free name in 3 attempts: " + feedback)
        self.ws.write_json("brand/brand.json", b)
        self.ws.write_text("brand/brand_guide.md", creative.brand_guide_md(b, brief))
        st = self.ws.load_state()
        st.name, st.ticker, st.phase = b.name, b.ticker, "production"
        self.ws.save_state(st)
        return ["brand/brand.json", "brand/brand_guide.md"]

    def _brand(self) -> tuple[BrandSystem, CreativeBrief]:
        return self._j("brand/brand.json", BrandSystem), self._j("strategy/creative_brief.json", CreativeBrief)

    def p4_visual(self, only: set[str] | None = None) -> list[str]:
        b, brief = self._brand()
        if not self.ws.exists("brand/visual_spec.json"):
            self.ws.write_json("brand/visual_spec.json", visual.visual_spec(self.ctx, b, brief))
        spec = self._j("brand/visual_spec.json", VisualSpec)
        res = visual.generate_assets(self.ctx, spec, only=only, gen=self.image_gen)
        self.ws.write_json("brand/asset_report.json", res)
        failed = [k for k, v in res.items() if not v["passed"]]
        if failed:
            raise RuntimeError(f"assets failed review after retries: {failed}")
        return [v["path"] for v in res.values()]

    def p4_social(self, feedback: str = "") -> list[str]:
        b, brief = self._brand()
        site = self._site_url()
        for _ in range(3):
            pkg = social.social_package(self.ctx, b, brief, site, feedback)
            problems = social.validate(pkg)
            if not problems:
                break
            feedback = "; ".join(problems)
        else:
            raise RuntimeError("social content failed validation: " + feedback)
        self.ws.write_json("social/profile.json", pkg)
        self.ws.write_text("social/ten_posts.md", social.posts_md(pkg, b))
        return ["social/profile.json", "social/ten_posts.md"]

    def p4_copy(self, feedback: str = "") -> list[str]:
        b, brief = self._brand()
        for _ in range(3):
            c = website.site_copy(self.ctx, b, brief, self._reference(), feedback)
            problems = website.lint_copy(c)
            if not problems:
                break
            feedback = "; ".join(problems)
        else:
            raise RuntimeError("website copy failed lint: " + feedback)
        self.ws.write_json("website/copy.json", c)
        return ["website/copy.json"]

    def p4_browser(self) -> list[str]:
        b, _ = self._brand()
        ops.browser_spec(self.ctx, b)
        return ["launch/browser_profile.json"]

    def _links(self) -> dict[str, str]:
        st = self.ws.read_json("launch/operator.json") if self.ws.exists("launch/operator.json") else {}
        links = {}
        if st.get("x_handle"):
            links["X"] = f"https://x.com/{st['x_handle']}"
        if st.get("telegram_url"):
            links["Telegram"] = st["telegram_url"]
        if st.get("contract_address"):
            links["Buy on pump.fun"] = f"https://pump.fun/coin/{st['contract_address']}"
        return links

    def _site_url(self) -> str:
        return self.ws.read_json("website/deployment.json").get("url", "") if self.ws.exists("website/deployment.json") else ""

    def p5_website(self) -> list[str]:
        b, brief = self._brand()
        c = self._j("website/copy.json", SiteCopy)
        op = self.ws.read_json("launch/operator.json") if self.ws.exists("launch/operator.json") else {}
        url = self._site_url()
        src = website.build(self.ctx, website.render(b, brief, c, self._links(), op.get("contract_address", ""), url))
        problems = website.check_local(src)
        if problems:
            raise RuntimeError("local site checks failed: " + "; ".join(problems))
        info = website.deploy(self.ctx, src, f"{b.name}-{b.ticker}")
        if not url:  # first deploy: rebuild with canonical/OG absolute URLs and redeploy
            src = website.build(self.ctx, website.render(b, brief, c, self._links(), op.get("contract_address", ""), info["url"]))
            info = website.deploy(self.ctx, src, f"{b.name}-{b.ticker}")
        if not info["verification"]["ok"]:
            raise RuntimeError(f"live verification failed: {info['verification']}")
        return ["website/deployment.json"]

    def p5_wallet(self) -> list[str]:
        ops.wallet_status(self.ctx)
        return ["wallet/public_address.json"]

    def p5_x_account(self) -> list[str]:
        op = self.ws.read_json("launch/operator.json") if self.ws.exists("launch/operator.json") else {}
        if not op.get("x_handle"):
            pkg = self._j("social/profile.json", SocialPackage)
            raise Blocked("Operator: create the X account in the project browser profile (CAPTCHA/phone verification are yours). "
                          f"Suggested handles: {', '.join(pkg.handle_candidates)}. Then `hermes set-x {self.ws.project_id} <handle>`.")
        return ["launch/operator.json"]

    def p5_launch(self) -> list[str]:
        b, _ = self._brand()
        op = self.ws.read_json("launch/operator.json") if self.ws.exists("launch/operator.json") else {}
        meta = ops.launch_metadata(self.ctx, b, self._j("social/profile.json", SocialPackage), self._site_url(),
                                   op.get("x_handle", ""), op.get("dev_buy_sol"))
        form = self.ws.read_json("launch/form_status.json") if self.ws.exists("launch/form_status.json") else {}
        self.ws.write_text("launch/launch_checklist.md", ops.checklist_md(meta, {"form": form.get("status", "not run")}))
        missing = [k for k in ("website", "x_url", "dev_wallet_public_address") if not meta.get(k)]
        if missing:
            raise Blocked(f"launch metadata waiting on: {', '.join(missing)}")
        if form.get("status") != "prefilled_verified":
            raise Blocked(f"Operator machine: run `python -m hermes.local.browser prefill {self.ws.root}` to populate the "
                          "pump.fun form (it never clicks Create).")
        return ["launch/metadata.json", "launch/launch_checklist.md"]

    def p6_qa(self) -> list[str]:
        det = qa.deterministic(self.ctx)
        rv = qa.review(self.ctx)
        blockers = [i for i in det if i["severity"] == "blocker"] + [i for i in rv.issues if i.severity == "blocker"]
        passed = not blockers and rv.matches_strategy and not [i for i in det if i["severity"] == "major"]
        self.ws.write_text("qa/audit.md", qa.audit_md(det, rv, passed))
        self.ws.write_json("qa/audit.json", {"deterministic": det, "review": rv.model_dump(), "passed": passed})
        if not passed:
            raise RuntimeError("QA failed; see qa/audit.md")
        return ["qa/audit.md"]

    def repair_from_qa(self) -> bool:
        """Route QA issues back to responsible agents. Returns True if anything was re-run."""
        if not self.ws.exists("qa/audit.json"):
            return False
        a = self.ws.read_json("qa/audit.json")
        issues = a["deterministic"] + a["review"]["issues"]
        by_agent: dict[str, list[str]] = {}
        for i in issues:
            if i["severity"] in ("blocker", "major"):
                by_agent.setdefault(i["agent"], []).append(f"{i['problem']} -> {i['fix']}")
        ran = False
        if "social" in by_agent:
            ran |= self.step("social", "social", lambda: self.p4_social("; ".join(by_agent["social"])), ("brand",), force=True)
        if "website" in by_agent:
            ran |= self.step("site_copy", "website", lambda: self.p4_copy("; ".join(by_agent["website"])), ("brand",), force=True)
            ran |= self.step("website", "website", self.p5_website, ("site_copy", "visual"), force=True)
        if "visual" in by_agent:
            ran |= self.step("visual", "visual", self.p4_visual, ("brand",), force=True)
        return ran

    # ------------------------------------------------------------------ run
    def run(self) -> dict:
        try:
            self.step("research", "market", self.p1_2_discovery)
            self.step("creative_brief", "creative", self.p3_creative, ("research",))
            self.step("brand", "brand", self.p3_brand, ("creative_brief",))
            # Phase 4: parallel production from the same approved brief
            jobs = [("visual", "visual", self.p4_visual), ("social", "social", self.p4_social),
                    ("site_copy", "website", self.p4_copy), ("browser", "browser", self.p4_browser)]
            with ThreadPoolExecutor(max_workers=4) as ex:
                list(ex.map(lambda j: self.step(j[0], j[1], j[2], ("brand",)), jobs))
            # Phase 5: integration
            self.step("website", "website", self.p5_website, ("site_copy", "visual"))
            self.step("x_account", "social", self.p5_x_account, ("social",))
            self.step("wallet", "wallet", self.p5_wallet, ("browser",))
            self.step("launch", "launch", self.p5_launch, ("website", "wallet", "x_account", "social", "visual"))
            # Phase 6: QA with repair loop
            for _ in range(self.settings.max_repair_rounds + 1):
                if self.step("qa", "qa", self.p6_qa, ("visual", "social", "site_copy", "website"), retries=0, force=True):
                    break
                if not self.repair_from_qa():
                    break
        except NoSuitableConcept as e:
            st = self.ws.load_state()
            st.phase = "no_suitable_concept"
            st.notes.append(str(e))
            self.ws.save_state(st)
            self.say(f"No suitable concept: {e}")
        except Paused:
            self.say("paused; state preserved")
        from hermes.report import handoff

        return handoff(self.ws)


def start(text: str, settings: Settings | None = None, llm: LLM | None = None, progress=None) -> Pipeline:
    s = settings or get_settings()
    req = parse_build(text)
    ws = Workspace.create(s.launches_dir, json.loads(req.model_dump_json()), label=req.mode.value)
    return Pipeline(ws, llm=llm, settings=s, progress=progress)
