"""Language profiles and pair settings from the admin screen (Phase 5).

The profile files in ``certiflow/profiles/data`` stay the defaults (git-tracked); admin changes go to an override file
in the data directory (``profiles.set_override``). Only existing languages can be tuned here: a new language also
needs its font and OCR pack on the server, which is a deployment task."""
from __future__ import annotations

import json
import threading
from typing import Any

from .. import profiles as pf
from ..fonts import available

LOCK = threading.Lock()
TEXT_FIELDS = ("style_guide", "name_rule", "transliteration_standard", "vision_notes")   # reach the prompts
LAYOUT_FIELDS = ("word_font", "pdf_font", "pdf_font_fallback", "body_size_pt", "heading_scale", "line_spacing",
                 "justify", "digit_style", "quote_marks")
EDITABLE = LAYOUT_FIELDS + TEXT_FIELDS
RANGES = {"body_size_pt": (8, 20), "heading_scale": (1.0, 2.0), "line_spacing": (0.8, 2.0)}
PAIR_FIELDS = ("template_id", "conventions", "no_foreign_script", "transliteration_standard")


class LanguageError(ValueError):
    pass


def _write(ov: dict) -> None:
    p = pf.override_path()
    if p is None:
        raise LanguageError("no settings file configured")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ov, indent=2, ensure_ascii=False) + "\n", "utf-8")
    tmp.replace(p)


def view() -> dict:
    ov = pf.read_override()
    langs = []
    for prof in sorted(pf.all_profiles(), key=lambda x: x.display_name):
        cur = prof.model_dump(mode="json")
        langs.append({"code": prof.code, "display_name": prof.display_name, "native_name": prof.native_name,
                      "direction": prof.direction.value, "script": prof.script, "ocr_pack": prof.ocr_pack,
                      "values": {k: cur[k] for k in EDITABLE}, "default": {k: pf.base_profile(prof.code).get(k)
                                                                            for k in EDITABLE},
                      "overridden": sorted((ov.get("profiles") or {}).get(prof.code, {}).keys()),
                      "pdf_font_installed": available(prof.pdf_font),
                      "fallback_installed": bool(prof.pdf_font_fallback) and available(prof.pdf_font_fallback)})
    base = {(x["source"], x["target"]) for x in pf.base_pairs()}
    pairs = [{**p.model_dump(include=set(PAIR_FIELDS) | {"source", "target"}), "in_defaults": k in base,
              "overridden": any((x["source"], x["target"]) == k for x in ov.get("pairs") or [])}
             for k, p in sorted(pf._load_pairs().items())]
    return {"languages": langs, "pairs": pairs, "editable": list(EDITABLE), "text_fields": list(TEXT_FIELDS)}


def _clean(field: str, v: Any) -> Any:
    if field in RANGES:
        lo, hi = RANGES[field]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
            raise LanguageError(f"{field} must be between {lo} and {hi}")
        return v
    if field == "justify":
        if not isinstance(v, bool):
            raise LanguageError("justify must be true or false")
        return v
    if field == "quote_marks":
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) and 0 < len(x) <= 3 for x in v)):
            raise LanguageError("quote marks: an opening and a closing mark")
        return v
    if field == "pdf_font_fallback" and (v is None or v == ""):
        return None
    if field == "transliteration_standard" and (v is None or v == ""):
        return None
    if not isinstance(v, str):
        raise LanguageError(f"{field} must be text")
    v = v.strip()
    if field in ("word_font", "pdf_font") and not v:
        raise LanguageError(f"{field} cannot be empty")
    return v[:4000]


def set_profile(code: str, values: dict) -> dict:
    """Store the given fields (only those that differ from the profile file). Returns {field: [old, new]}."""
    unknown = set(values) - set(EDITABLE)
    if unknown:
        raise LanguageError(f"cannot change {', '.join(sorted(unknown))} here")
    try:
        base = pf.base_profile(code)
    except FileNotFoundError:
        raise KeyError(code) from None
    clean = {k: _clean(k, v) for k, v in values.items()}
    with LOCK:
        cur = pf.get_profile(code).model_dump(mode="json")
        ov = pf.read_override()
        mine = {**(ov.get("profiles") or {}).get(code, {}), **clean}
        mine = {k: v for k, v in mine.items() if base.get(k) != v}
        pf.LanguageProfile.model_validate({**base, **mine})          # whole profile still valid
        ov.setdefault("profiles", {})[code] = mine
        if not mine:
            ov["profiles"].pop(code)
        _write(ov)
        return {k: [cur.get(k), v] for k, v in clean.items() if cur.get(k) != v and k not in TEXT_FIELDS} | \
            {k: "changed" for k, v in clean.items() if cur.get(k) != v and k in TEXT_FIELDS}


def reset_profile(code: str) -> None:
    with LOCK:
        ov = pf.read_override()
        (ov.get("profiles") or {}).pop(code, None)
        _write(ov)


def set_pair(source: str, target: str, values: dict, template_ids: set[str]) -> None:
    codes = {p.code for p in pf.all_profiles()}
    if source not in codes or target not in codes or source == target:
        raise LanguageError("choose two different languages")
    unknown = set(values) - set(PAIR_FIELDS)
    if unknown:
        raise LanguageError(f"cannot change {', '.join(sorted(unknown))} here")
    tpl = values.get("template_id") or None
    if tpl and tpl not in template_ids:
        raise LanguageError("no such active template")
    nfs = values.get("no_foreign_script")
    if nfs is not None and not isinstance(nfs, bool):
        raise LanguageError("no_foreign_script must be true, false or empty")
    item = {"source": source, "target": target, "template_id": tpl,
            "conventions": str(values.get("conventions") or "").strip()[:4000],
            "no_foreign_script": nfs,
            "transliteration_standard": (str(values.get("transliteration_standard") or "").strip()[:500] or None)}
    existing = pf._load_pairs().get((source, target))
    if existing and existing.agent_models:
        item["agent_models"] = existing.agent_models                  # kept as it is (not edited here)
    pf.PairSettings.model_validate(item)
    with LOCK:
        ov = pf.read_override()
        pairs = [x for x in ov.get("pairs") or [] if (x["source"], x["target"]) != (source, target)]
        ov["pairs"] = pairs + [item]
        _write(ov)


def reset_pair(source: str, target: str) -> None:
    """Back to the default pair settings (or no settings for a pair added here)."""
    with LOCK:
        ov = pf.read_override()
        ov["pairs"] = [x for x in ov.get("pairs") or [] if (x["source"], x["target"]) != (source, target)]
        _write(ov)
