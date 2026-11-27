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


_FIG = re.compile(r"\d[\d/.,:-]*\d|\d")


def figures_match(doc: Document) -> list[Finding]:
    """Digit sequences of the source must be found in the target (Eastern Arabic digits normalised)."""
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    out = []
    for b in doc.blocks:
        for src, tgt in block_texts(b):
            s_figs = {f.translate(trans) for f in _FIG.findall(src.translate(trans))}
            t = tgt.translate(trans)
            missing = [f for f in s_figs if f not in t and f.rstrip(".") not in t]
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
            added = [f for f in {f.translate(trans) for f in _FIG.findall(tgt.translate(trans))}
                     if f not in s and f.rstrip(".") not in s]
            if added:
                out.append(Finding(b.id, "figure_added", ", ".join(sorted(added))))
    return out


_IDENT = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|(?:https?://|www\.)[^\s<>\"]+[^\s<>\".,;:!?)]"
                    r"|(?<![\w])(?=[A-Za-z0-9/.-]*[A-Za-z])(?=[A-Za-z0-9/.-]*\d)[A-Za-z0-9]+(?:[-/.][A-Za-z0-9]+)*(?![\w])")


def identifiers_match(doc: Document) -> list[Finding]:
    """IDs, codes, emails and URLs (letters + digits) must appear in the translation exactly as written."""
    out = []
    for b in doc.blocks:
        if b.multilingual_duplicate:
            continue
        for src, tgt in block_texts(b):
            t = "".join(ch for ch in tgt if ch not in _CTRL)
            missing = sorted({m for m in _IDENT.findall(src) if m.rstrip(".") not in t})
            if missing:
                out.append(Finding(b.id, "identifier_changed", ", ".join(missing)))
    return out


def scan(doc: Document) -> list[Finding]:
    return (leftover_source_script(doc) + stray_punctuation(doc) + figures_match(doc) + figures_added(doc)
            + identifiers_match(doc))
