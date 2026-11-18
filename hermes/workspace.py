"""Per-project workspace (SOP section 7), persistent task state (section 9) and project registry."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from pydantic import BaseModel

from hermes.safety import assert_no_secrets

SUBDIRS = [
    "strategy", "brand", "website/source", "website/assets", "social/post_assets",
    "wallet", "launch", "qa",
]

TaskStatus = Literal["pending", "running", "verified", "failed", "blocked", "skipped"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(s: str, n: int = 24) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:n] or "project"


class Task(BaseModel):
    task_id: str
    agent: str
    status: TaskStatus = "pending"
    depends_on: list[str] = []
    attempts: int = 0
    outputs: list[str] = []
    verification: str = ""
    failure_reason: str = ""
    next_action: str = ""
    operator_action: str = ""   # set when blocked on a human step
    updated_at: str = ""


class ProjectState(BaseModel):
    project_id: str
    created_at: str
    request: dict[str, Any]
    name: str = ""
    ticker: str = ""
    paused: bool = False
    phase: str = "discovery"
    tasks: dict[str, Task] = {}
    launch_ready: bool = False
    notes: list[str] = []


class Workspace:
    def __init__(self, root: Path):
        self.root = root

    # -- creation / loading
    @classmethod
    def create(cls, launches_dir: Path, request: dict[str, Any], label: str = "pending") -> "Workspace":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        pid = f"{stamp}_{slug(label)}"
        ws = cls(launches_dir / pid)
        for d in SUBDIRS:
            (ws.root / d).mkdir(parents=True, exist_ok=True)
        ws.save_state(ProjectState(project_id=pid, created_at=now_iso(), request=request))
        Registry(launches_dir).add(pid)
        return ws

    @classmethod
    def load(cls, launches_dir: Path, project: str) -> "Workspace":
        matches = Registry(launches_dir).find(project)
        if not matches:
            raise FileNotFoundError(f"no project matching {project!r}")
        if len(matches) > 1:
            raise ValueError(f"ambiguous project {project!r}: {', '.join(matches)}")
        return cls(launches_dir / matches[0])

    # -- files (all writes go through the secret guard)
    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError(f"path escapes workspace: {rel}")
        return p

    def write_text(self, rel: str, text: str) -> Path:
        assert_no_secrets(text, rel)
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)
        return p

    def write_json(self, rel: str, data: Any) -> Path:
        if isinstance(data, BaseModel):
            data = data.model_dump(mode="json")
        return self.write_text(rel, json.dumps(data, indent=2, ensure_ascii=False))

    def write_bytes(self, rel: str, data: bytes) -> Path:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def read_json(self, rel: str) -> Any:
        return json.loads(self.path(rel).read_text(encoding="utf-8"))

    def exists(self, rel: str) -> bool:
        return self.path(rel).exists()

    # -- state
    def load_state(self) -> ProjectState:
        return ProjectState.model_validate(self.read_json("status.json"))

    def save_state(self, st: ProjectState) -> None:
        self.write_json("status.json", st)

    def update_task(self, task_id: str, agent: str, **fields: Any) -> Task:
        with self.lock("state"):
            st = self.load_state()
            t = st.tasks.get(task_id) or Task(task_id=task_id, agent=agent)
            for k, v in fields.items():
                setattr(t, k, v)
            t.updated_at = now_iso()
            st.tasks[task_id] = t
            self.save_state(st)
            return t

    def task(self, task_id: str) -> Task | None:
        return self.load_state().tasks.get(task_id)

    # -- locks: one writer per live resource (browser, wallet, launch form, state)
    @contextlib.contextmanager
    def lock(self, resource: str) -> Iterator[None]:
        lp = self.root / f".lock_{resource}"
        with open(lp, "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    @property
    def project_id(self) -> str:
        return self.root.name


class Registry:
    def __init__(self, launches_dir: Path):
        self.dir = launches_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "registry.json"

    def _read(self) -> list[str]:
        return json.loads(self.file.read_text()) if self.file.exists() else []

    def add(self, pid: str) -> None:
        ids = self._read()
        if pid not in ids:
            ids.append(pid)
            self.file.write_text(json.dumps(ids, indent=2))

    def all(self) -> list[str]:
        return [p for p in self._read() if (self.dir / p / "status.json").exists()]

    def find(self, q: str) -> list[str]:
        ids = self.all()
        if q in ids:
            return [q]
        ql = q.lower().lstrip("$")
        hits = [p for p in ids if ql in p.lower()]
        if not hits:
            for p in ids:
                st = json.loads((self.dir / p / "status.json").read_text())
                if ql in (st.get("ticker", "").lower(), st.get("name", "").lower()):
                    hits.append(p)
        return hits
