"""Operator-machine helper (Agents 08 + 10). Requires: pip install 'hermes-launch-os[local]' && playwright install chrome

  python -m hermes.local.browser open    <project_dir>   # dedicated Chrome profile with project bookmarks as tabs
  python -m hermes.local.browser prefill <project_dir>   # fill the pump.fun create form, read it back, STOP

Design constraints:
  * one persistent Chrome user-data-dir per project (real isolation, no fingerprint spoofing, no proxy rotation)
  * the operator does Phantom install, wallet creation, CAPTCHAs and logins themselves in that window
  * prefill never clicks Create/Launch/Confirm and never interacts with the wallet popup
  * the live form's field mapping is discovered at runtime and verified by reading values back; anything that could not be
    matched is reported, never assumed
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

FORBIDDEN_CLICK = re.compile(r"create|launch|deploy|confirm|approve|sign|buy|connect", re.I)

FIELDS = {
    "name": ["name", "coin name", "token name"],
    "ticker": ["ticker", "symbol"],
    "description": ["description", "about"],
    "website": ["website"],
    "x_url": ["twitter", "x link", "x (twitter)", "x url"],
    "telegram_url": ["telegram"],
}


def _profile_dir(project: Path) -> Path:
    spec = json.loads((project / "launch/browser_profile.json").read_text())
    d = Path.home() / "hermes_chrome_profiles" / spec["profile_name"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _context(pw, project: Path):
    return pw.chromium.launch_persistent_context(str(_profile_dir(project)), channel="chrome", headless=False,
                                                 no_viewport=True, args=["--no-first-run"])


def cmd_open(project: Path) -> None:
    from playwright.sync_api import sync_playwright

    spec = json.loads((project / "launch/browser_profile.json").read_text())
    with sync_playwright() as pw:
        ctx = _context(pw, project)
        for url in spec["bookmarks"].values():
            ctx.new_page().goto(url)
        dep = project / "website/deployment.json"
        if dep.exists():
            ctx.new_page().goto(json.loads(dep.read_text())["url"])
        print(f"Profile {spec['profile_name']} open. Complete Phantom/X steps yourself; close the window when done.")
        ctx.pages[0].wait_for_event("close", timeout=0)
        ctx.close()


def _find(page, keys: list[str]):
    """Locate a text input/textarea by label, placeholder, name or id."""
    for k in keys:
        for loc in (page.get_by_label(re.compile(k, re.I)), page.get_by_placeholder(re.compile(k, re.I))):
            if loc.count() == 1:
                return loc
        css = ", ".join(f"{t}[name*='{k.split()[0]}' i], {t}[id*='{k.split()[0]}' i]" for t in ("input", "textarea"))
        loc = page.locator(css)
        if loc.count() == 1:
            return loc
    return None


def cmd_prefill(project: Path) -> None:
    from playwright.sync_api import sync_playwright

    meta = json.loads((project / "launch/metadata.json").read_text())
    status: dict = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "fields": {}, "unmatched": []}
    with sync_playwright() as pw:
        ctx = _context(pw, project)
        page = ctx.new_page()
        page.goto(meta["platform_url"], wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        # reveal optional link fields if the form hides them (only clicks non-submitting toggles)
        for txt in ("more options", "show more", "add social"):
            t = page.get_by_text(re.compile(txt, re.I))
            if t.count() == 1 and not FORBIDDEN_CLICK.search(t.inner_text()):
                t.click()
                page.wait_for_timeout(500)
        for key, labels in FIELDS.items():
            val = meta.get(key)
            if not val:
                continue
            loc = _find(page, labels)
            if loc is None:
                status["unmatched"].append(key)
                continue
            loc.fill(str(val))
            back = loc.input_value()
            status["fields"][key] = {"expected": val, "read_back": back, "ok": back == str(val)}
        fi = page.locator("input[type=file]")
        if fi.count() >= 1:
            fi.first.set_input_files(str(project / meta["image"]))
            n = fi.first.evaluate("e => e.files.length")
            status["fields"]["image"] = {"ok": n == 1}
        else:
            status["unmatched"].append("image")
        page.screenshot(path=str(project / "launch/form_prefill.png"), full_page=True)
        ok = (not status["unmatched"]) and all(f["ok"] for f in status["fields"].values())
        status["status"] = "prefilled_verified" if ok else "prefilled_with_issues"
        (project / "launch/form_status.json").write_text(json.dumps(status, indent=2))
        print(json.dumps(status, indent=2))
        print("\nForm left open for your review. Hermes did NOT click Create. Approve in Phantom only if everything matches.")
        page.wait_for_event("close", timeout=0)
        ctx.close()


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("open", "prefill"):
        print(__doc__)
        raise SystemExit(2)
    project = Path(sys.argv[2]).resolve()
    (cmd_open if sys.argv[1] == "open" else cmd_prefill)(project)


if __name__ == "__main__":
    main()
