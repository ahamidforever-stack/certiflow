"""Language Profiles and Language Pair Settings.

Profiles are data (JSON files in ``data/``; moved to the database in Phase 3
with the same schema). Adding a language = adding a profile file, fonts and an
OCR pack. No code change.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..model import Direction

DATA_DIR = Path(__file__).parent / "data"


class Labels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note_open: str = "//"
    note_close: str = "//"
    unreadable_illegible: str
    unreadable_covered_by_stamp: str
    unreadable_truncated: str
    repeated_notes_heading: str            # heading for stamps/signatures repeated on every page


class LanguageProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str                               # BCP-47 primary tag
    display_name: str
    native_name: str
    script: Literal["Latn", "Arab", "Hebr", "Cyrl", "Grek", "Hans", "Hant", "Jpan", "Kore", "Deva"]
    direction: Direction
    word_tag: str                           # w:lang value, e.g. "ar-AE", "en-GB"
    font_slot: Literal["ascii", "cs", "eastAsia"]  # which w:rFonts slot carries this script
    word_font: str
    pdf_font: str                           # font used for the PDF build (must be installed on the server)
    pdf_font_fallback: Optional[str] = None  # used when pdf_font is not installed (e.g. licensed font missing)
    body_size_pt: float = 12
    heading_scale: float = 1.25
    line_spacing: float = 1.15
    justify: bool = True
    digit_style: Literal["as_source", "western", "eastern_arabic", "persian"] = "as_source"
    quote_marks: tuple[str, str] = ("“", "”")
    list_style: str = "as_source"
    transliteration_standard: Optional[str] = None
    name_rule: str = ""
    no_foreign_script: bool = False        # target must not contain source-script text (identifiers excepted)
    ocr_pack: str                           # tesseract language code
    vision_notes: str = ""
    style_guide: str                        # injected into Translator / Proofreader / QA prompts
    labels: Labels


class PairSettings(BaseModel):
    """Optional per-pair overrides (source -> target)."""
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    template_id: Optional[str] = None
    transliteration_standard: Optional[str] = None
    no_foreign_script: Optional[bool] = None
    agent_models: dict[str, str] = Field(default_factory=dict)
    conventions: str = ""


class ResolvedPair(BaseModel):
    source: LanguageProfile
    target: LanguageProfile
    template_id: Optional[str]
    transliteration_standard: Optional[str]
    no_foreign_script: bool
    same_script: bool
    agent_models: dict[str, str]
    conventions: str


# Admin changes from the web app live in a separate file (data/settings/languages.json) laid over the profile
# files here, so the git-tracked data is never written by the app:
#   {"profiles": {"ar": {"body_size_pt": 13, ...}}, "pairs": [{"source": "en", "target": "ar", ...}]}
# A pair in the override replaces the pair with the same source and target.
_override: Optional[Path] = None


def set_override(path: Optional[Path]) -> None:
    global _override
    _override = Path(path) if path else None


def override_path() -> Optional[Path]:
    return _override


def read_override() -> dict:
    return json.loads(_override.read_text("utf-8")) if _override is not None and _override.exists() else {}


def _stamp() -> tuple[str, int]:
    ov = _override
    return (str(ov), ov.stat().st_mtime_ns) if ov is not None and ov.exists() else ("", 0)


def base_profile(code: str) -> dict:
    return json.loads((DATA_DIR / f"{code}.json").read_text(encoding="utf-8"))


def base_pairs() -> list[dict]:
    f = DATA_DIR / "pairs.json"
    return json.loads(f.read_text("utf-8")) if f.exists() else []


def _load_all() -> dict[str, LanguageProfile]:
    return _profiles(*_stamp())


def _load_pairs() -> dict[tuple[str, str], PairSettings]:
    return _pairs(*_stamp())


@lru_cache(maxsize=8)
def _profiles(override: str, _mtime: int) -> dict[str, LanguageProfile]:
    ov = (json.loads(Path(override).read_text("utf-8")).get("profiles") or {}) if override else {}
    out = {}
    for p in sorted(DATA_DIR.glob("*.json")):
        if p.name == "pairs.json":
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        data.update(ov.get(data["code"], {}))
        prof = LanguageProfile.model_validate(data)
        out[prof.code] = prof
    return out


@lru_cache(maxsize=8)
def _pairs(override: str, _mtime: int) -> dict[tuple[str, str], PairSettings]:
    items = {(x["source"], x["target"]): x for x in base_pairs()}
    if override:
        for x in json.loads(Path(override).read_text("utf-8")).get("pairs") or []:
            items[(x["source"], x["target"])] = x
    return {k: PairSettings.model_validate(v) for k, v in items.items()}


def get_profile(code: str) -> LanguageProfile:
    try:
        return _load_all()[code]
    except KeyError:
        raise KeyError(f"no language profile for '{code}'; add certiflow/profiles/data/{code}.json") from None


def all_profiles() -> list[LanguageProfile]:
    return list(_load_all().values())


def resolve_pair(source: str, target: str) -> ResolvedPair:
    s, t = get_profile(source), get_profile(target)
    o = _load_pairs().get((source, target))
    same_script = s.script == t.script
    return ResolvedPair(
        source=s,
        target=t,
        template_id=o.template_id if o else None,
        transliteration_standard=(o.transliteration_standard if o and o.transliteration_standard else
                                  (None if same_script else t.transliteration_standard)),
        no_foreign_script=(o.no_foreign_script if o and o.no_foreign_script is not None else t.no_foreign_script),
        same_script=same_script,
        agent_models=o.agent_models if o else {},
        conventions=o.conventions if o else "",
    )
