"""Deterministic Word renderer: Document model -> .docx on the office template.

Two font modes from the same model:
  * ``word`` - the release .docx, using each profile's Word font.
  * ``pdf``  - an identical document using the profile's embedded open font,
               converted by LibreOffice (which does not have proprietary Word fonts).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from docx import Document as load_docx
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

from ..model import Block, BlockType, Direction, Document, InlineRun, PageOrder, RunKind, TableCell
from ..profiles import LanguageProfile, ResolvedPair, resolve_pair
from ..textdir import infer_direction, isolate, needs_isolation, segment

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
    layout: dict | None = None            # template seal layout (page-relative centres, mm)
    strip_images: list[str] = field(default_factory=list)  # sha1 of template footer images to remove


@dataclass
class BuildOptions:
    font_mode: FontMode = "word"
    isolation_style: Literal["marks", "isolate"] = "marks"
    page_order: PageOrder = PageOrder.translation_then_source
    seal: SealSpec | None = None
    _end_notes: list[Block] = field(default_factory=list)


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


class _Ctx:
    def __init__(self, doc_model: Document, pair: ResolvedPair, opts: BuildOptions, text_width_twips: int):
        self.m = doc_model
        self.pair = pair
        self.t: LanguageProfile = pair.target
        self.opts = opts
        self.dir = self.t.direction
        self.width = text_width_twips

    def font(self, slot: str) -> str:
        if slot == self.t.font_slot:
            return self.t.word_font if self.opts.font_mode == "word" else self.t.pdf_font
        s = self.pair.source
        if slot == s.font_slot and s.font_slot != "ascii":
            return s.word_font if self.opts.font_mode == "word" else s.pdf_font
        return FALLBACK[slot][self.opts.font_mode]


# ------------------------------------------------------------------- runs

def _run_props(ctx: _Ctx, *, size_pt: float, bold: bool, italic: bool, rtl: bool, proof: bool,
               color: str | None = None):
    rpr = _el("w:rPr")
    rpr.append(_el("w:rFonts", ascii=ctx.font("ascii"), hAnsi=ctx.font("ascii"),
                   cs=ctx.font("cs"), eastAsia=ctx.font("eastAsia")))
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


def _add_runs(p_el, ctx: _Ctx, runs: list[InlineRun], pdir: Direction, size_pt: float, bold: bool):
    for run in runs:
        iso = needs_isolation(run, pdir)
        rdir = run.direction or infer_direction(run.text) or pdir
        text = isolate(run.text, rdir, ctx.opts.isolation_style) if iso else run.text
        _add_run(p_el, ctx, text, size_pt=size_pt, bold=bold or run.bold, italic=run.italic,
                 rtl=(rdir == Direction.rtl and not (iso and rdir == Direction.ltr)),
                 proof=run.kind in (RunKind.text, RunKind.name))


def _runs_for(text: str, runs: list[InlineRun] | None, pdir: Direction) -> list[InlineRun]:
    return runs if runs else segment(text, pdir)


# ------------------------------------------------------------- paragraphs

def _new_par(ctx: _Ctx, pdir: Direction, *, align: str | None, keep_next=False, space_before=0.0,
             space_after=6.0, indent_level=0, line=None):
    p = _el("w:p")
    ppr = _el("w:pPr")
    if keep_next:
        ppr.append(_el("w:keepNext"))
    if pdir == Direction.rtl:
        ppr.append(_el("w:bidi"))
    ppr.append(_el("w:spacing", before=int(space_before * 20), after=int(space_after * 20),
                   line=int(240 * (line or ctx.t.line_spacing)), lineRule="auto"))
    if indent_level:
        ppr.append(_el("w:ind", start=360 * indent_level))
    # In bidi paragraphs Word treats left/right relative to the reading direction.
    jc = {"start": "left", "end": "right", "center": "center", "justify": "both"}[
        align or ("justify" if ctx.t.justify else "start")]
    ppr.append(_el("w:jc", val=jc))
    p.append(ppr)
    return p


def _block_dir(ctx: _Ctx, b: Block) -> Direction:
    return b.direction or ctx.dir


def _render_text_block(body, ctx: _Ctx, b: Block, *, prefix_runs: list[InlineRun] | None = None,
                       text: str | None = None, align=None, bold=False, scale=1.0, keep_next=False,
                       space_before=0.0, space_after=6.0):
    pdir = _block_dir(ctx, b)
    lay = b.layout
    p = _new_par(ctx, pdir, align=lay.align or align, keep_next=lay.keep_with_next or keep_next,
                 space_before=lay.space_before_pt if lay.space_before_pt is not None else space_before,
                 space_after=lay.space_after_pt if lay.space_after_pt is not None else space_after,
                 indent_level=lay.indent_level)
    size = ctx.t.body_size_pt * scale * lay.font_scale
    runs = list(prefix_runs or []) + _runs_for(text if text is not None else b.translated_text,
                                               None if text is not None else b.runs, pdir)
    _add_runs(p, ctx, runs, pdir, size, bold if lay.bold is None else lay.bold)
    body.append(p)
    return p


def _note_text(ctx: _Ctx, text: str) -> str:
    lb = ctx.t.labels
    return f"{lb.note_open} {text.strip()} {lb.note_close}"


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

def _cell_borders():
    b = _el("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b.append(_el(f"w:{side}", val="single", sz=4, space=0, color="808080"))
    return b


def _render_table(body, ctx: _Ctx, b: Block):
    pdir = _block_dir(ctx, b)
    ncols = max(sum(c.colspan for c in r.cells) for r in b.rows)
    rel = b.column_widths or ([0.35, 0.65] if b.type == BlockType.kv_table else [1.0] * ncols)
    tot = sum(rel)
    widths = [int(ctx.width * w / tot) for w in rel]

    tbl = _el("w:tbl")
    tpr = _el("w:tblPr")
    tpr.append(_el("w:tblW", w=sum(widths), type="dxa"))
    if pdir == Direction.rtl:
        tpr.append(_el("w:bidiVisual"))
    tpr.append(_el("w:jc", val="center"))
    tpr.append(_cell_borders())
    tpr.append(_el("w:tblLayout", type="fixed"))
    mar = _el("w:tblCellMar")
    for side in ("top", "bottom"):
        mar.append(_el(f"w:{side}", w=40, type="dxa"))
    for side in ("start", "end", "left", "right"):
        mar.append(_el(f"w:{side}", w=100, type="dxa"))
    tpr.append(mar)
    tbl.append(tpr)
    grid = _el("w:tblGrid")
    for w in widths:
        grid.append(_el("w:gridCol", w=w))
    tbl.append(grid)

    size = ctx.t.body_size_pt * b.layout.font_scale * (0.92 if ncols > 3 else 1.0)
    for row in b.rows:
        tr = _el("w:tr")
        trpr = _el("w:trPr")
        trpr.append(_el("w:cantSplit"))
        if row.header:
            trpr.append(_el("w:tblHeader"))
        tr.append(trpr)
        col = 0
        for ci, cell in enumerate(row.cells):
            tc = _el("w:tc")
            tcpr = _el("w:tcPr")
            tcpr.append(_el("w:tcW", w=sum(widths[col:col + cell.colspan]), type="dxa"))
            if cell.colspan > 1:
                tcpr.append(_el("w:gridSpan", val=cell.colspan))
            if row.header or cell.header:
                tcpr.append(_el("w:shd", val="clear", color="auto", fill="E7E6E6"))
            tc.append(tcpr)
            col += cell.colspan
            is_key = b.type == BlockType.kv_table and ci == 0
            bold = cell.bold or row.header or cell.header or is_key
            _cell_paragraphs(tc, ctx, cell, pdir, size, bold, center=row.header or cell.header)
            tr.append(tc)
        tbl.append(tr)
    body.append(tbl)
    # spacer paragraph so consecutive tables do not merge
    body.append(_new_par(ctx, pdir, align="start", space_after=4))


def _cell_paragraphs(tc, ctx: _Ctx, cell: TableCell, pdir: Direction, size: float, bold: bool, center: bool):
    lines = (cell.translated_text or "").split("\n") if not cell.runs else [None]
    for line in lines:
        p = _new_par(ctx, pdir, align="center" if center else "start", space_after=0, line=1.0)
        runs = cell.runs if line is None else segment(line, pdir)
        _add_runs(p, ctx, runs, pdir, size, bold)
        tc.append(p)


# ------------------------------------------------------------------ footer

def _active_footers(docx):
    out = []
    for section in docx.sections:
        out.append((section, section.footer))
        if docx.settings.odd_and_even_pages_header_footer:
            out.append((section, section.even_page_footer))
        if section.different_first_page_header_footer:
            out.append((section, section.first_page_footer))
    return out


def _strip_baked_seal(docx, strip: list[str]):
    import hashlib
    blip_tag = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
    embed = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
    for _, ft in _active_footers(docx):
        for d in list(ft._element.iter(qn("w:drawing"))):
            blip = next(d.iter(blip_tag), None)
            if blip is None:
                continue
            part = ft.part.related_parts.get(blip.get(embed))
            if part is not None and hashlib.sha1(part.blob).hexdigest() in strip:
                run = d.getparent()
                run.getparent().remove(run)


_ANCHOR_XML = """<w:r %s><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="%d"
 behindDoc="0" locked="1" layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/>
