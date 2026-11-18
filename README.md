# MEME-BRAIN — HERMES LAUNCH OS engine

Turns one instruction into a researched, branded, launch-ready Solana token project: market research → scored concept →
creative brief → brand system → visual assets → live website → X profile + 10 posts → wallet/launch prep → QA → handoff.

It is a CLI + Python package with no chat front end, so any orchestrator (e.g. a Hermes Telegram agent) can shell out to
`hermes … --json`.

**It never launches, signs, funds, or touches seed phrases.** You make the final Create click and Phantom approval yourself.

## Setup

```bash
pip install -e '.[dev]'          # server side
cp .env.example .env             # fill in keys, then: set -a; . ./.env; set +a
```

| Variable | Needed for |
|---|---|
| `ANTHROPIC_API_KEY` | all agents (Claude, web search) |
| `NETLIFY_AUTH_TOKEN` | website hosting (HTTPS) |
| `OPENAI_API_KEY` | *optional* — automatic image generation via the API |
| `HERMES_IMAGE_SOURCE` | `auto` (default), `api`, or `chatgpt` |

### Images with a ChatGPT subscription
A ChatGPT Plus/Pro plan does **not** include API access, so without `OPENAI_API_KEY` Hermes uses the import flow:
1. Hermes writes `launches/<project>/brand/IMAGE_PROMPTS.md`, with one prompt per asset, the aspect ratio to request, and the filename to save as.
2. Generate each image in ChatGPT and save it as `<key>.png` in a folder.
3. Run `hermes import-assets <project> <folder>`. Hermes crops each image to the exact size, has Claude review it for defects, accepts
   it or marks it for a redo (with reasons), and continues the pipeline.

## Commands

```bash
hermes build auto                                   # Mode C: full autonomy
hermes build https://example.com                    # Mode A: reference site
hermes build "theme: viral AI lobster | vibe: absurd luxury | style: cinematic"   # Mode B
hermes build "https://example.com | find the best current meme meta | surprise me"  # Mode D
hermes ideas                     # five researched, scored opportunities
hermes status                    # all projects
hermes preview  <project>        # brief, brand guide, posts, handoff
hermes revise   <project> "make the hero copy funnier"
hermes import-assets <project> [folder]
hermes set-x    <project> <handle>          # after you create the X account
hermes wallet   <project> set <PUBLIC_ADDRESS>   # public address only
hermes launch   <project> --dev-buy 0.5     # records your decision; does not execute
hermes launchready <project>                # re-validate + handoff
hermes set-ca   <project> <CONTRACT>        # after YOU launch: publishes CA on the site
hermes pause|resume <project>
```
`<project>` accepts the project id, any unique part of it, the ticker or the name. Add `--json` for machine output.

### On your own computer (browser steps)
```bash
pip install -e '.[local]' && playwright install chrome
python -m hermes.local.browser open    launches/<project>   # dedicated Chrome profile LAUNCH_YYYYMMDD_NAME_TICKER
python -m hermes.local.browser prefill launches/<project>   # fills pump.fun form, reads values back, never clicks Create
```
In that window you install Phantom from phantom.com, create the wallet and back it up offline, and create the X account
yourself (including CAPTCHA and phone verification). Each project gets its own Chrome profile for isolation. There is no fingerprint spoofing or proxy rotation.

## How it works

| SOP agent | Code |
|---|---|
| 01 Market Intelligence, 02 Meta Strategist | `hermes/agents/research.py`: Claude web search, five candidates. Any cited URL that the search never returned is deleted. Live DexScreener lookup for competing tokens. |
| Scoring (100 pts, ≥80) | `hermes/scoring.py`: weights as in the SOP. Blocking concerns veto a concept. If nothing qualifies, the run stops. |
| 03 Creative, 04 Brand | `hermes/agents/creative.py`: brief, brand system, name/ticker conflict check (up to 3 renames) |
| 05 Visual | `hermes/agents/visual.py`: unified spec → 21 assets → Claude vision review → automatic regeneration |
| 06 Website | `hermes/agents/website.py`: copy → static site (8 layout styles) → Netlify → live HTTPS + asset check |
| 07 Social | `hermes/agents/social.py`: profile, pinned post, 10 purpose-specific posts (drafts) |
| 08–10 Browser / Wallet / Launch | `hermes/agents/ops.py`, `hermes/local/browser.py` |
| 11 QA | `hermes/agents/qa.py`: deterministic checks + independent review; problems are sent back to the responsible agent |
| Orchestrator | `hermes/orchestrator.py`: phases 1–7, parallel phase 4, resumable task state |

State lives in `launches/<project>/status.json`. Each task records its id, agent, status, dependencies, attempt count, outputs, verification,
failure reason, next action and any operator action. Re-running only redoes what isn't verified. File locks keep two agents from
writing the same resource at once.

Guardrails (`hermes/safety.py`):
- Every file write is checked for anything shaped like a seed phrase or private key, and refuses it.
- Wallet input must be a valid 32-byte public address.
- Public copy is linted for return promises, fake partnerships, investment framing and placeholder text.

## Tests
```bash
pytest -q     # offline: fake LLM, fake image generator, fake hosting
```
