"""Human review of a translated document (Phase 4).

Pure functions on the document model, used by the review editor API:
* ``edit_block``   - a reviewer changes a block's text or table cells
* ``decide_change`` - accept or reject a change an agent made (proofreader, translator fix, ...)
* ``resolve_flag`` - close a QA flag with a comment

Every change to the text appends a ``HistoryEntry`` with the reviewer as actor, so the
audit trail shows who changed what. Nothing here calls a model.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from .model import Block, Document, HistoryEntry, Severity

CELL_FIELD = re.compile(r"rows\[(\d+)\]\[(\d+)\]")
AGENT_ACTORS = {"translator", "proofreader", "qa", "formatter"}


class ReviewError(ValueError):
    """The request does not fit the document (unknown block, index, field)."""


class ReviewConflict(ReviewError):
    """The text changed since the agent's edit, so the decision cannot be applied safely."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def block(doc: Document, block_id: str) -> Block:
    for b in doc.blocks:
        if b.id == block_id:
            return b
    raise ReviewError(f"no block {block_id}")


def _get(b: Block, field: str) -> str:
    if field == "translated_text":
        return b.translated_text
    m = CELL_FIELD.fullmatch(field)
    if not m:
        raise ReviewError(f"unknown field {field}")
    r, c = int(m.group(1)), int(m.group(2))
    if r >= len(b.rows) or c >= len(b.rows[r].cells):
        raise ReviewError(f"block {b.id}: no cell {field}")
    return b.rows[r].cells[c].translated_text


def _set(b: Block, field: str, text: str) -> None:
    if field == "translated_text":
        if b.rows:
            raise ReviewError(f"block {b.id} is a table: edit its cells")
        b.translated_text, b.runs = text, None
        return
    _get(b, field)                                   # validates the cell
    m = CELL_FIELD.fullmatch(field)
    cell = b.rows[int(m.group(1))].cells[int(m.group(2))]
    if cell.blocks:
        raise ReviewError(f"block {b.id}: cell {field} has rich content and cannot be edited as text")
    cell.translated_text, cell.runs = text, None


def edit_block(doc: Document, block_id: str, user: str, text: Optional[str] = None,
               cells: Optional[list[tuple[int, int, str]]] = None, reason: str = "") -> list[HistoryEntry]:
    """Apply a reviewer's edit. Returns the history entries added (empty if nothing changed)."""
    b = block(doc, block_id)
    edits: list[tuple[str, str]] = []
    if text is not None:
        edits.append(("translated_text", text))
    for r, c, t in cells or []:
        edits.append((f"rows[{r}][{c}]", t))
    if not edits:
        raise ReviewError("nothing to edit")
    added = []
    for field, new in edits:
        old = _get(b, field)
        if old == new:
            continue
        _set(b, field, new)
        h = HistoryEntry(actor=user, field=field, old=old, new=new, reason=reason or "review edit")
        b.history.append(h)
        added.append(h)
    return added


def changes(doc: Document) -> list[dict]:
    """Agent changes open to accept/reject, in document order. ``index`` is the position in the block history."""
    out = []
    for b in doc.blocks:
        for i, h in enumerate(b.history):
            if h.actor in AGENT_ACTORS and h.old is not None and h.new is not None and h.old != h.new:
                out.append({"block": b.id, "index": i, "actor": h.actor, "field": h.field, "reason": h.reason,
                            "review": h.review})
    return out


def decide_change(doc: Document, block_id: str, index: int, user: str, accept: bool) -> HistoryEntry:
    """Accept (keep) or reject (restore the old text) an agent change."""
    b = block(doc, block_id)
    if index < 0 or index >= len(b.history):
        raise ReviewError(f"block {block_id}: no change {index}")
    h = b.history[index]
    if h.actor not in AGENT_ACTORS or h.old is None or h.new is None:
        raise ReviewError(f"block {block_id}: history entry {index} is not an agent change")
    if h.review is not None:
        raise ReviewConflict(f"block {block_id}: change {index} was already {h.review}")
    if not accept:
        if _get(b, h.field) != h.new:
            raise ReviewConflict(f"block {block_id}: the text changed after this change; edit it directly")
        _set(b, h.field, h.old)
        b.history.append(HistoryEntry(actor=user, field=h.field, old=h.new, new=h.old,
                                      reason=f"rejected {h.actor} change #{index}"))
    h.review, h.reviewed_by = ("accepted" if accept else "rejected"), user
    return h


def resolve_flag(doc: Document, block_id: str, index: int, user: str, comment: str) -> None:
    b = block(doc, block_id)
    if index < 0 or index >= len(b.flags):
        raise ReviewError(f"block {block_id}: no flag {index}")
    f = b.flags[index]
    if f.resolved:
        raise ReviewConflict(f"block {block_id}: flag {index} is already resolved")
    comment = comment.strip()
    if f.severity == Severity.blocker and not comment:
        raise ReviewError("a blocker needs a comment to be resolved")
    f.resolved, f.resolved_by, f.resolved_at, f.resolution = True, user, _now(), comment or None


def open_blockers(doc: Document) -> list[str]:
    return [b.id for b in doc.blocks if any(f.severity == Severity.blocker and not f.resolved for f in b.flags)]
