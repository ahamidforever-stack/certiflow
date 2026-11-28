"""Agent and pipeline settings (config/agents.json, override with CERTIFLOW_SETTINGS)."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "agents.json"


class AgentSettings(BaseModel):
    model: str
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    max_tokens: int = 16000
    prompt_version: str = "v1"


class Price(BaseModel):
    input: float
    output: float
    cache_read: float = 0.0
    cache_write: float = 0.0


class PipelineSettings(BaseModel):
    chunk_blocks: int = 40
    chunk_max_pages: int = 20               # a translation unit never spans more source pages than this
    context_overlap_blocks: int = 3
    qa_max_loops: int = 2
    validation_retries: int = 2
    ocr_dpi: int = 300
    vision_dpi: int = 150
    zoom_conf_threshold: int = 70
    max_parallel_documents: int = 3


class Settings(BaseModel):
    agents: dict[str, AgentSettings]
    fallbacks: Optional[str] = "default"
    pricing_per_mtok: dict[str, Price] = Field(default_factory=dict)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)

    def agent(self, name: str) -> AgentSettings:
        if name not in self.agents:
            raise KeyError(f"no settings for agent '{name}' in config")
        return self.agents[name]

    def cost(self, model: str, usage: dict) -> float:
        p = self.pricing_per_mtok.get(model)
        if not p:
            return 0.0
        return (usage.get("input_tokens", 0) * p.input + usage.get("output_tokens", 0) * p.output
                + usage.get("cache_read_input_tokens", 0) * p.cache_read
                + usage.get("cache_creation_input_tokens", 0) * p.cache_write) / 1e6


_override: Optional[Path] = None


def set_override(path: Optional[Path]) -> None:
    """Admin changes from the web app live in a separate file (data/settings/agents.json) that overlays the
    defaults in config/agents.json, so the git-tracked file is never written by the app."""
    global _override
    _override = Path(path) if path else None


def override_path() -> Optional[Path]:
    return _override


def read_override() -> dict:
    p = _override
    if p is None or not p.exists():
        return {}
    return json.loads(p.read_text("utf-8"))


def defaults(path: str | None = None) -> dict:
    p = Path(path or os.environ.get("CERTIFLOW_SETTINGS") or DEFAULT_PATH)
    data = json.loads(p.read_text("utf-8"))
    data.pop("_comment", None)
    return data


def load(path: str | None = None) -> Settings:
    p = str(Path(path or os.environ.get("CERTIFLOW_SETTINGS") or DEFAULT_PATH))
    ov = _override
    stamp = ov.stat().st_mtime_ns if ov is not None and ov.exists() else 0
    return _load(p, str(ov) if stamp else "", stamp)


@lru_cache(maxsize=8)
def _load(path: str, override: str, _mtime: int) -> Settings:
    data = defaults(path)
    if override:
        ov = json.loads(Path(override).read_text("utf-8"))
        for name, fields in (ov.get("agents") or {}).items():
            if name in data["agents"]:
                data["agents"][name] = {**data["agents"][name], **fields}
        data["pipeline"] = {**data.get("pipeline", {}), **(ov.get("pipeline") or {})}
    return Settings.model_validate(data)
