"""Deterministic target-text checks (no LLM).

* leftover source-script text in the target (identifiers on the allow-list excepted)
* stray punctuation (doubled marks, space before punctuation, unbalanced // notes)
* figure match: every number/date/identifier in the source appears in the target
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..model import Block, BlockType, Document
from ..profiles import resolve_pair
from ..textdir import LRI, LRM, PDI, RLI, RLM, SCRIPT_RANGES, char_script

QUOTED = re.compile(r"«[^»]{1,80}»|\u201c[^\u201d]{1,80}\u201d|\"[^\"]{1,80}\"")
ALLOWED_TOKEN = re.compile(
    r"\S*_\S*"                                            # system names, usernames (AKHILA_HANIIT)
    r"|(?<!\w)[A-Za-z]{1,3}(?=\s?\d)"                      # letter prefixes of references (L 17344, No 5)
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"                       # email
    r"|(?:https?://|www\.)\S+"                             # url
    r"|(?=[A-Za-z0-9/.-]*\d)[A-Za-z0-9]+(?:[-/.][A-Za-z0-9]+)*"  # codes containing a digit
)
_CTRL = {LRM, RLM, LRI, RLI, PDI, "⁨"}


@dataclass
class Finding:
    block_id: str
    code: str
    detail: str


def block_texts(b: Block) -> list[tuple[str, str]]:
    """(source, target) pairs for a block, tables flattened."""
    if b.type in (BlockType.table, BlockType.kv_table):
        return [(c.source_text, c.translated_text) for r in b.rows for c in r.cells]
    return [(b.source_text, b.translated_text)]


def _strip_allowed(text: str, glossary_keep: set[str]) -> str:
    text = "".join(ch for ch in text if ch not in _CTRL)
    text = QUOTED.sub(" ", text)  # quoted on-screen labels and titles are reproduced as written
    for keep in sorted(glossary_keep, key=len, reverse=True):
        text = text.replace(keep, " ")
    return ALLOWED_TOKEN.sub(" ", text)


def leftover_source_script(doc: Document, extra_allow: set[str] | None = None) -> list[Finding]:
    pair = resolve_pair(doc.source_language, doc.target_language)
    src_script, tgt_script = pair.source.script, pair.target.script
    keep = {g.target for g in doc.glossary if g.confirmed} | (extra_allow or set())
    out: list[Finding] = []
    if pair.same_script:
        return out  # e.g. fr->en: handled by the QA agent (untranslated words), not by script
    check_scripts = {src_script}
    if pair.no_foreign_script:
        check_scripts |= {s for s in SCRIPT_RANGES if s != tgt_script and not _same_family(s, tgt_script)}
    for b in doc.blocks:
        for _, tgt in block_texts(b):
            residue = _strip_allowed(tgt, keep)
            bad = [ch for ch in residue if char_script(ch) in check_scripts and not _same_family(char_script(ch), tgt_script)]
            if bad:
                words = sorted(set(re.findall(r"\S*[" + re.escape("".join(set(bad))) + r"]\S*", residue)))
                out.append(Finding(b.id, "leftover_source_script", ", ".join(words[:8])))
    return out


def _same_family(a: str | None, b: str) -> bool:
    fam = [{"Hans", "Hant", "Jpan"}]
    return a == b or any(a in f and b in f for f in fam)


_STRAY = [
    (re.compile(r"([,.;:!?،؛])\1"), "doubled_punctuation"),
    (re.compile(r"\s+[,.;:!?،؛]"), "space_before_punctuation"),
    (re.compile(r"[(\[]\s*[)\]]"), "empty_brackets"),
]


def stray_punctuation(doc: Document) -> list[Finding]:
    out = []
    for b in doc.blocks:
        for _, tgt in block_texts(b):
            t = "".join(ch for ch in tgt if ch not in _CTRL)
            t = re.sub(r"\.{3}|…", "", t)
            for rx, code in _STRAY:
                m = rx.search(t)
                if m:
                    out.append(Finding(b.id, code, m.group(0)))
            if re.sub(r"(?:https?:)?//\S+", "", t).count("//") % 2 and t.count("//") % 2:
                out.append(Finding(b.id, "unbalanced_note_marks", t[:40]))
    return out


# A figure never starts inside a word or a number: the digits of chemical names and symbols (SpO2, O2, CO2)
# are part of a term the translation renders as words, not figures to copy.
_FIG = re.compile(r"(?<![A-Za-z0-9])(?:\d[\d/.,:-]*\d|\d)")
_HHMM = re.compile(r"([01]\d|2[0-3])([0-5]\d)")


def _time_forms(f: str) -> set[str]:
    """A 24-hour time written 1909 (1909H, 1909hrs) may be rendered 19:09 or 19.09 in the translation."""
    m = _HHMM.fullmatch(f)
    return {f"{m[1]}:{m[2]}", f"{m[1]}.{m[2]}"} if m else set()


def _found(f: str, text: str) -> bool:
    return f in text or f.rstrip(".") in text or any(t in text for t in _time_forms(f))


# "1 hour" and "1st" are written as words in many target languages (ساعة واحدة, الأول), as the approved
# translations do; the meaning of these is left to the QA agent rather than demanded as a digit.
_ONE_UNIT = r"\s*(?:st\b|hours?\b|hrs?\b|days?\b|minutes?\b|mins?\b)"
_ONE_AS_WORD = re.compile(r"(?<![\d.,])1" + _ONE_UNIT, re.I)
_OTHER_ONE = re.compile(r"(?<![\d.,/])1(?![\d.,:])(?!" + _ONE_UNIT + ")", re.I)


def _only_ones_as_words(src: str) -> bool:
    """True when every bare figure 1 in the text is a '1 hour' / '1st' (written as a word in the target)."""
    return bool(_ONE_AS_WORD.search(src)) and not _OTHER_ONE.search(src)


def figures_match(doc: Document) -> list[Finding]:
    """Digit sequences of the source must be found in the target (Eastern Arabic digits normalised)."""
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    out = []
    for b in doc.blocks:
        for src, tgt in block_texts(b):
            s_figs = {f.translate(trans) for f in _FIG.findall(src.translate(trans))}
            if _only_ones_as_words(src):
                s_figs.discard("1")
            t = tgt.translate(trans)
            missing = [f for f in s_figs if not _found(f, t)]
            if missing:
                out.append(Finding(b.id, "figure_missing", ", ".join(sorted(missing))))
    return out


def figures_added(doc: Document) -> list[Finding]:
    """Digit sequences in the translation that the source does not contain (invented or altered figures)."""
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    out = []
    for b in doc.blocks:
        if b.multilingual_duplicate:
            continue
        for src, tgt in block_texts(b):
            s = src.translate(trans)
            s_forms = {tf for f in _FIG.findall(s) for tf in _time_forms(f)}
            added = [f for f in {f.translate(trans) for f in _FIG.findall(tgt.translate(trans))}
                     if f not in s and f.rstrip(".") not in s and f not in s_forms]
            if added:
                out.append(Finding(b.id, "figure_added", ", ".join(sorted(added))))
    return out


_IDENT = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|(?:https?://|www\.)[^\s<>\"]+[^\s<>\".,;:!?)]"
                    r"|(?<![\w])(?=[A-Za-z0-9/.-]*[A-Za-z])(?=[A-Za-z0-9/.-]*\d)[A-Za-z0-9]+(?:[-/.][A-Za-z0-9]+)*(?![\w])")


# Units and clock-time suffixes: a number followed by one of these is a measurement, not an identifier.
# The translation writes the unit in the target language; its number is still enforced by figures_match.
# Ambiguous single letters (c, m, s, l, v, w) are left out: 12C or 3M may be a flat or a reference code.
# Also clock suffixes (am/pm) and ordinals (1st, 2nd).
_UNIT = (r"(?:mg|mcg|ug|µg|g|gm|kg|ml|cc|mmhg|bpm|rpm|min|mins|sec|hr|hrs|h|hours?|days?|cm|mm|km|"
         r"iu|units?|mmol|kcal|°c|°f|kb|mb|gb|tb|kw|am|pm|st|nd|rd|th)")
_MEASURE = re.compile(r"\d+(?:[.,]\d+)?" + _UNIT, re.I)
# Chemical and clinical symbols translated as words (O2 -> oxygen); the OCR often reads SpO2 as SP02.
_TERMS = {"o2", "co2", "spo2", "sp02", "sao2", "pao2", "paco2", "fio2", "etco2", "h2o", "kg/m2", "m2"}
# Vital-sign labels written label-value (BP-117/80mmHg, HR-68bpm): the label is translated, the values are figures.
_VITALS = {"bp", "hr", "pr", "rr", "temp", "gcs", "rbs", "fbs", "map"}
_REF_PREFIX = re.compile(r"(?i)^(?:no|nr|ref)\.")


def _kind(p: str) -> str:
    if p.isalpha():
        return "alpha"
    if p.isdigit():
        return "digits"
    return "measure" if _MEASURE.fullmatch(p) else "other"


def _is_identifier(token: str) -> bool:
    """False for tokens whose digits are figures rather than a code: measurements (7.5MG, 105bpm, 1909H, 7.35PM),
    numbers or measurements joined to words (1909H-Patient, 1911-Epinephrine, SINGLE/1ST), chemical symbols
    (O2, SpO2-65) and vital signs (BP-117/80mmHg). Their numbers are still enforced by figures_match."""
    if token.lower() in _TERMS or _MEASURE.fullmatch(token):
        return False
    parts = [p for p in re.split(r"[-/]", token) if p]
    kinds = [_kind(p) for p in parts]
    head = parts[0].lower()
    if all(k in ("alpha", "measure") for k in kinds):
        return False
    if kinds[0] == "digits" and len(parts) > 1 and all(k == "alpha" for k in kinds[1:]):
        return False
    if head in _TERMS or (head in _VITALS and all(k in ("digits", "measure") for k in kinds[1:])):
        return False
    return True


def _kept(token: str, text: str) -> bool:
    """The identifier is in the translation as written; a 'No.'/'Ref.' prefix may itself be translated."""
    token = token.rstrip(".")
    return token in text or (bool(_REF_PREFIX.match(token)) and _REF_PREFIX.sub("", token) in text)


def identifiers_match(doc: Document) -> list[Finding]:
    """IDs, codes, emails and URLs (letters + digits) must appear in the translation exactly as written."""
    out = []
    for b in doc.blocks:
        if b.multilingual_duplicate:
            continue
        for src, tgt in block_texts(b):
            t = "".join(ch for ch in tgt if ch not in _CTRL)
            missing = sorted({m for m in _IDENT.findall(src) if _is_identifier(m) and not _kept(m, t)})
            if missing:
                out.append(Finding(b.id, "identifier_changed", ", ".join(missing)))
    return out


def scan(doc: Document) -> list[Finding]:
    return (leftover_source_script(doc) + stray_punctuation(doc) + figures_match(doc) + figures_added(doc)
            + identifiers_match(doc))
