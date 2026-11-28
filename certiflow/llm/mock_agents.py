"""Deterministic offline stand-ins for every agent (tests and dry runs only).

They read the same payloads the real agents get and return schema-valid
replies, so the whole pipeline (OCR, graph, checkpoints, QA loop, builder) runs
without the API. The "translation" is a marked pseudo-translation into the
target script that keeps identifiers and figures: it is never a real
translation and is labelled as such.
"""
from __future__ import annotations

import json
import re

from ..profiles import get_profile
from ..textdir import char_script
from .client import LLMRequest, MockClient

PSEUDO_WORD = {"Arab": "كلمة", "Latn": "word", "Cyrl": "слово", "Hebr": "מילה", "Hans": "词", "Jpan": "語",
               "Kore": "단어", "Deva": "शब्द"}
KEEP = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|(?:https?://|www\.)\S+|[A-Za-z0-9]*\d[A-Za-z0-9/.,:%-]*|[^\w\s]+")


def pseudo_translate(text: str, target: str) -> str:
    """Words -> a target-script placeholder; identifiers, numbers, dates, punctuation kept."""
    word = PSEUDO_WORD.get(get_profile(target).script, "word")
    out = []
    for tok in re.findall(r"\S+|\s+", text):
        if tok.isspace():
            out.append(tok)
            continue
        parts = KEEP.findall(tok)
        if any(ch.isdigit() for ch in tok) or "@" in tok or (parts and "".join(parts) == tok):
            out.append(tok)
        else:
            kept = "".join(p for p in parts if any(ch.isdigit() for ch in p) or "@" in p)
            out.append((word + (" " + kept if kept else "")))
    return "".join(out)


def _payload(req: LLMRequest) -> dict:
    return req.payload if isinstance(req.payload, dict) else json.loads(req.user_text.split("\n\n", 1)[-1])


def make_mock(target: str, corrupt_once: set[str] | None = None, qa_issues: list[dict] | None = None,
              proofread_changes: list[dict] | None = None) -> MockClient:
    corrupt = set(corrupt_once or ())

    def intake(req):
        p = _payload(req)
        lines = [l.strip() for l in p["ocr_draft"].splitlines() if l.strip()]
        blocks, kv = [], []

        def flush_kv():
            if kv:
                blocks.append(dict(type="kv_table", level=None, label=None, text="", rows=[list(r) for r in kv],
                                   header_row=False, note_kind=None, note_description=None, unreadable_reason=None,
                                   confidence=0.95, continues_previous_page=False, multilingual_duplicate=False,
                                   repeated_on_every_page=False))
                kv.clear()
        for i, line in enumerate(lines):
            base = dict(level=None, label=None, rows=None, header_row=False, note_kind=None, note_description=None,
                        unreadable_reason=None, confidence=0.95, continues_previous_page=False,
                        multilingual_duplicate=False, repeated_on_every_page=False)
            m_kv = re.match(r"^([^:：]{2,40})[:：]\s*(.+)$", line)
            m_num = re.match(r"^(\d+[.)])\s+(.+)$", line)
            if i == 0:
                flush_kv(); blocks.append({**base, "type": "heading", "level": 1, "text": line})
            elif m_num:
                flush_kv(); blocks.append({**base, "type": "numbered_item", "label": m_num.group(1), "text": m_num.group(2)})
            elif m_kv and len(m_kv.group(1).split()) <= 5:
                kv.append((m_kv.group(1).strip(), m_kv.group(2).strip()))
            else:
                flush_kv(); blocks.append({**base, "type": "paragraph", "text": line})
        flush_kv()
        blocks.append(dict(type="note", level=None, label=None, text="", rows=None, header_row=False, note_kind="stamp",
                           note_description="oval stamp, red ink", unreadable_reason=None, confidence=0.9,
                           continues_previous_page=False, multilingual_duplicate=False, repeated_on_every_page=False))
        step = 800 // max(len(blocks), 1)               # stacked boxes down the page (positions for the editor)
        for i, b in enumerate(blocks):
            b["bbox"] = [80, 100 + i * step, 920, 100 + (i + 1) * step - 10]
        return {"languages": ["xx"], "rotation_needed": 0, "has_stamp": True, "has_signature": False,
                "has_handwriting": False, "has_table": bool(kv), "removed_artifacts": [], "blocks": blocks,
                "uncertain_regions": []}

    def zoom(req):
        p = _payload(req)
        return {"text": p.get("current_reading", ""), "legible": True, "covered_by_stamp": False, "confidence": 0.99}

    def glossary(req):
        return {"items": []}

    def translator(req):
        p = _payload(req)
        out = []
        for b in p["translate"]:
            text = "" if b["type"] == "note" and not b["text"] else pseudo_translate(b["text"], target)
            if b["id"] in corrupt and not p.get("fix_requests"):
                text = re.sub(r"\d", "9", text, count=1) if re.search(r"\d", text) else text + " 999"
                corrupt.discard(b["id"])
            rows = [[pseudo_translate(c, target) for c in r] for r in b["rows"]] if b.get("rows") else None
            out.append({"id": b["id"], "text": text, "label": b.get("label"), "rows": rows})
        return {"blocks": out}

    def proofreader(req):
        ids = {b["id"] for b in _payload(req)["blocks"]}
        return {"changes": [c for c in (proofread_changes or []) if c["id"] in ids]}

    def qa(req):
        ids = {b["id"] for b in _payload(req)["blocks"]}
        return {"issues": [i for i in (qa_issues or []) if i.get("id") in ids]}

    def formatter(req):
        return {"decisions": [{"id": b["id"], "type": b["type"], "level": b["level"], "align": None, "bold": None,
                               "column_widths": None, "page_break_before": False}
                              for b in _payload(req)["blocks"]]}

    def assistant(req):
        # Labelled mock: one pseudo wording of the block so the editor's "use this" path can be exercised offline.
        blk = _payload(req)["block"]
        text = pseudo_translate(blk.get("source") or "", target) if blk.get("source") else ""
        sugg = [{"text": text, "note": "Mock suggestion (test mode, not a real translation)."}] if text else []
        return {"answer": "Mock answer (test mode): the helper would answer the question here.", "suggestions": sugg}

    return MockClient(handlers={"assistant": assistant, "intake": intake, "intake_zoom": zoom, "glossary": glossary, "translator": translator,
                                "proofreader": proofreader, "qa": qa, "formatter": formatter})
