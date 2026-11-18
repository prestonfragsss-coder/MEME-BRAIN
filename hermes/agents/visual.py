"""Agent 05 Visual Asset Director: unified visual spec -> generate -> review -> regenerate (SOP 3)."""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import httpx
from PIL import Image

from hermes.agents.common import HOUSE_RULES, Blocked, Ctx
from hermes.models import BrandSystem, CreativeBrief, ImageReview, VisualSpec


@dataclass(frozen=True)
class Req:
    key: str
    path: str
    size: tuple[int, int]
    purpose: str
    allow_text: bool = False


REQUIRED: list[Req] = [
    Req("token_icon", "brand/token_icon.png", (1024, 1024), "square token icon, reads at 48px"),
    Req("x_avatar", "brand/x_avatar.png", (400, 400), "X profile picture, centred subject for circular crop"),
    Req("x_banner", "brand/x_banner.png", (1500, 500), "X header banner; keep bottom-left clear for avatar overlap"),
    Req("hero", "website/assets/hero.png", (1920, 1080), "website hero artwork"),
    Req("support_1", "website/assets/support_1.png", (1200, 900), "website supporting graphic: the story"),
    Req("support_2", "website/assets/support_2.png", (1200, 900), "website supporting graphic: the community"),
    Req("og_image", "website/assets/og.png", (1200, 630), "Open Graph social preview"),
    Req("launch_art", "social/post_assets/launch.png", (1200, 1200), "launch announcement artwork"),
    Req("meme_template", "social/post_assets/meme_template.png", (1200, 1200), "blank meme template with the character, empty caption space"),
    Req("pose_1", "brand/pose_1.png", (1024, 1024), "mascot/visual variant pose 1"),
    Req("pose_2", "brand/pose_2.png", (1024, 1024), "mascot/visual variant pose 2"),
    *[Req(f"post_{i}", f"social/post_assets/post_{i}.png", (1200, 1200), f"social post graphic #{i}") for i in range(1, 11)],
]
REQ_BY_KEY = {r.key: r for r in REQUIRED}

SPEC_SYSTEM = f"""You are the Visual Asset Director. Before any image is generated you write ONE visual specification that
every asset obeys: same character proportions, colours, line quality, lighting and composition language. Each prompt you write
must be fully self-contained (the image model has no memory) and restate the character sheet and style rules.
Do not ask for text/lettering inside images unless explicitly allowed; never include real logos or real people.
{HOUSE_RULES}"""

REVIEW_SYSTEM = """You are a strict art director reviewing a generated brand asset. Fail it for: unwanted or garbled text,
distorted anatomy or character, off-palette colours, inconsistency with the character sheet, generic stock-crypto composition,
real logos or recognisable real people, watermarks, or poor fit for its stated purpose and crop."""


def visual_spec(ctx: Ctx, brand: BrandSystem, brief: CreativeBrief) -> VisualSpec:
    reqs = "\n".join(f"- {r.key}: {r.size[0]}x{r.size[1]} — {r.purpose}" for r in REQUIRED)
    spec = ctx.llm.structured(
        SPEC_SYSTEM,
        f"Brand:\n{brand.model_dump_json(indent=2)}\n\nBrief:\n{brief.model_dump_json(indent=2)}\n\n"
        f"Required assets (write exactly one prompt per key):\n{reqs}\n\nThe ten post graphics must each illustrate a different idea.",
        VisualSpec,
    )
    missing = set(REQ_BY_KEY) - {p.key for p in spec.prompts}
    if missing:
        raise ValueError(f"visual spec missing prompts for: {sorted(missing)}")
    return spec


def _gen_size(target: tuple[int, int]) -> str:
    w, h = target
    r = w / h
    return "1536x1024" if r > 1.15 else "1024x1536" if r < 0.87 else "1024x1024"