<wp:positionH relativeFrom="page"><wp:posOffset>%d</wp:posOffset></wp:positionH>
<wp:positionV relativeFrom="page"><wp:posOffset>%d</wp:posOffset></wp:positionV>
<wp:extent cx="%d" cy="%d"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>
<wp:docPr id="%d" name="%s"/><wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>
<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>
<pic:nvPicPr><pic:cNvPr id="0" name="%s.png"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
</pic:pic></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>"""


def _anchored_seal(docx, ctx: _Ctx, seal: SealSpec):
    """Floating signature + stamp at the template's measured position, on every
    page. Kept below the body text area (top clamped to the bottom margin)."""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    from PIL import Image
    EMU = 36000
    _strip_baked_seal(docx, seal.strip_images)
    n = 0
    for section, ft in _active_footers(docx):
        ft.is_linked_to_previous = False
        body_bottom_mm = (section.page_height - section.bottom_margin) / EMU
        par = ft.paragraphs[0] if ft.paragraphs else ft.add_paragraph()
        for key, png, width_mm in (("signature", seal.signature_png, seal.signature_width_mm),
                                   ("stamp", seal.stamp_png, seal.stamp_width_mm)):
            pos = seal.layout[key]
            with Image.open(png) as im:
                h_mm = width_mm * im.height / im.width
            top = max(pos["cy_mm"] - h_mm / 2, body_bottom_mm + 0.5)
            left = pos["cx_mm"] - width_mm / 2
            rid, _ = ft.part.get_or_add_image(str(png))
            n += 1
            xml = _ANCHOR_XML % (nsdecls("w", "wp", "a", "pic", "r"), 251700000 + n, int(left * EMU), int(top * EMU),
                                 int(width_mm * EMU), int(h_mm * EMU), 9000 + n, f"CertiFlow {key} {n}", key, rid,
                                 int(width_mm * EMU), int(h_mm * EMU))
            par._p.append(parse_xml(xml))
        _hidden_marker(par._p, ctx, seal.marker)


def _install_seal(docx, ctx: _Ctx, seal: SealSpec):
    if seal.layout:
        return _anchored_seal(docx, ctx, seal)
    return _inline_seal(docx, ctx, seal)


def _inline_seal(docx, ctx: _Ctx, seal: SealSpec):
    """Signature (left) and stamp (right) as inline pictures at the top of every
    footer. Inline footer content grows the footer, so body text can never run
    underneath the seal."""
    for section in docx.sections:
        footers = [section.footer]
        if section.different_first_page_header_footer:
            footers.append(section.first_page_footer)
        if docx.settings.odd_and_even_pages_header_footer:
            footers.append(section.even_page_footer)
        text_w = section.page_width - section.left_margin - section.right_margin
        for ft in footers:
            ft.is_linked_to_previous = False
            par = ft.add_paragraph()
            # move to top of footer
            ft._element.remove(par._p)
            ft._element.insert(0, par._p)
            pf = par.paragraph_format
            pf.space_before = Pt(0)
            pf.space_after = Pt(2)
            pf.tab_stops.add_tab_stop(text_w, WD_TAB_ALIGNMENT.RIGHT)
            par.add_run().add_picture(str(seal.signature_png), width=Mm(seal.signature_width_mm))
            par.add_run("\t")
            par.add_run().add_picture(str(seal.stamp_png), width=Mm(seal.stamp_width_mm))
            _hidden_marker(par._p, ctx, seal.marker)


def _hidden_marker(p_el, ctx: _Ctx, text: str):
    _add_run(p_el, ctx, text, size_pt=1, color="FFFFFF", proof=False)


# ------------------------------------------------------------------- build

def _clear_body(docx):
    body = docx.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def render(model: Document, template: Path, out: Path, opts: BuildOptions) -> Path:
    pair = resolve_pair(model.source_language, model.target_language)
    docx = load_docx(str(template))
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
            mp = _new_par(ctx, ctx.dir, align="start", space_after=0, line=1.0)
            _hidden_marker(mp, ctx, f"{SEGMENT_MARKER}{b.source_page:03d}")
            tmp.append(mp)
        _render_block(tmp, ctx, b, end_notes)

    if end_notes:
        seen: set[str] = set()
        uniq = [n for n in end_notes if not (n.translated_text.strip() in seen or seen.add(n.translated_text.strip()))]
        hb = Block(id="_end_heading", type=BlockType.heading, translated_text=ctx.t.labels.repeated_notes_heading)
        _render_text_block(tmp, ctx, hb, align="center", bold=True, keep_next=True, space_before=12)
        for n in uniq:
            _render_text_block(tmp, ctx, n, text=_note_text(ctx, n.translated_text))

    for child in list(tmp):
        sect_pr.addprevious(child)

    if opts.seal:
        _install_seal(docx, ctx, opts.seal)
    _set_doc_language(docx, ctx)
    out.parent.mkdir(parents=True, exist_ok=True)
    docx.save(str(out))
    return out


def _render_block(body, ctx: _Ctx, b: Block, end_notes: list[Block]):
    t = b.type
    if t == BlockType.heading:
        scale = ctx.t.heading_scale if b.level == 1 else max(1.0, ctx.t.heading_scale - 0.1 * (b.level - 1))
        _render_text_block(body, ctx, b, align="center", bold=True, scale=scale, keep_next=True,
                           space_before=6 if b.level == 1 else 4)
    elif t == BlockType.paragraph:
        _render_text_block(body, ctx, b)
    elif t == BlockType.numbered_item:
        label = (b.label or "").strip()
        pre = [InlineRun(text=label, kind=RunKind.number, direction=Direction.ltr), InlineRun(text=" ")] if label else []
        b2 = b.model_copy(update={"layout": b.layout.model_copy(update={"indent_level": max(b.layout.indent_level, 0)})})
        _render_text_block(body, ctx, b2, prefix_runs=pre)
    elif t == BlockType.bullet:
        _render_text_block(body, ctx, b, prefix_runs=[InlineRun(text="• ")])
    elif t in (BlockType.table, BlockType.kv_table):
        _render_table(body, ctx, b)
    elif t == BlockType.note:
        if b.note_scope == "document_end":
            end_notes.append(b)
        else:
            _render_text_block(body, ctx, b, text=_note_text(ctx, b.translated_text), align="start")
    elif t == BlockType.unreadable:
        _render_text_block(body, ctx, b, text=_unreadable_text(ctx, b))
    elif t == BlockType.page_break:
        _page_break(body)
    elif t == BlockType.signature_block:
        for i, line in enumerate(b.translated_text.split("\n")):
            _render_text_block(body, ctx, b, text=line, align="start", bold=(i == 0), space_after=0,
                               space_before=8 if i == 0 else 0)
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
