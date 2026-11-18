"""Phase 7 launch handoff + status views (SOP 5 phase 7, section 10)."""
from __future__ import annotations

from hermes.workspace import Registry, Workspace

CRITERIA = [
    ("research", "Researched, scored concept"),
    ("brand", "Original, consistent branding"),
    ("visual", "All required visual assets"),
    ("site_copy", "Website copy"),
    ("website", "Website deployed + verified live"),
    ("social", "Ten posts + profile prepared"),
    ("x_account", "X account configured (operator)"),
    ("browser", "Isolated browser workspace spec"),
    ("wallet", "Phantom wallet (operator-controlled) registered"),
    ("launch", "Launch metadata + form prefilled"),
    ("qa", "Quality assurance passed"),
]


def handoff(ws: Workspace) -> dict:
    st = ws.load_state()
    rows, outstanding = [], []
    for tid, label in CRITERIA:
        t = st.tasks.get(tid)
        status = t.status if t else "not started"
        rows.append({"task": tid, "label": label, "status": status})
        if status != "verified":
            outstanding.append(f"{label}: " + ((t.operator_action or t.failure_reason or t.next_action) if t else "not started"))
    ready = not outstanding and st.phase != "no_suitable_concept"
    st.launch_ready = ready
    if ready:
        st.phase = "launch_ready"
    ws.save_state(st)

    def j(rel: str) -> dict:
        return ws.read_json(rel) if ws.exists(rel) else {}

    sel, dep, meta, wal, prof = (j("strategy/selected_candidate.json"), j("website/deployment.json"), j("launch/metadata.json"),
                                 j("wallet/public_address.json"), j("launch/browser_profile.json"))
    lines = [
        f"# Launch handoff — {st.name or '(unnamed)'} {('$' + st.ticker) if st.ticker else ''}",
        "",
        f"**Status:** {'LAUNCH READY' if ready else 'NOT READY'}  ·  phase `{st.phase}`  ·  project `{st.project_id}`",
        "",
        f"**Strategic rationale:** {sel.get('positioning') or sel.get('token_concept') or '—'}"
        + (f" (score {sel['score']['total']})" if sel.get("score") else ""),
        f"**Website:** {dep.get('url') or 'not deployed'}",
        f"**X:** {meta.get('x_url') or 'awaiting operator account creation'} — posts stored as drafts in social/ten_posts.md",
        f"**Browser profile:** {prof.get('profile_name') or '—'}",
        f"**Dev wallet (public):** {wal.get('public_address') or 'not registered'}",
        f"**Platform:** {meta.get('platform') or 'pump.fun'}",
        f"**Funding:** {meta.get('funding_estimate') or '—'}",
        f"**QA:** {(st.tasks.get('qa').status if st.tasks.get('qa') else 'not run')}",
        "",
        "## Checklist",
        *[f"- [{'x' if r['status'] == 'verified' else ' '}] {r['label']} — {r['status']}" for r in rows],
        "",
        "## Outstanding actions",
        *([f"- {o}" for o in outstanding] or ["- none — review the form and launch when you choose"]),
        "",
        "## Assets",
        "brand/token_icon.png · brand/x_avatar.png · brand/x_banner.png · website/assets/* · social/post_assets/*",
        "",
        "_Hermes never launches, signs, or funds. The final Create click and Phantom approval are yours._",
    ]
    if st.phase == "no_suitable_concept":
        lines.insert(2, "**No suitable concept found** — " + "; ".join(st.notes[-1:]))
    text = "\n".join(lines) + "\n"
    ws.write_text("HANDOFF.md", text)
    return {"project_id": st.project_id, "launch_ready": ready, "outstanding": outstanding, "report": text}


def status_all(launches_dir) -> str:
    reg = Registry(launches_dir)
    out = []
    for pid in reg.all():
        st = Workspace(launches_dir / pid).load_state()
        done = sum(1 for t in st.tasks.values() if t.status == "verified")
        blocked = [t.task_id for t in st.tasks.values() if t.status in ("blocked", "failed")]
        out.append(f"{pid}  {st.name or '-'} {('$' + st.ticker) if st.ticker else ''}  phase={st.phase}  "
                   f"{done}/{len(CRITERIA)} verified{'  PAUSED' if st.paused else ''}"
                   + (f"  attention: {', '.join(blocked)}" if blocked else ""))
    return "\n".join(out) or "no projects"
