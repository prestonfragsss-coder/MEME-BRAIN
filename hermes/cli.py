"""Command interface (SOP section 8). Any chat bot (e.g. a Hermes Telegram agent) can shell out to these.

  hermes build "auto" | "<url>" | "theme: ... | vibe: ..."
  hermes ideas
  hermes status
  hermes preview <project>
  hermes revise <project> "<instructions>"
  hermes wallet <project> [set <PUBLIC_ADDRESS>]
  hermes set-x <project> <handle>        hermes set-telegram <project> <url>
  hermes set-ca <project> <CONTRACT>     hermes launch <project> --dev-buy <SOL>
  hermes launchready <project>
  hermes pause <project> | resume <project>

Add --json for machine-readable output.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys

from hermes.config import get_settings
from hermes.orchestrator import Pipeline, start
from hermes.report import handoff, status_all
from hermes.safety import find_secret, is_solana_public_address
from hermes.workspace import Workspace


def _out(args, payload: dict | str) -> None:
    if args.json:
        print(json.dumps(payload if isinstance(payload, dict) else {"text": payload}, indent=2))
    else:
        print(payload["report"] if isinstance(payload, dict) and "report" in payload else
              payload if isinstance(payload, str) else json.dumps(payload, indent=2))


def _operator(ws: Workspace, **kv) -> dict:
    d = ws.read_json("launch/operator.json") if ws.exists("launch/operator.json") else {}
    d.update(kv)
    ws.write_json("launch/operator.json", d)
    return d


def _invalidate(ws: Workspace, *task_ids: str) -> None:
    for t in task_ids:
        if ws.task(t):
            ws.update_task(t, ws.task(t).agent, status="pending", next_action="re-run after operator update")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hermes", description="HERMES LAUNCH OS")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("instruction", nargs="*")
    sub.add_parser("ideas")
    sub.add_parser("status")
    for name in ("preview", "launchready", "pause", "resume"):
        sub.add_parser(name).add_argument("project")
    r = sub.add_parser("revise"); r.add_argument("project"); r.add_argument("instructions")
    w = sub.add_parser("wallet"); w.add_argument("project"); w.add_argument("action", nargs="?"); w.add_argument("address", nargs="?")
    x = sub.add_parser("set-x"); x.add_argument("project"); x.add_argument("handle")
    t = sub.add_parser("set-telegram"); t.add_argument("project"); t.add_argument("url")
    c = sub.add_parser("set-ca"); c.add_argument("project"); c.add_argument("address")
    ia = sub.add_parser("import-assets", help="import images generated in ChatGPT")
    ia.add_argument("project"); ia.add_argument("folder", nargs="?", help="folder of <key>.png files (default: project inbox)")
    lp = sub.add_parser("launch"); lp.add_argument("project"); lp.add_argument("--dev-buy", type=float, required=True)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s", stream=sys.stderr)

    # Refuse secret material anywhere on the command line before doing anything else.
    reason = find_secret(" ".join(sys.argv[1:] if argv is None else argv))
    if reason:
        print(f"Refused: input looks like wallet secret material ({reason}). Never share seed phrases or private keys.", file=sys.stderr)
        return 2

    s = get_settings()
    if args.cmd == "build":
        p = start("/build " + " ".join(args.instruction or ["auto"]), settings=s)
        _out(args, p.run())
        return 0
    if args.cmd == "ideas":
        p = start("/build auto", settings=s)
        p.step("research", "market", p.p1_2_discovery)
        md = p.ws.path("strategy/market_research.md")
        _out(args, md.read_text() if md.exists() else "research failed: see status")
        return 0
    if args.cmd == "status":
        _out(args, status_all(s.launches_dir))
        return 0

    ws = Workspace.load(s.launches_dir, args.project)
    if args.cmd == "preview":
        parts = []
        for rel in ("strategy/creative_brief.md", "brand/brand_guide.md", "social/ten_posts.md", "HANDOFF.md"):
            if ws.exists(rel):
                parts.append(ws.path(rel).read_text())
        _out(args, "\n\n---\n\n".join(parts) or "nothing produced yet")
    elif args.cmd == "pause":
        st = ws.load_state(); st.paused = True; ws.save_state(st)
        _out(args, f"{ws.project_id} paused")
    elif args.cmd == "resume":
        st = ws.load_state(); st.paused = False; ws.save_state(st)
        _out(args, Pipeline(ws, settings=s).run())
    elif args.cmd == "launchready":
        _out(args, Pipeline(ws, settings=s).run())
    elif args.cmd == "revise":
        st = ws.load_state(); st.notes.append(f"revision: {args.instructions}"); ws.save_state(st)
        p = Pipeline(ws, settings=s)
        fb = f"Operator revision (keep the approved brand identity unless told otherwise): {args.instructions}"
        p.step("site_copy", "website", lambda: p.p4_copy(fb), ("brand",), force=True)
        p.step("social", "social", lambda: p.p4_social(fb), ("brand",), force=True)
        _invalidate(ws, "website", "launch", "qa")
        _out(args, p.run())
    elif args.cmd == "wallet":
        if args.action == "set":
            if not args.address or not is_solana_public_address(args.address):
                print("Not a valid Solana PUBLIC address. Never send a seed phrase or private key.", file=sys.stderr)
                return 2
            from hermes.agents import ops
            from hermes.agents.common import Ctx
            rec = ops.register_wallet(Ctx(ws=ws, llm=None, settings=s), args.address)  # type: ignore[arg-type]
            _invalidate(ws, "wallet", "launch")
            _out(args, rec)
        else:
            d = ws.read_json("wallet/public_address.json") if ws.exists("wallet/public_address.json") else {}
            _out(args, d or {"status": "not registered", "setup": str(ws.path("wallet/SETUP.md"))})
    elif args.cmd == "set-x":
        h = args.handle.lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9_]{4,15}", h):
            print("invalid X handle", file=sys.stderr); return 2
        _operator(ws, x_handle=h); _invalidate(ws, "x_account", "website", "launch", "qa")
        _out(args, f"X handle set to @{h}; run `hermes resume {ws.project_id}` to redeploy links")
    elif args.cmd == "set-telegram":
        if not args.url.startswith("https://t.me/"):
            print("expected https://t.me/... URL", file=sys.stderr); return 2
        _operator(ws, telegram_url=args.url); _invalidate(ws, "website", "launch", "qa")
        _out(args, "telegram link set")
    elif args.cmd == "set-ca":
        if not is_solana_public_address(args.address):
            print("invalid contract address", file=sys.stderr); return 2
        _operator(ws, contract_address=args.address); _invalidate(ws, "website", "qa")
        _out(args, Pipeline(ws, settings=s).run())
    elif args.cmd == "import-assets":
        import shutil
        from pathlib import Path

        from hermes.agents.visual import INBOX, REQ_BY_KEY
        inbox = ws.path(INBOX); inbox.mkdir(parents=True, exist_ok=True)
        if args.folder:
            for f in Path(args.folder).expanduser().iterdir():
                if f.stem in REQ_BY_KEY and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    shutil.copy(f, inbox / f.name)
        _invalidate(ws, "visual", "website", "launch", "qa")
        _out(args, Pipeline(ws, settings=s).run())
    elif args.cmd == "launch":
        if args.dev_buy < 0:
            print("dev buy must be >= 0", file=sys.stderr); return 2
        _operator(ws, dev_buy_sol=args.dev_buy); _invalidate(ws, "launch")
        _out(args, f"dev buy recorded: {args.dev_buy} SOL (Hermes will not execute it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
