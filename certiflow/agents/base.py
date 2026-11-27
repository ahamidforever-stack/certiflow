"""Shared agent machinery: versioned prompt files, language placeholders,
the model call, and one audit record per call."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from ..llm.client import Image, LLMClient, LLMRequest, LLMResult, SystemBlock
from ..model import GlossaryEntry
from ..profiles import ResolvedPair
from ..settings import Settings

PROMPTS = Path(__file__).parent / "prompts"


class _Safe(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def load_prompt(agent: str, version: str) -> str:
    p = PROMPTS / agent / f"{version}.md"
    if not p.exists():
        raise FileNotFoundError(f"prompt {agent}/{version}.md not found")
    return p.read_text("utf-8")


def common_rules(version: str = "v1") -> str:
    return (PROMPTS / f"common_rules.{version}.md").read_text("utf-8")


def glossary_text(glossary: list[GlossaryEntry]) -> str:
    items = sorted((g for g in glossary if g.confirmed), key=lambda g: g.source.lower())
    if not items:
        return "(none yet)"
    return "\n".join(f"- {g.source} => {g.target} ({g.kind})" for g in items)


class AuditLog:
    """Append-only JSONL audit per job (lives with the job's confidential files)."""

    def __init__(self, path: Optional[Path]):
        self.path = path
        self.records: list[dict] = []
        self._lock = threading.Lock()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, rec: dict) -> None:
        with self._lock:
            self.records.append(rec)
            if self.path:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def totals(self) -> dict:
        out: dict[str, dict] = {}
        for r in self.records:
            if r.get("kind") != "llm_call":
                continue
            a = out.setdefault(r["agent"], {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                            "cache_read_input_tokens": 0, "cost_usd": 0.0, "seconds": 0.0})
            a["calls"] += 1
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
                a[k] += r["usage"].get(k, 0)
            a["cost_usd"] += r["cost_usd"]
            a["seconds"] += r["latency_s"]
        return out


@dataclass
class AgentContext:
    pair: ResolvedPair
    settings: Settings
    client: LLMClient
    audit: AuditLog
    glossary: list[GlossaryEntry] = field(default_factory=list)
    job_id: str = ""
    document_id: str = ""


def lang_vars(ctx: AgentContext) -> dict[str, str]:
    p = ctx.pair
    foreign = ""
    if p.no_foreign_script:
        foreign = (f"The {p.target.display_name} text must not contain {p.source.display_name}-script words next to the "
                   f"translation; transliterate or translate them. Only identifiers stay in their original script.")
    return {
        "source_language": p.source.display_name,
        "target_language": p.target.display_name,
        "style_guide": p.target.style_guide,
        "name_rule": p.target.name_rule if not p.same_script else
        "Source and target share a script: keep names exactly as written; translate only descriptive parts.",
        "transliteration_standard": p.transliteration_standard or "not applicable (same script)",
        "foreign_script_rule": foreign,
        "pair_conventions": f"Conventions for this language pair: {p.conventions}" if p.conventions else "",
        "glossary": glossary_text(ctx.glossary),
        "rules": common_rules(),
    }


def call_agent(ctx: AgentContext, agent: str, output: type[BaseModel], payload: Any,
               images: list[Image] | None = None, extra_vars: dict | None = None,
               instruction: str = "") -> LLMResult:
    st = ctx.settings.agent(agent)
    system_text = load_prompt(agent, st.prompt_version).format_map(_Safe({**lang_vars(ctx), **(extra_vars or {})}))
    user_text = (instruction + "\n\n" if instruction else "") + json.dumps(payload, ensure_ascii=False, indent=1)
    req = LLMRequest(agent=agent, system=[SystemBlock(system_text, cache=True)], user_text=user_text,
                     output=output, model=st.model, effort=st.effort, max_tokens=st.max_tokens,
                     images=images or [], payload=payload, prompt_version=st.prompt_version)
    t0 = time.time()
    try:
        res = ctx.client.call(req)
    except Exception as e:
        ctx.audit.record({"kind": "llm_error", "at": _now(), "job": ctx.job_id, "document": ctx.document_id,
                          "agent": agent, "model": st.model, "prompt_version": st.prompt_version,
                          "error": f"{type(e).__name__}: {e}"[:500], "latency_s": round(time.time() - t0, 2)})
        raise
    ctx.audit.record({
        "kind": "llm_call", "at": _now(), "job": ctx.job_id, "document": ctx.document_id, "agent": agent,
        "model": res.model, "prompt_version": st.prompt_version, "effort": st.effort, "usage": res.usage,
        "cost_usd": round(ctx.settings.cost(res.model, res.usage), 6), "latency_s": round(res.latency_s, 2),
        "retries": res.retries, "request_id": res.request_id,
        "prompt": {"system_chars": len(system_text), "user": user_text}, "response": res.raw_text,
    })
    return res


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
