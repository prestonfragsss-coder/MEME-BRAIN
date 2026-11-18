"""Agent 06 Website Architect & Builder: copy -> static site -> Netlify deploy -> live verification (SOP 3)."""
from __future__ import annotations

import html
import io
import json
import re
import shutil
import time
import zipfile
from pathlib import Path

import httpx

from hermes.agents.common import HOUSE_RULES, Blocked, Ctx
from hermes.models import BrandSystem, CreativeBrief, SiteCopy
from hermes.safety import lint_public_copy

COPY_SYSTEM = f"""You are the website copywriter and information architect. Write original copy in the brand voice for a single-page
site. For pure memes focus on entertainment, story and community; never invent a product, utility, roadmap, team, partners,
tokenomics promises or metrics. If real technology exists, describe only what is implemented. Sections: 3-6, ids lowercase
slug. image_key may be one of: hero, support_1, support_2, pose_1, pose_2, meme_template, or empty.
The footer disclaimer must say this is a community meme token with no intrinsic value or expectation of financial return.
{HOUSE_RULES}"""

SITE_IMAGES = ["hero", "support_1", "support_2", "pose_1", "pose_2", "meme_template", "og_image", "token_icon"]
ASSET_SRC = {
    "hero": "website/assets/hero.png", "support_1": "website/assets/support_1.png", "support_2": "website/assets/support_2.png",
    "og_image": "website/assets/og.png", "token_icon": "brand/token_icon.png", "pose_1": "brand/pose_1.png",
    "pose_2": "brand/pose_2.png", "meme_template": "social/post_assets/meme_template.png",
}

LAYOUTS = {
    "premium_editorial": "--radius:2px;--hero-align:left;--section-gap:9rem;--measure:38rem;",
    "playful_meme": "--radius:28px;--hero-align:center;--section-gap:5rem;--measure:34rem;",
    "retro_internet": "--radius:0;--hero-align:center;--section-gap:4rem;--measure:40rem;",
    "experimental_interactive": "--radius:12px;--hero-align:left;--section-gap:7rem;--measure:36rem;",
    "tech_product": "--radius:10px;--hero-align:left;--section-gap:7rem;--measure:40rem;",
    "cinematic_universe": "--radius:4px;--hero-align:center;--section-gap:10rem;--measure:36rem;",
    "minimal_statement": "--radius:0;--hero-align:center;--section-gap:12rem;--measure:30rem;",
    "gamified_community": "--radius:16px;--hero-align:center;--section-gap:6rem;--measure:38rem;",
}


def site_copy(ctx: Ctx, brand: BrandSystem, brief: CreativeBrief, reference: str, feedback: str = "") -> SiteCopy:
    fb = f"\nRejected previous attempt: {feedback}" if feedback else ""
    return ctx.llm.structured(
        COPY_SYSTEM,
        f"Brand:\n{brand.model_dump_json(indent=2)}\n\nBrief:\n{brief.model_dump_json(indent=2)}\n\n"
        f"Reference analysis (layout/pacing only, no copying):\n{reference[:4000] or 'none'}{fb}",
        SiteCopy,
    )


def lint_copy(c: SiteCopy) -> list[str]:
    text = " ".join([c.title, c.meta_description, c.hero_headline, c.hero_subline, c.footer_disclaimer,
                     *[s.heading + " " + s.body for s in c.sections]])
    return [f"{f.where}: {f.reason} ('{f.excerpt}')" for f in lint_public_copy(text, "website")]


def _e(s: str) -> str:
    return html.escape(s, quote=True)


def _paras(s: str) -> str:
    return "".join(f"<p>{_e(p.strip())}</p>" for p in re.split(r"\n\s*\n|\n", s) if p.strip())


