from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    launches_dir: Path = field(default_factory=lambda: Path(_env("HERMES_LAUNCHES_DIR", "./launches")).resolve())
    model: str = field(default_factory=lambda: _env("HERMES_MODEL", "claude-opus-5-5"))
    image_model: str = field(default_factory=lambda: _env("HERMES_IMAGE_MODEL", "gpt-image-1"))
    score_threshold: float = field(default_factory=lambda: float(_env("HERMES_SCORE_THRESHOLD", "80")))
    image_source: str = field(default_factory=lambda: _env("HERMES_IMAGE_SOURCE", "auto"))  # auto | api | chatgpt
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    netlify_token: str = field(default_factory=lambda: _env("NETLIFY_AUTH_TOKEN"))
    max_repair_rounds: int = 2
    max_image_attempts: int = 3


def get_settings() -> Settings:
    return Settings()
