"""Agents 08 (browser workspace), 09 (Phantom wallet) and 10 (launch engineer).

Server-side these agents prepare specs, metadata and checklists. Anything that touches a live account, extension or launch form
runs on the operator's own machine through hermes/local/browser.py, in a dedicated Chrome profile, with the operator present.
"""
from __future__ import annotations

from datetime import datetime, timezone

from hermes.agents.common import Blocked, Ctx
from hermes.models import BrandSystem, SocialPackage
from hermes.safety import is_solana_public_address, lint_public_copy

OFFICIAL = {
    "phantom": "https://phantom.com/download",
    "pumpfun_create": "https://pump.fun/create",
    "x_signup": "https://x.com/i/flow/signup",
}


def profile_name(brand: BrandSystem, created: str | None = None) -> str:
    day = (created or datetime.now(timezone.utc).strftime("%Y%m%d"))[:8]
    proj = "".join(ch for ch in brand.name.upper().replace(" ", "_") if ch.isalnum() or ch == "_")[:24]
    return f"LAUNCH_{day}_{proj}_{brand.ticker}"


def browser_spec(ctx: Ctx, brand: BrandSystem) -> dict:
    st = ctx.ws.load_state()
    spec = {
        "profile_name": profile_name(brand, st.project_id[:8]),
        "isolation": "dedicated Chrome user-data-dir per project (separate cookies, storage, extensions, sessions)",
        "fingerprint_spoofing": False,
        "proxy_rotation": False,
        "bookmarks": {
            "Phantom (official download)": OFFICIAL["phantom"],
            "X sign up": OFFICIAL["x_signup"],
            "Pump.fun create": OFFICIAL["pumpfun_create"],
        },
        "email_identity": "operator-provided durable mailbox (Gmail or custom domain); never a temp inbox for accounts that control assets",
        "command": f"python -m hermes.local.browser open {ctx.ws.root}",
    }
    ctx.ws.write_json("launch/browser_profile.json", spec)
    return spec


WALLET_STEPS = """# Phantom wallet setup — operator-controlled

Hermes never sees, stores or transmits the recovery phrase or private key.

1. Run `python -m hermes.local.browser open {root}` — opens the project's dedicated Chrome profile.
2. In that window open the bookmarked **official** Phantom download page ({phantom}) and install from the Chrome Web Store
   listing it links to. Confirm the publisher is Phantom and the listing is the one linked from phantom.com.
3. Create a **new** wallet. Write the recovery phrase on paper / a password manager **you** control. Do not paste it anywhere else.
4. Copy the wallet's **public** address and register it:
   `hermes wallet {pid} set <PUBLIC_ADDRESS>`
5. Deposit SOL yourself. Hermes does not move funds, sign transactions or grant token approvals.
"""


def wallet_status(ctx: Ctx) -> dict:
    if ctx.ws.exists("wallet/public_address.json"):
        return ctx.ws.read_json("wallet/public_address.json")
    ctx.ws.write_text("wallet/SETUP.md", WALLET_STEPS.format(root=ctx.ws.root, phantom=OFFICIAL["phantom"], pid=ctx.ws.project_id))
    raise Blocked(f"Operator: create the Phantom wallet in the project browser profile (see {ctx.ws.root}/wallet/SETUP.md), "
                  f"then run `hermes wallet {ctx.ws.project_id} set <PUBLIC_ADDRESS>`.")


def register_wallet(ctx: Ctx, address: str) -> dict:
    address = address.strip()
    if not is_solana_public_address(address):
        raise ValueError("not a valid Solana public address (expected 32-byte base58). Never send a seed phrase or private key.")
    rec = {"public_address": address, "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "custody": "operator (Phantom, operator-held recovery phrase)",
           "explorer": f"https://solscan.io/account/{address}"}
    ctx.ws.write_json("wallet/public_address.json", rec)
    return rec


def launch_metadata(ctx: Ctx, brand: BrandSystem, social: SocialPackage, site_url: str, x_handle: str = "",
                    dev_buy_sol: float | None = None) -> dict:
    problems = [f.reason for f in lint_public_copy(brand.token_description, "token description")]
    if len(brand.token_description) > 280:
        problems.append("description over 280 chars")
    if problems:
        raise ValueError("token description failed lint: " + "; ".join(problems))
    wallet = ctx.ws.read_json("wallet/public_address.json") if ctx.ws.exists("wallet/public_address.json") else {}
    meta = {
        "platform": "pump.fun",
        "platform_url": OFFICIAL["pumpfun_create"],
        "name": brand.name,
        "ticker": brand.ticker,
        "description": brand.token_description,
        "image": "brand/token_icon.png",
        "banner": "brand/x_banner.png",
        "website": site_url or None,
        "x_url": f"https://x.com/{x_handle.lstrip('@')}" if x_handle else None,
        "telegram_url": None,
        "dev_wallet_public_address": wallet.get("public_address"),
        "contract_address": None,  # only exists after the operator launches
        "dev_buy_sol": dev_buy_sol,
        "fees": "Read the creation fee and network fee from the live form at launch time; Hermes does not guess them.",
        "funding_estimate": (f"{dev_buy_sol} SOL dev buy + platform/network fees shown on the form + ~0.05 SOL buffer for "
                             "follow-up transactions" if dev_buy_sol is not None else
                             "Operator to set dev buy (`hermes launch <project> --dev-buy <SOL>`); add fees shown on the form."),
        "social_handle_candidates": social.handle_candidates,
    }
    ctx.ws.write_json("launch/metadata.json", meta)
    return meta


def checklist_md(meta: dict, status: dict[str, str]) -> str:
    def box(ok: bool) -> str:
        return "x" if ok else " "

    rows = [
        (bool(meta.get("website")), f"Website live: {meta.get('website') or 'not deployed'}"),
        (bool(meta.get("x_url")), f"X account: {meta.get('x_url') or 'operator to create + register handle'}"),
        (bool(meta.get("dev_wallet_public_address")), f"Dev wallet (public): {meta.get('dev_wallet_public_address') or 'pending'}"),
        (meta.get("dev_buy_sol") is not None, f"Dev buy decided: {meta.get('dev_buy_sol')}"),
        (status.get("form") == "prefilled_verified", f"Launch form prefilled & read back: {status.get('form', 'not run')}"),
    ]
    lines = ["# Launch checklist", "", f"**{meta['name']} (${meta['ticker']})** on {meta['platform']}", ""]
    lines += [f"- [{box(ok)}] {txt}" for ok, txt in rows]
    lines += ["", "## Operator-only steps", "- Back up the Phantom recovery phrase offline.", "- Fund the wallet.",
              "- Review every field on the live form against `launch/metadata.json`.",
              "- Click **Create/Launch** yourself and approve the transaction in Phantom.",
              "- After launch: `hermes set-ca <project> <CONTRACT_ADDRESS>` to publish the CA on the website."]
    return "\n".join(lines) + "\n"