def render(brand: BrandSystem, brief: CreativeBrief, copy: SiteCopy, links: dict[str, str], ca: str = "",
           site_url: str = "") -> str:
    p = brand.palette
    fonts = "&".join(f"family={f.replace(' ', '+')}:wght@400;600;800" for f in dict.fromkeys([brand.display_font, brand.body_font]))
    nav = "".join(f'<a href="#{_e(s.id)}">{_e(s.heading)}</a>' for s in copy.sections) + '<a href="#token">Token</a>'
    sections = []
    for i, s in enumerate(copy.sections):
        img = (f'<img src="assets/{_e(s.image_key)}.png" alt="{_e(s.heading)}" loading="lazy">' if s.image_key in SITE_IMAGES else "")
        sections.append(f'<section id="{_e(s.id)}" class="band {"flip" if i % 2 else ""}"><div class="txt"><h2>{_e(s.heading)}</h2>'
                        f'{_paras(s.body)}</div>{img}</section>')
    ca_html = (f'<code id="ca">{_e(ca)}</code><button type="button" data-copy="{_e(ca)}">Copy</button>' if ca else
               '<p class="muted">Not launched yet. The contract address will be published here and on our X account only after launch. '
               'Treat any address posted elsewhere as fake.</p>')
    link_html = "".join(f'<a class="btn" href="{_e(u)}" target="_blank" rel="noopener">{_e(k)}</a>' for k, u in links.items() if u)
    og = f"{site_url.rstrip('/')}/assets/og_image.png" if site_url else "assets/og_image.png"
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(copy.title)}</title>
<meta name="description" content="{_e(copy.meta_description)}">
<link rel="icon" href="assets/token_icon.png">
<meta property="og:type" content="website"><meta property="og:title" content="{_e(copy.title)}">
<meta property="og:description" content="{_e(copy.meta_description)}"><meta property="og:image" content="{_e(og)}">
{f'<meta property="og:url" content="{_e(site_url)}"><link rel="canonical" href="{_e(site_url)}">' if site_url else ''}
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{_e(og)}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?{fonts}&display=swap" rel="stylesheet">
<style>
:root{{--primary:{p.primary};--secondary:{p.secondary};--accent:{p.accent};--bg:{p.background};--text:{p.text};
--display:'{brand.display_font}',system-ui,sans-serif;--body:'{brand.body_font}',system-ui,sans-serif;{LAYOUTS[brief.website_experience]}}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}
body{{margin:0;background:var(--bg);color:var(--text);font:17px/1.6 var(--body);overflow-x:hidden}}
a{{color:var(--accent)}}img{{max-width:100%;display:block;border-radius:var(--radius)}}
header.nav{{position:sticky;top:0;z-index:5;display:flex;gap:1.25rem;align-items:center;justify-content:space-between;padding:.9rem 1rem;
background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px)}}
header.nav .brand{{display:flex;gap:.6rem;align-items:center;font:800 1.1rem var(--display);color:var(--text);text-decoration:none}}
header.nav .brand img{{width:34px;height:34px;border-radius:50%}}
header.nav nav{{display:flex;gap:1rem;flex-wrap:wrap}}header.nav nav a{{color:var(--text);text-decoration:none;opacity:.8;font-size:.95rem}}
.hero{{position:relative;min-height:88vh;display:grid;align-items:end;padding:2rem 1rem 4rem}}
.hero img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:0}}
.hero::after{{content:"";position:absolute;inset:0;background:linear-gradient(to top,var(--bg),transparent 60%)}}
.hero .copy{{position:relative;z-index:1;max-width:var(--measure);text-align:var(--hero-align);margin:0 auto;width:100%}}
h1,h2{{font-family:var(--display);line-height:1.05;margin:0 0 1rem}}h1{{font-size:clamp(2.6rem,8vw,6rem)}}
h2{{font-size:clamp(1.8rem,4.5vw,3rem);color:var(--primary)}}.ticker{{color:var(--accent);font-weight:800;letter-spacing:.08em}}
.band{{display:grid;gap:2rem;align-items:center;max-width:72rem;margin:var(--section-gap) auto;padding:0 1rem}}
@media(min-width:800px){{.band{{grid-template-columns:1fr 1fr}}.band.flip .txt{{order:2}}}}
.txt{{max-width:var(--measure)}}#token{{max-width:48rem;margin:var(--section-gap) auto;padding:2rem 1rem;border-top:2px solid var(--secondary)}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:.4rem 1.2rem}}dt{{opacity:.7}}
code{{word-break:break-all;background:color-mix(in srgb,var(--text) 10%,transparent);padding:.2rem .4rem;border-radius:4px}}
.btn,button{{display:inline-block;margin:.3rem .5rem .3rem 0;padding:.7rem 1.2rem;border-radius:var(--radius);background:var(--primary);
color:var(--bg);font-weight:700;text-decoration:none;border:0;cursor:pointer;font-family:inherit}}.muted{{opacity:.75}}
footer{{padding:3rem 1rem;text-align:center;font-size:.85rem;opacity:.75;max-width:48rem;margin:auto}}
@media(max-width:640px){{header.nav nav{{display:none}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
</style></head><body>
<header class="nav"><a class="brand" href="#top"><img src="assets/token_icon.png" alt="">{_e(brand.name)}</a><nav>{nav}</nav></header>
<main id="top">
<section class="hero"><img src="assets/hero.png" alt="{_e(brand.name)} hero artwork">
<div class="copy"><p class="ticker">${_e(brand.ticker)}</p><h1>{_e(copy.hero_headline)}</h1><p>{_e(copy.hero_subline)}</p>{link_html}</div></section>
{''.join(sections)}
<section id="token"><h2>Token</h2><dl><dt>Name</dt><dd>{_e(brand.name)}</dd><dt>Ticker</dt><dd>${_e(brand.ticker)}</dd>
<dt>Chain</dt><dd>Solana</dd><dt>Contract</dt><dd>{ca_html}</dd></dl></section>
</main>
<footer>{_e(copy.footer_disclaimer)}</footer>
<script>document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>navigator.clipboard.writeText(b.dataset.copy).then(()=>b.textContent='Copied'))</script>
</body></html>"""


def build(ctx: Ctx, html_text: str) -> Path:
    src = ctx.ws.path("website/source")
    if src.exists():
        shutil.rmtree(src)
    (src / "assets").mkdir(parents=True)
    for key, rel in ASSET_SRC.items():
        if not ctx.ws.exists(rel):
            raise Blocked(f"asset {key} missing ({rel}); visual task must complete first")
        shutil.copy(ctx.ws.path(rel), src / "assets" / f"{key}.png")
    ctx.ws.write_text("website/source/index.html", html_text)
    ctx.ws.write_text("website/source/robots.txt", "User-agent: *\nAllow: /\n")
    return src


def check_local(src: Path) -> list[str]:
    """No broken internal refs, no placeholders, viewport + OG present."""
    page = (src / "index.html").read_text()
    problems = []
    for ref in re.findall(r'(?:src|href)="([^"#:]+)"', page):
        if not (src / ref).exists():
            problems.append(f"broken local reference: {ref}")
    for anchor in re.findall(r'href="#([^"]+)"', page):
        if f'id="{anchor}"' not in page:
            problems.append(f"broken anchor: #{anchor}")
    for needle in ('name="viewport"', 'property="og:image"', 'name="description"'):
        if needle not in page:
            problems.append(f"missing meta {needle}")
    problems += [f"{f.reason}: {f.excerpt}" for f in lint_public_copy(re.sub(r"<[^>]+>", " ", page), "html")]
    return problems


class Netlify:
    API = "https://api.netlify.com/api/v1"

    def __init__(self, token: str):
        self.h = {"Authorization": f"Bearer {token}"}

    def ensure_site(self, name: str, existing_id: str = "") -> dict:
        if existing_id:
            r = httpx.get(f"{self.API}/sites/{existing_id}", headers=self.h, timeout=30)
            if r.status_code == 200:
                return r.json()
        for suffix in ["", "-site", "-web", "-xyz"]:
            r = httpx.post(f"{self.API}/sites", headers=self.h, json={"name": f"{name}{suffix}"}, timeout=30)
            if r.status_code in (200, 201):
                return r.json()
            if r.status_code != 422:  # 422 = name taken
                r.raise_for_status()
        r = httpx.post(f"{self.API}/sites", headers=self.h, json={}, timeout=30)
        r.raise_for_status()
        return r.json()

    def deploy_zip(self, site_id: str, src: Path) -> dict:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in src.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(src).as_posix())
        r = httpx.post(f"{self.API}/sites/{site_id}/deploys", headers={**self.h, "Content-Type": "application/zip"},
                       content=buf.getvalue(), timeout=300)
        r.raise_for_status()
        d = r.json()
        for _ in range(60):
            if d.get("state") in ("ready", "error"):
                break
            time.sleep(3)
            d = httpx.get(f"{self.API}/deploys/{d['id']}", headers=self.h, timeout=30).json()
        if d.get("state") != "ready":
            raise RuntimeError(f"deploy ended in state {d.get('state')}: {d.get('error_message')}")
        return d


def deploy(ctx: Ctx, src: Path, site_name: str) -> dict:
    if not ctx.settings.netlify_token:
        raise Blocked("Set NETLIFY_AUTH_TOKEN (website hosting) and run `hermes resume <project>`.")
    prev = ctx.ws.read_json("website/deployment.json") if ctx.ws.exists("website/deployment.json") else {}
    nl = Netlify(ctx.settings.netlify_token)
    site = nl.ensure_site(re.sub(r"[^a-z0-9-]", "-", site_name.lower())[:50], prev.get("site_id", ""))
    d = nl.deploy_zip(site["id"], src)
    url = site.get("ssl_url") or site.get("url")
    info = {"provider": "netlify", "site_id": site["id"], "url": url, "deploy_id": d["id"], "state": d["state"]}
    info["verification"] = verify_live(url, ["assets/hero.png", "assets/og_image.png", "assets/token_icon.png"])
    ctx.ws.write_json("website/deployment.json", info)
    return info


def verify_live(url: str, assets: list[str]) -> dict:
    out: dict = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    r = httpx.get(url, timeout=30, follow_redirects=True)
    out["index"] = r.status_code
    out["https"] = str(r.url).startswith("https://")
    out["assets"] = {a: httpx.get(f"{url.rstrip('/')}/{a}", timeout=30).status_code for a in assets}
    out["ok"] = r.status_code == 200 and out["https"] and all(c == 200 for c in out["assets"].values())
    return out


def external_links_ok(links: dict[str, str]) -> dict[str, str]:
    res = {}
    for k, u in links.items():
        try:
            r = httpx.get(u, timeout=20, follow_redirects=True)
            res[k] = str(r.status_code)
        except Exception as e:  # noqa: BLE001
            res[k] = f"error: {e.__class__.__name__}"
    return res


def deployment_summary(ctx: Ctx) -> str:
    return json.dumps(ctx.ws.read_json("website/deployment.json"), indent=2) if ctx.ws.exists("website/deployment.json") else "not deployed"
