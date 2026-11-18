"""Claude client wrapper. Agents depend on the `LLM` protocol so tests can inject a fake."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class Research:
    text: str
    source_urls: set[str] = field(default_factory=set)


class LLMRefused(RuntimeError):
    pass


class LLM(Protocol):
    def research(self, system: str, prompt: str, *, fetch: bool = False, max_searches: int = 12) -> Research: ...
    def structured(self, system: str, prompt: str, schema: type[T], *, images: list[bytes] | None = None,
                   effort: str = "high") -> T: ...


class ClaudeLLM:
    def __init__(self, model: str = "claude-opus-5-5", client: Any = None):
        import anthropic

        self.model = model
        self.client = client or anthropic.Anthropic(max_retries=4)

    def research(self, system: str, prompt: str, *, fetch: bool = False, max_searches: int = 12) -> Research:
        tools: list[dict[str, Any]] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}]
        if fetch:
            tools.append({"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8})
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        urls: set[str] = set()
        texts: list[str] = []
        for _ in range(8):  # resume pause_turn up to 8 times
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=64000,
                system=system,
                messages=messages,
                tools=tools,
                output_config={"effort": "high"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                resp = stream.get_final_message()
            if resp.stop_reason == "refusal":
                raise LLMRefused(str(getattr(resp, "stop_details", "")))
            for b in resp.content:
                if b.type == "text":
                    texts.append(b.text)
                elif b.type == "web_search_tool_result" and isinstance(b.content, list):
                    urls.update(r.url for r in b.content if getattr(r, "url", None))
                elif b.type == "web_fetch_tool_result":
                    u = getattr(b.content, "url", None)
                    if u:
                        urls.add(u)
            if resp.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": resp.content})
        return Research(text="\n".join(texts), source_urls=urls)

    def structured(self, system: str, prompt: str, schema: type[T], *, images: list[bytes] | None = None,
                   effort: str = "high") -> T:
        content: list[dict[str, Any]] = []
        for img in images or []:
            content.append({"type": "image", "source": {"type": "base64", "media_type": _mime(img),
                                                         "data": base64.b64encode(img).decode()}})
        content.append({"type": "text", "text": prompt})
        resp = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=schema,
            output_config={"effort": effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            raise LLMRefused(str(getattr(resp, "stop_details", "")))
        if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
            raise RuntimeError(f"structured output incomplete (stop_reason={resp.stop_reason})")
        return resp.parsed_output


def _mime(b: bytes) -> str:
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"
