"""Script detection, run segmentation and bidi isolation.

Language-neutral: everything is driven by a target Direction and the Unicode
properties of the characters, never by a hard-coded language.
"""
from __future__ import annotations

import re
import unicodedata

from .model import Direction, InlineRun, RunKind

LRM, RLM = "‎", "‏"
LRI, RLI, FSI, PDI = "⁦", "⁧", "⁨", "⁩"

# Unicode block ranges per script tag used in Language Profiles.
SCRIPT_RANGES: dict[str, list[tuple[int, int]]] = {
    "Latn": [(0x41, 0x5A), (0x61, 0x7A), (0xC0, 0x24F), (0x1E00, 0x1EFF)],
    "Arab": [(0x600, 0x6FF), (0x750, 0x77F), (0x8A0, 0x8FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)],
    "Hebr": [(0x590, 0x5FF), (0xFB1D, 0xFB4F)],
    "Cyrl": [(0x400, 0x4FF), (0x500, 0x52F)],
    "Grek": [(0x370, 0x3FF)],
    "Deva": [(0x900, 0x97F)],
    "Hans": [(0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x3000, 0x303F)],
    "Hant": [(0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x3000, 0x303F)],
    "Jpan": [(0x3040, 0x30FF), (0x4E00, 0x9FFF), (0x3000, 0x303F)],
    "Kore": [(0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F)],
}


def char_script(ch: str) -> str | None:
    cp = ord(ch)
    for tag, ranges in SCRIPT_RANGES.items():
        if any(a <= cp <= b for a, b in ranges):
            return tag
    return None


def strong_direction(ch: str) -> Direction | None:
    bd = unicodedata.bidirectional(ch)
    if bd in ("R", "AL"):
        return Direction.rtl
    if bd == "L":
        return Direction.ltr
    return None


# Tokens that must be kept as written and isolated. Order matters (first match wins).
_TOKEN_PATTERNS: list[tuple[RunKind, str]] = [
    (RunKind.email, r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    (RunKind.url, r"(?:https?://|www\.)[^\s<>\"]+[^\s<>\".,;:!?)]"),
    (RunKind.date, r"\b\d{1,4}[./-]\d{1,2}[./-]\d{1,4}\b"),
    # identifiers: alnum codes containing at least one digit, with optional separators (784-1990-1234567-1, AB12345, P-00123/2024)
    (RunKind.identifier, r"(?<![\w])(?=[\w/.-]*\d)[A-Za-z0-9]+(?:[-/.][A-Za-z0-9]+)+(?![\w])|(?<![\w])(?=[A-Za-z]*\d)(?=\d*[A-Za-z])[A-Za-z0-9]{3,}(?![\w])"),
    (RunKind.number, r"[+]?\d[\d\s,.]*\d%?|\d%?"),
    # any remaining run of Latin letters (acronyms, brand names): isolated, and later checked by QA
    (RunKind.identifier, r"[A-Za-z][A-Za-z0-9&'._-]*(?:\s+[A-Za-z0-9][A-Za-z0-9&'._-]*)*"),
]
_TOKEN_RE = re.compile("|".join(f"(?P<g{i}>{p})" for i, (_, p) in enumerate(_TOKEN_PATTERNS)))


def segment(text: str, target: Direction) -> list[InlineRun]:
    """Split translated text into runs; tokens that run against the paragraph
    direction (or are identifiers/numbers/dates) become isolated runs.

    For LTR targets only RTL-script stretches are isolated (names or codes left
    in Arabic/Hebrew); numbers are fine in an LTR paragraph.
    """
    runs: list[InlineRun] = []
    if target == Direction.rtl:
        pos = 0
        for m in _TOKEN_RE.finditer(text):
            if m.start() > pos:
                runs.append(InlineRun(text=text[pos:m.start()]))
            kind = _TOKEN_PATTERNS[int(m.lastgroup[1:])][0]
            runs.append(InlineRun(text=m.group(0), kind=kind, direction=Direction.ltr))
            pos = m.end()
        if pos < len(text):
            runs.append(InlineRun(text=text[pos:]))
    else:
        for m in re.finditer(r"([֐-ࣿיִ-﷿ﹰ-﻿][֐-ࣿיִ-﷿ﹰ-﻿\s\d]*[֐-ࣿיִ-﷿ﹰ-﻿]|[֐-ࣿיִ-﷿ﹰ-﻿])|([^֐-ࣿיִ-﷿ﹰ-﻿]+)", text):
            if m.group(1):
                runs.append(InlineRun(text=m.group(1), kind=RunKind.name, direction=Direction.rtl))
            else:
                runs.append(InlineRun(text=m.group(2)))
    return [r for r in runs if r.text]


def needs_isolation(run: InlineRun, paragraph: Direction) -> bool:
    if run.kind == RunKind.text and run.direction is None:
        return False
    d = run.direction or infer_direction(run.text) or paragraph
    if paragraph == Direction.rtl:
        # anything LTR, and every number/date/identifier
        return d == Direction.ltr or run.kind != RunKind.text
    return d == Direction.rtl


def infer_direction(text: str) -> Direction | None:
    for ch in text:
        d = strong_direction(ch)
        if d:
            return d
    return None


def isolate(text: str, run_dir: Direction, style: str = "marks") -> str:
    """Wrap text so it cannot reorder against its paragraph.

    ``marks``  : LRM/RLM on both sides. Universally supported by Word and LibreOffice.
    ``isolate``: Unicode isolates LRI/RLI ... PDI (cleanest, needs newer renderers).
    """
    if style == "isolate":
        return (LRI if run_dir == Direction.ltr else RLI) + text + PDI
    m = LRM if run_dir == Direction.ltr else RLM
    return m + text + m
