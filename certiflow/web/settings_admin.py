"""Model and pipeline settings from the admin screen (Phase 5).

Defaults stay in the git-tracked ``config/agents.json``; admin changes are written to an override file in the data
directory (``WebConfig.settings_override``), which ``certiflow.settings.load`` lays over the defaults. New pipeline
steps pick up a change at once (the loader re-reads the file when it changes)."""
from __future__ import annotations

import json
import re
import threading

from ..agents.base import PROMPTS
from ..settings import defaults, load, override_path, read_override

LOCK = threading.Lock()
EFFORTS = ("low", "medium", "high", "xhigh", "max")
PIPELINE_FIELDS = {"qa_max_loops": (0, 5), "max_parallel_documents": (1, 8)}


class SettingsError(ValueError):
    pass


def prompt_versions(agent: str) -> list[str]:
    files = (PROMPTS / agent).glob("v*.md")
    return sorted((f.stem for f in files if re.fullmatch(r"v\d+", f.stem)), key=lambda v: int(v[1:]))


def view() -> dict:
    base, ov, st = defaults(), read_override(), load()
    agents = {}
    for name, d in base["agents"].items():
        cur = st.agent(name)
        agents[name] = {"model": cur.model, "effort": cur.effort, "max_tokens": cur.max_tokens,
                        "prompt_version": cur.prompt_version, "default": d,
                        "overridden": sorted((ov.get("agents") or {}).get(name, {}).keys()),
                        "prompt_versions": prompt_versions(name)}
    pipe = {k: getattr(st.pipeline, k) for k in PIPELINE_FIELDS}
    return {"agents": agents, "efforts": list(EFFORTS),
            "models": [{"model": m, **p.model_dump()} for m, p in st.pricing_per_mtok.items()],
            "pipeline": pipe, "pipeline_default": {k: base.get("pipeline", {}).get(k) for k in PIPELINE_FIELDS},
            "pipeline_overridden": sorted((ov.get("pipeline") or {}).keys())}


def _write(ov: dict) -> None:
    p = override_path()
    if p is None:
        raise SettingsError("no settings file configured")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ov, indent=2, ensure_ascii=False) + "\n", "utf-8")
    tmp.replace(p)


def set_agent(name: str, model: str, effort: str, prompt_version: str, max_tokens: int) -> dict:
    """Store the fields that differ from the default; returns {field: [old, new]} for the log."""
    base = defaults()
    if name not in base["agents"]:
        raise KeyError(name)
    if model not in base.get("pricing_per_mtok", {}):
        raise SettingsError("unknown model (it needs a price in config/agents.json)")
    if effort not in EFFORTS:
        raise SettingsError("unknown effort")
    if prompt_version not in prompt_versions(name):
        raise SettingsError("no such prompt version")
    if not 1000 <= max_tokens <= 128000:
        raise SettingsError("max tokens must be between 1000 and 128000")
    with LOCK:
        cur = load().agent(name)
        new = {"model": model, "effort": effort, "prompt_version": prompt_version, "max_tokens": max_tokens}
        changed = {k: [getattr(cur, k), v] for k, v in new.items() if getattr(cur, k) != v}
        ov = read_override()
        diff = {k: v for k, v in new.items() if base["agents"][name].get(k) != v}
        agents = ov.setdefault("agents", {})
        if diff:
            agents[name] = diff
        else:
            agents.pop(name, None)
        _write(ov)
        return changed


def reset_agent(name: str) -> None:
    if name not in defaults()["agents"]:
        raise KeyError(name)
    with LOCK:
        ov = read_override()
        (ov.get("agents") or {}).pop(name, None)
        _write(ov)


def set_pipeline(values: dict[str, int]) -> dict:
    base = defaults().get("pipeline", {})
    for k, v in values.items():
        lo, hi = PIPELINE_FIELDS.get(k, (None, None))
        if lo is None:
            raise SettingsError(f"{k} cannot be changed here")
        if not isinstance(v, int) or not lo <= v <= hi:
            raise SettingsError(f"{k} must be between {lo} and {hi}")
    with LOCK:
        st = load().pipeline
        changed = {k: [getattr(st, k), v] for k, v in values.items() if getattr(st, k) != v}
        ov = read_override()
        pipe = ov.setdefault("pipeline", {})
        for k, v in values.items():
            if base.get(k) == v:
                pipe.pop(k, None)
            else:
                pipe[k] = v
        _write(ov)
        return changed