def fit(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Center-crop to aspect, then resize."""
    tw, th = size
    w, h = img.size
    tr = tw / th
    if w / h > tr:
        nw = int(h * tr)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / tr)
        img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    return img.resize(size, Image.LANCZOS)


class ImageGen:
    def __init__(self, api_key: str, model: str):
        self.api_key, self.model = api_key, model

    def generate(self, prompt: str, size: str) -> bytes:
        r = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "prompt": prompt, "size": size, "n": 1},
            timeout=300,
        )
        r.raise_for_status()
        d = r.json()["data"][0]
        if d.get("b64_json"):
            return base64.b64decode(d["b64_json"])
        return httpx.get(d["url"], timeout=120).content


INBOX = "brand/inbox"
_ASPECT = {"1536x1024": "landscape (3:2)", "1024x1536": "portrait (2:3)", "1024x1024": "square (1:1)"}


def _style_block(spec: VisualSpec) -> str:
    return "\n".join(["Character sheet: " + spec.character_sheet, "Style: " + "; ".join(spec.style_rules),
                      "Never: " + "; ".join(spec.negative_rules)])


def _review(ctx: Ctx, spec: VisualSpec, r: Req, data: bytes) -> ImageReview:
    return ctx.llm.structured(
        REVIEW_SYSTEM,
        f"Asset: {r.key} ({r.purpose}), text allowed: {r.allow_text}.\nCharacter sheet: {spec.character_sheet}\n"
        f"Style rules: {spec.style_rules}",
        ImageReview, images=[data], effort="medium",
    )


def _png(raw: bytes, size: tuple[int, int]) -> bytes:
    img = fit(Image.open(io.BytesIO(raw)).convert("RGB"), size)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def write_chatgpt_prompts(ctx: Ctx, spec: VisualSpec, defects: dict[str, list[str]] | None = None) -> str:
    """Manual path for operators who generate images in their ChatGPT subscription instead of via the API."""
    prompts = {p.key: p.prompt for p in spec.prompts}
    inbox = ctx.ws.path(INBOX)
    inbox.mkdir(parents=True, exist_ok=True)
    todo = [r for r in REQUIRED if not ctx.ws.exists(r.path)]
    out = ["# Image prompts for ChatGPT", "",
           f"Generate each image in ChatGPT, download it, and save it as `<key>.png` (or .jpg/.webp) in:\n\n`{inbox}`\n",
           "Then run `hermes import-assets <project>` (or `hermes resume <project>`). Hermes crops to the exact size, reviews each "
           "image for defects, and lists any that need a redo here.", "",
           "Tip: generate the token icon first, then attach it to later chats and say \"same character\" so every asset stays consistent.",
           ""]
    for r in todo:
        redo = (defects or {}).get(r.key)
        out += [f"## `{r.key}` — {r.purpose}", f"Ask for: **{_ASPECT[_gen_size(r.size)]}**, final crop {r.size[0]}x{r.size[1]}"]
        if redo:
            out.append("**Redo — previous image was rejected for:** " + "; ".join(redo))
        out += ["", "```", f"{prompts[r.key]}\n\n{_style_block(spec)}\n\nPurpose: {r.purpose}. No text, watermarks or logos.", "```", ""]
    if not todo:
        out.append("All assets imported and approved.")
    text = "\n".join(out) + "\n"
    ctx.ws.write_text("brand/IMAGE_PROMPTS.md", text)
    return text


def import_assets(ctx: Ctx, spec: VisualSpec) -> dict[str, dict]:
    """Import operator-generated images from the inbox: fit, review, accept or flag for redo."""
    inbox = ctx.ws.path(INBOX)
    results: dict[str, dict] = {}
    defects: dict[str, list[str]] = {}
    for r in REQUIRED:
        if ctx.ws.exists(r.path):
            results[r.key] = {"path": r.path, "passed": True, "defects": [], "source": "existing"}
            continue
        files = [f for ext in ("png", "jpg", "jpeg", "webp") for f in inbox.glob(f"{r.key}.{ext}")]
        if not files:
            results[r.key] = {"path": r.path, "passed": False, "defects": ["not provided yet"], "source": "chatgpt"}
            continue
        data = _png(files[0].read_bytes(), r.size)
        rv = _review(ctx, spec, r, data)
        if rv.passed:
            ctx.ws.write_bytes(r.path, data)
            files[0].unlink()
        else:
            defects[r.key] = rv.defects
            files[0].rename(files[0].with_name(f"{r.key}.rejected{files[0].suffix}"))
        results[r.key] = {"path": r.path, "passed": rv.passed, "defects": rv.defects, "source": "chatgpt"}
    write_chatgpt_prompts(ctx, spec, defects)
    return results


def generate_assets(ctx: Ctx, spec: VisualSpec, only: set[str] | None = None, gen: ImageGen | None = None) -> dict[str, dict]:
    """Generate (or regenerate `only`) assets. Returns {key: {path, attempts, passed, defects}}. Never writes placeholders.

    Without an API key (or with HERMES_IMAGE_SOURCE=chatgpt) the operator generates images in ChatGPT and Hermes imports them.
    """
    if gen is None and (ctx.settings.image_source == "chatgpt" or not ctx.settings.openai_api_key):
        if only:
            for k in only:
                if ctx.ws.exists(REQ_BY_KEY[k].path):
                    ctx.ws.path(REQ_BY_KEY[k].path).unlink()
        res = import_assets(ctx, spec)
        missing = [k for k, v in res.items() if not v["passed"]]
        if missing:
            raise Blocked(f"Operator: generate {len(missing)} image(s) in ChatGPT using {ctx.ws.root}/brand/IMAGE_PROMPTS.md, "
                          f"save them to {ctx.ws.path(INBOX)}, then run `hermes import-assets {ctx.ws.project_id}`.")
        return res
    if gen is None:
        gen = ImageGen(ctx.settings.openai_api_key, ctx.settings.image_model)
    prompts = {p.key: p.prompt for p in spec.prompts}
    style = _style_block(spec)
    results: dict[str, dict] = {}
    for r in REQUIRED:
        if only is not None and r.key not in only:
            continue
        if only is None and ctx.ws.exists(r.path):
            results[r.key] = {"path": r.path, "attempts": 0, "passed": True, "defects": [], "cached": True}
            continue
        defects: list[str] = []
        attempts = 0
        passed = False
        for attempts in range(1, ctx.settings.max_image_attempts + 1):
            extra = (" Avoid these defects from the last attempt: " + "; ".join(defects)) if defects else ""
            raw = gen.generate(f"{prompts[r.key]}\n\n{style}\n\nPurpose: {r.purpose}.{extra}", _gen_size(r.size))
            data = _png(raw, r.size)
            review = _review(ctx, spec, r, data)
            defects = review.defects
            if review.passed:
                ctx.ws.write_bytes(r.path, data)
                passed = True
                break
        results[r.key] = {"path": r.path, "attempts": attempts, "passed": passed, "defects": defects}
    return results
