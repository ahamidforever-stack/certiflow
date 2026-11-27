"""Deterministic Word renderer: Document model -> .docx on the office template.

Two font modes from the same model:
  * ``word`` - the release .docx, using each profile's Word font.
  * ``pdf``  - an identical document using the profile's embedded open font,
               converted by LibreOffice (which does not have proprietary Word fonts).

Layout comes from three layers, most specific first: the block's own Layout
(Formatter output), the office HouseStyle, the target Language Profile.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from docx import Document as load_docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from ..house import DEFAULT as DEFAULT_HOUSE
from ..house import HouseStyle
from ..model import Block, BlockType, Direction, Document, InlineRun, PageOrder, RunKind, TableCell
from ..profiles import LanguageProfile, ResolvedPair, resolve_pair
from ..textdir import LRM, RLM, infer_direction, isolate, needs_isolation, segment
from .seal_docx import install_seal

FontMode = Literal["word", "pdf"]

SEAL_MARKER = "CFSEAL"            # hidden marker text in every footer / on every source page
SEGMENT_MARKER = "CFSP"           # hidden per-source-page marker (interleaved mode)

# Fallback fonts for runs whose script is not the target's own script, per rFonts slot.
FALLBACK = {
    "ascii": {"word": "Times New Roman", "pdf": "Liberation Serif"},
    "cs": {"word": "Sakkal Majalla", "pdf": "Amiri"},
    "eastAsia": {"word": "SimSun", "pdf": "Noto Serif CJK SC"},
}


@dataclass
class SealSpec:
    stamp_png: Path
    signature_png: Path
    stamp_width_mm: float = 38.0
    signature_width_mm: float = 32.0
    marker: str = SEAL_MARKER
    layout: dict | None = None            # template seal layout (page-relative ink centres, mm)
    strip_images: list[str] = field(default_factory=list)  # sha1 of template footer images to remove


@dataclass
class BuildOptions:
    font_mode: FontMode = "word"
    isolation_style: Literal["marks", "isolate"] = "marks"
    page_order: PageOrder = PageOrder.translation_then_source
    seal: SealSpec | None = None
    house: HouseStyle = field(default_factory=lambda: DEFAULT_HOUSE)
    margins_mm: dict | None = None        # template margin overrides {"top":..,"bottom":..,"left":..,"right":..}


# ----------------------------------------------------------------- xml utils

def _el(tag: str, **attrs) -> OxmlElement:
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn(k if ":" in k else f"w:{k}"), str(v))
    return e


def _get_or_add(parent, tag: str):
    found = parent.find(qn(tag))
    if found is None:
        found = OxmlElement(tag)
        parent.append(found)
    return found


def _tw(pt: float) -> int:
    return int(round(pt * 20))


class _Ctx:
    def __init__(self, doc_model: Document, pair: ResolvedPair, opts: BuildOptions, text_width_twips: int):
        self.m = doc_model
        self.pair = pair
        self.t: LanguageProfile = pair.target
        self.opts = opts
        self.h: HouseStyle = opts.house
        self.dir = self.t.direction
        self.width = text_width_twips
        self.body = self.t.body_size_pt

    def target_font(self) -> str:
        return self.t.word_font if self.opts.font_mode == "word" else self.t.pdf_font

    def font(self, slot: str) -> str:
        if slot == self.t.font_slot:
            return self.target_font()
        if self.h.latin_in_target_font and self.t.font_slot == "cs" and slot in ("ascii", "eastAsia"):
            return self.target_font()
        s = self.pair.source
        if slot == s.font_slot and s.font_slot != "ascii":
            return s.word_font if self.opts.font_mode == "word" else s.pdf_font
        return FALLBACK[slot][self.opts.font_mode]


# ------------------------------------------------------------------- runs

def _run_props(ctx: _Ctx, *, size_pt: float, bold: bool, italic: bool, rtl: bool, proof: bool,
               color: str | None = None):
    rpr = _el("w:rPr")
    rpr.append(_el("w:rFonts", ascii=ctx.font("ascii"), hAnsi=ctx.font("ascii"),
                   eastAsia=ctx.font("eastAsia"), cs=ctx.font("cs")))
    if bold:
        rpr.append(_el("w:b"))
        rpr.append(_el("w:bCs"))
    if italic:
        rpr.append(_el("w:i"))
        rpr.append(_el("w:iCs"))
    if color:
        rpr.append(_el("w:color", val=color))
    hp = str(int(round(size_pt * 2)))
    rpr.append(_el("w:sz", val=hp))
    rpr.append(_el("w:szCs", val=hp))
    if rtl:
        rpr.append(_el("w:rtl"))
    if not proof:
        rpr.append(_el("w:noProof"))
    tag = ctx.t.word_tag
    lang = {"val": tag if ctx.t.font_slot == "ascii" else "en-GB"}
    if ctx.t.font_slot == "cs":
        lang["bidi"] = tag
    if ctx.t.font_slot == "eastAsia":
        lang["eastAsia"] = tag
    rpr.append(_el("w:lang", **lang))
    return rpr


def _add_run(p_el, ctx: _Ctx, text: str, *, size_pt: float, bold=False, italic=False, rtl=False,
             proof=True, color=None):
    r = _el("w:r")
    r.append(_run_props(ctx, size_pt=size_pt, bold=bold, italic=italic, rtl=rtl, proof=proof, color=color))
    t = _el("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    r.append(t)
    p_el.append(r)
    return r


@dataclass
class _RunStyle:
    size: float
    bold: bool = False
    italic: bool = False
    color: str | None = None


def _add_runs(p_el, ctx: _Ctx, runs: list[InlineRun], pdir: Direction, st: _RunStyle):
    for run in runs:
        iso = needs_isolation(run, pdir)
        rdir = run.direction or infer_direction(run.text) or pdir
        text = isolate(run.text, rdir, ctx.opts.isolation_style) if iso else run.text
        _add_run(p_el, ctx, text, size_pt=run.size_pt or st.size, bold=st.bold or run.bold,
                 italic=st.italic or run.italic, color=run.color or st.color,
                 rtl=(rdir == Direction.rtl),
                 proof=run.kind in (RunKind.text, RunKind.name))


def _runs_for(text: str, runs: list[InlineRun] | None, pdir: Direction) -> list[InlineRun]:
    return runs if runs else segment(text, pdir)


# ------------------------------------------------------------- paragraphs

_JC = {"start": "left", "end": "right", "center": "center", "justify": "both"}


def _new_par(ctx: _Ctx, pdir: Direction, *, align: str, keep_next=False, space_before=0.0,
             space_after=3.0, indent_twips: int = 0, fill: str | None = None, line: float | None = None):
    p = _el("w:p")
    ppr = _el("w:pPr")
    if keep_next:
        ppr.append(_el("w:keepNext"))
    if fill:
        ppr.append(_el("w:shd", val="clear", color="auto", fill=fill))
    if pdir == Direction.rtl:
        ppr.append(_el("w:bidi"))
    sp = {"before": _tw(space_before), "after": _tw(space_after)}
    ln = line if line is not None else ctx.h.line_spacing
    if ln:
        sp.update(line=int(240 * ln), lineRule="auto")
    ppr.append(_el("w:spacing", **sp))
    if indent_twips:
        ppr.append(_el("w:ind", start=indent_twips))
    # In bidi paragraphs Word and LibreOffice read left/right relative to the reading direction.
    ppr.append(_el("w:jc", val=_JC[align]))
    p.append(ppr)
    return p


def _block_dir(ctx: _Ctx, b: Block) -> Direction:
    return b.direction or ctx.dir


@dataclass
class _ParStyle:
    align: str
    size: float
    bold: bool = False
    italic: bool = False
    color: str | None = None
    keep_next: bool = False
    before: float = 0.0
    after: float = 3.0
    indent: int = 0
    fill: str | None = None


def _apply_layout(ps: _ParStyle, b: Block, ctx: _Ctx) -> _ParStyle:
    lay = b.layout
    if lay.align:
        ps.align = lay.align
    if lay.bold is not None:
        ps.bold = lay.bold
    if lay.size_pt:
        ps.size = lay.size_pt
    elif lay.font_scale != 1.0:
        ps.size = ps.size * lay.font_scale
    if lay.keep_with_next is not None:
        ps.keep_next = lay.keep_with_next
    if lay.space_before_pt is not None:
        ps.before = lay.space_before_pt
    if lay.space_after_pt is not None:
        ps.after = lay.space_after_pt
    if lay.indent_twips is not None:
        ps.indent = lay.indent_twips
    elif lay.indent_level:
        ps.indent = 360 * lay.indent_level
    if lay.fill is not None:
        ps.fill = lay.fill or None
    return ps


def _paragraph(body, ctx: _Ctx, b: Block, ps: _ParStyle, runs: list[InlineRun]):
    pdir = _block_dir(ctx, b)
    p = _new_par(ctx, pdir, align=ps.align, keep_next=ps.keep_next, space_before=ps.before,
                 space_after=ps.after, indent_twips=ps.indent, fill=ps.fill)
    _add_runs(p, ctx, runs, pdir, _RunStyle(ps.size, ps.bold, ps.italic, ps.color))
    body.append(p)
    return p


def _text_runs(ctx: _Ctx, b: Block) -> list[InlineRun]:
    return _runs_for(b.translated_text, b.runs, _block_dir(ctx, b))


def _label_runs(ctx: _Ctx, label: str, pdir: Direction) -> list[InlineRun]:
    """Numbering label as the house writes it. RTL, isolated_digits: ‎1‎.‏ + gap."""
    h = ctx.h
    label = label.strip()
    if pdir == Direction.rtl and h.number_label == "isolated_digits":
        core = label.rstrip(".)-:")
        tail = label[len(core):]
        out = [InlineRun(text=core, kind=RunKind.number, direction=Direction.ltr)]
        out.append(InlineRun(text=tail + (RLM if tail else "") + h.number_gap))
        return out
    return [InlineRun(text=label + h.number_gap)]


def _note_text(ctx: _Ctx, text: str) -> str:
    return ctx.h.note_wrap.format(text=text.strip())


def _unreadable_text(ctx: _Ctx, b: Block) -> str:
    lb = ctx.t.labels
    label = {"illegible": lb.unreadable_illegible, "covered_by_stamp": lb.unreadable_covered_by_stamp,
             "truncated": lb.unreadable_truncated}[b.unreadable_reason.value]
    return f"{b.translated_text.strip()} {label}".strip() if b.translated_text else label


def _page_break(body):
    p = _el("w:p")
    r = _el("w:r")
    r.append(_el("w:br", type="page"))
    p.append(r)
    body.append(p)


# ------------------------------------------------------------------ tables

def _borders(color: str):
    b = _el("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b.append(_el(f"w:{side}", val="single", sz=4, space=0, color=color))
    return b


def _default_widths(b: Block, ncols: int) -> list[float]:
    if b.type == BlockType.kv_table:
        if ncols == 2:
            return [0.3, 0.7]
        pairs = ncols // 2
        return [0.44 / pairs, 0.56 / pairs] * pairs
    return [1.0] * ncols


def _render_table(body, ctx: _Ctx, b: Block):
    h = ctx.h
    pdir = _block_dir(ctx, b)
    ncols = max(sum(c.colspan for c in r.cells) for r in b.rows)
    rel = b.column_widths or _default_widths(b, ncols)
    tot = sum(rel)
    widths = [int(ctx.width * w / tot) for w in rel]
    widths[-1] += ctx.width - sum(widths) if abs(ctx.width - sum(widths)) < 10 else 0

    tbl = _el("w:tbl")
    tpr = _el("w:tblPr")
    if pdir == Direction.rtl:
        tpr.append(_el("w:bidiVisual"))
    tpr.append(_el("w:tblW", w=sum(widths), type="dxa"))
    tpr.append(_borders(h.border_color))
    tpr.append(_el("w:tblLayout", type="fixed"))
    mar = _el("w:tblCellMar")
    mar.append(_el("w:top", w=h.cell_margin_tb_twips, type="dxa"))
    mar.append(_el("w:left", w=h.cell_margin_lr_twips, type="dxa"))
    mar.append(_el("w:bottom", w=h.cell_margin_tb_twips, type="dxa"))
    mar.append(_el("w:right", w=h.cell_margin_lr_twips, type="dxa"))
    tpr.append(mar)
    tbl.append(tpr)
    grid = _el("w:tblGrid")
    for w in widths:
        grid.append(_el("w:gridCol", w=w))
    tbl.append(grid)

    base = (b.layout.size_pt or ctx.body * b.layout.font_scale) + h.table_delta_pt
    for row in b.rows:
        tr = _el("w:tr")
        trpr = _el("w:trPr")
        trpr.append(_el("w:cantSplit"))
        if row.header:
            trpr.append(_el("w:tblHeader"))
        tr.append(trpr)
        col = 0
        for ci, cell in enumerate(row.cells):
            is_label = b.type == BlockType.kv_table and ci % 2 == 0 and not (len(row.cells) % 2)
            is_head = row.header or cell.header
            fill = cell.fill if cell.fill is not None else (
                h.label_fill if is_label else h.header_fill if is_head else None)
            tc = _el("w:tc")
            tcpr = _el("w:tcPr")
            tcpr.append(_el("w:tcW", w=sum(widths[col:col + cell.colspan]), type="dxa"))
            if cell.colspan > 1:
                tcpr.append(_el("w:gridSpan", val=cell.colspan))
            if fill:
                tcpr.append(_el("w:shd", val="clear", color="auto", fill=fill))
            tcpr.append(_el("w:vAlign", val="top"))
            tc.append(tcpr)
            col += cell.colspan
            st = _ParStyle(
                align=cell.align or ("center" if is_head else "start" if is_label else h.value_align),
                size=cell.size_pt or base, bold=cell.bold or is_label or is_head,
                after=h.label_after_pt if (is_label or is_head) else h.value_after_pt)
            _cell_paragraphs(tc, ctx, cell, pdir, st)
            tr.append(tc)
        tbl.append(tr)
    body.append(tbl)
    if h.spacer_after_table:
        sp = _new_par(ctx, pdir, align="start", space_after=h.spacer_after_pt)
        _add_run(sp, ctx, LRM + LRM, size_pt=h.spacer_size_pt)
        body.append(sp)


def _cell_paragraphs(tc, ctx: _Ctx, cell: TableCell, pdir: Direction, st: _ParStyle):
    """Cell text: one paragraph per line. Explicit runs may contain "\n" to split paragraphs.
    Rich cells (``blocks``) are rendered block by block with their own layout."""
    if cell.blocks:
        for blk in cell.blocks:
            _render_block(tc, ctx, blk, [])
        return
    if cell.runs:
        lines: list[list[InlineRun]] = [[]]
        for r in cell.runs:
            parts = r.text.split("\n")
            for k, part in enumerate(parts):
                if k:
                    lines.append([])
                if part:
                    lines[-1].append(r.model_copy(update={"text": part}))
    else:
        lines = [segment(line, pdir) for line in (cell.translated_text or "").split("\n")]
    for runs in lines:
        p = _new_par(ctx, pdir, align=st.align, space_after=st.after)
        _add_runs(p, ctx, runs or [InlineRun(text="")], pdir, _RunStyle(st.size, st.bold))
        tc.append(p)


# ------------------------------------------------------------------- build

def _clear_body(docx):
    body = docx.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def _apply_margins(docx, margins: dict | None):
    if not margins:
        return
    from docx.shared import Mm
    for s in docx.sections:
        for k, v in margins.items():
            setattr(s, f"{k}_margin", Mm(v))


def render(model: Document, template: Path, out: Path, opts: BuildOptions) -> Path:
    pair = resolve_pair(model.source_language, model.target_language)
    docx = load_docx(str(template))
    _apply_margins(docx, opts.margins_mm)
    sec = docx.sections[-1]
    text_width = int((sec.page_width - sec.left_margin - sec.right_margin) / 635)  # EMU -> twips
    ctx = _Ctx(model, pair, opts, text_width)
    _clear_body(docx)
    body = docx.element.body
    sect_pr = body.find(qn("w:sectPr"))
    tmp = _el("w:body")  # build into a scratch container, then splice before sectPr

    end_notes: list[Block] = []
    current_page = None
    interleave = opts.page_order == PageOrder.interleaved
    for b in model.blocks:
        if interleave and b.source_page and b.source_page != current_page:
            if current_page is not None:
                _page_break(tmp)
            current_page = b.source_page
            mp = _new_par(ctx, ctx.dir, align="start", space_after=0)
            _add_run(mp, ctx, f"{SEGMENT_MARKER}{b.source_page:03d}", size_pt=1, color="FFFFFF", proof=False)
            tmp.append(mp)
        _render_block(tmp, ctx, b, end_notes)

    if end_notes:
        seen: set[str] = set()
        uniq = [n for n in end_notes if not (n.translated_text.strip() in seen or seen.add(n.translated_text.strip()))]
        hb = Block(id="_end_heading", type=BlockType.heading, level=3,
                   translated_text=ctx.t.labels.repeated_notes_heading)
        _render_block(tmp, ctx, hb, [])
        for n in uniq:
            _render_block(tmp, ctx, n.model_copy(update={"note_scope": "inline"}), [])

    for child in list(tmp):
        sect_pr.addprevious(child)

    if opts.seal:
        install_seal(docx, ctx, opts.seal)
    _set_doc_language(docx, ctx)
    out.parent.mkdir(parents=True, exist_ok=True)
    docx.save(str(out))
    return out


def _render_block(body, ctx: _Ctx, b: Block, end_notes: list[Block]):
    h, t = ctx.h, b.type
    pdir = _block_dir(ctx, b)
    if t == BlockType.heading:
        if b.level == 1:
            ps = _ParStyle("center", ctx.body + h.title_delta_pt, bold=True, keep_next=True, after=h.title_after_pt)
        elif b.level == 2:
            ps = _ParStyle("start", ctx.body + h.section_delta_pt, bold=True, keep_next=True,
                           before=h.section_before_pt, after=h.section_after_pt, fill=h.section_fill)
        else:
            ps = _ParStyle(h.body_align, ctx.body + h.subheading_delta_pt, bold=True, keep_next=True,
                           after=h.para_after_pt)
        _paragraph(body, ctx, b, _apply_layout(ps, b, ctx), _text_runs(ctx, b))
    elif t == BlockType.paragraph:
        _paragraph(body, ctx, b, _apply_layout(_ParStyle(h.body_align, ctx.body, after=h.para_after_pt), b, ctx),
                   _text_runs(ctx, b))
    elif t == BlockType.numbered_item:
        pre = _label_runs(ctx, b.label, pdir) if b.label else []
        _paragraph(body, ctx, b, _apply_layout(_ParStyle(h.body_align, ctx.body, after=h.para_after_pt), b, ctx),
                   pre + _text_runs(ctx, b))
    elif t == BlockType.bullet:
        ps = _ParStyle(h.body_align, ctx.body, after=h.para_after_pt, indent=h.bullet_indent_twips)
        _paragraph(body, ctx, b, _apply_layout(ps, b, ctx), [InlineRun(text=h.bullet)] + _text_runs(ctx, b))
    elif t in (BlockType.table, BlockType.kv_table):
        _render_table(body, ctx, b)
    elif t == BlockType.note:
        if b.note_scope == "document_end":
            end_notes.append(b)
            return
        ps = _ParStyle("start", ctx.body + h.note_delta_pt, italic=h.note_italic, color=h.note_color,
                       after=h.para_after_pt)
        runs = segment(_note_text(ctx, b.translated_text), pdir) if not b.runs else (
            [InlineRun(text=h.note_wrap.split("{text}")[0])] + b.runs + [InlineRun(text=h.note_wrap.split("{text}")[1])])
        _paragraph(body, ctx, b, _apply_layout(ps, b, ctx), runs)
    elif t == BlockType.unreadable:
        _paragraph(body, ctx, b, _apply_layout(_ParStyle(h.body_align, ctx.body, after=h.para_after_pt), b, ctx),
                   segment(_unreadable_text(ctx, b), pdir))
    elif t == BlockType.page_break:
        _page_break(body)
    elif t == BlockType.signature_block:
        lines = b.translated_text.split("\n")
        for i, line in enumerate(lines):
            ps = _ParStyle("start", ctx.body, bold=(i == 0), before=8 if i == 0 else 0,
                           after=0.5 if i < len(lines) - 1 else h.para_after_pt)
            ps = _apply_layout(ps, b, ctx)
            if i:
                ps.before = 0
            _paragraph(body, ctx, b, ps, segment(line, pdir))
    else:  # pragma: no cover
        raise ValueError(f"unknown block type {t}")


def _set_doc_language(docx, ctx: _Ctx):
    """Default proofing language for the document (styles docDefaults)."""
    styles = docx.styles.element
    dd = styles.find(qn("w:docDefaults"))
    if dd is None:
        return
    rpr_def = _get_or_add(dd, "w:rPrDefault")
    rpr = _get_or_add(rpr_def, "w:rPr")
    old = rpr.find(qn("w:lang"))
    if old is not None:
        rpr.remove(old)
    lang = {"val": ctx.t.word_tag if ctx.t.font_slot == "ascii" else "en-GB"}
    if ctx.t.font_slot == "cs":
        lang["bidi"] = ctx.t.word_tag
    if ctx.t.font_slot == "eastAsia":
        lang["eastAsia"] = ctx.t.word_tag
    rpr.append(_el("w:lang", **lang))
