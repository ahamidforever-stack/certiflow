"""Golden set tools.

* ``import_docx``: read an approved certified translation (.docx made in the
  office house style) back into the Document model. Layout is recorded only
  where it deviates from the house style, so the model stays what a Formatter
  would produce.
* ``signature`` / ``compare``: a normalised, formatting-aware fingerprint of a
  .docx body, used to prove the Builder regenerates an approved file exactly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document as load_docx
from docx.oxml.ns import qn

from .house import HouseStyle
from .model import Block, BlockType, Direction, Document, InlineRun, Layout, RunKind, TableCell, TableRow
from .profiles import get_profile
from .textdir import LRM, RLM

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_JC = {"left": "start", "start": "start", "right": "end", "end": "end", "both": "justify", "center": "center",
       "distribute": "justify"}


# ------------------------------------------------------------------ parsing

@dataclass
class RunInfo:
    text: str
    bold: bool
    italic: bool
    size: float | None
    color: str | None


@dataclass
class ParInfo:
    runs: list[RunInfo]
    align: str
    before: float
    after: float
    indent: int
    keep_next: bool
    fill: str | None
    page_break: bool

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    @property
    def visible(self) -> str:
        return self.text.replace(LRM, "").replace(RLM, "").strip()


def _attr(el, name):
    return None if el is None else el.get(W + name)


def parse_par(p) -> ParInfo:
    ppr = p.find(W + "pPr")
    g = (lambda t: ppr.find(W + t)) if ppr is not None else (lambda t: None)
    sp, ind, jc, shd = g("spacing"), g("ind"), g("jc"), g("shd")
    runs, brk = [], False
    for r in p.iter(W + "r"):
        if r.find(W + "br") is not None and _attr(r.find(W + "br"), "type") == "page":
            brk = True
        t = "".join(x.text or "" for x in r.iter(W + "t"))
        if not t:
            continue
        rp = r.find(W + "rPr")
        f = (lambda t_: rp.find(W + t_)) if rp is not None else (lambda t_: None)
        sz = _attr(f("szCs"), "val") or _attr(f("sz"), "val")
        col = _attr(f("color"), "val")
        runs.append(RunInfo(t, f("b") is not None or f("bCs") is not None, f("i") is not None or f("iCs") is not None,
                            int(sz) / 2 if sz else None, None if col in (None, "auto", "000000") else col.upper()))
    fill = _attr(shd, "fill")
    return ParInfo(runs=runs, align=_JC.get(_attr(jc, "val") or "start", "start"),
                   before=int(_attr(sp, "before") or 0) / 20, after=int(_attr(sp, "after") or 0) / 20,
                   indent=int(_attr(ind, "start") or _attr(ind, "right") or 0) if ind is not None else 0,
                   keep_next=g("keepNext") is not None,
                   fill=None if fill in (None, "auto") else fill.upper(), page_break=brk)


def _inline(runs: list[RunInfo], base: RunInfo | None = None) -> list[InlineRun]:
    """RunInfo -> InlineRun. LRM-wrapped runs become isolated LTR runs."""
    out = []
    for r in runs:
        t = r.text
        if len(t) > 2 and t.startswith(LRM) and t.endswith(LRM):
            ir = InlineRun(text=t[1:-1], kind=RunKind.identifier, direction=Direction.ltr)
        else:
            ir = InlineRun(text=t)
        upd = {}
        if r.bold and not (base and base.bold):
            upd["bold"] = True
        if r.italic and not (base and base.italic):
            upd["italic"] = True
        if r.color and not (base and base.color == r.color):
            upd["color"] = r.color
        if r.size and not (base and base.size == r.size):
            upd["size_pt"] = r.size
        out.append(ir.model_copy(update=upd))
    return out


def _uniform(runs: list[RunInfo], attr: str):
    vals = {getattr(r, attr) for r in runs if r.text.replace(LRM, "").replace(RLM, "").strip()}
    return vals.pop() if len(vals) == 1 else None


# ------------------------------------------------------------------ import

class _Importer:
    def __init__(self, house: HouseStyle, body_pt: float):
        self.h = house
        self.body = body_pt
        self.n = 0

    def bid(self) -> str:
        self.n += 1
        return f"b{self.n:03d}"

    def defaults(self, kind: str, level: int = 0) -> dict:
        h, b = self.h, self.body
        if kind == "heading" and level == 1:
            return dict(align="center", size=b + h.title_delta_pt, bold=True, keep=True, before=0, after=h.title_after_pt, fill=None, indent=0)
        if kind == "heading" and level == 2:
            return dict(align="start", size=b + h.section_delta_pt, bold=True, keep=True, before=h.section_before_pt,
                        after=h.section_after_pt, fill=h.section_fill, indent=0)
        if kind == "heading":
            return dict(align=h.body_align, size=b + h.subheading_delta_pt, bold=True, keep=True, before=0, after=h.para_after_pt, fill=None, indent=0)
        if kind == "note":
            return dict(align="start", size=b + h.note_delta_pt, bold=False, keep=False, before=0, after=h.para_after_pt, fill=None, indent=0)
        if kind == "bullet":
            return dict(align=h.body_align, size=b, bold=False, keep=False, before=0, after=h.para_after_pt, fill=None, indent=h.bullet_indent_twips)
        return dict(align=h.body_align, size=b, bold=False, keep=False, before=0, after=h.para_after_pt, fill=None, indent=0)

    def layout(self, p: ParInfo, d: dict, size: float | None, bold: bool | None) -> Layout:
        lay = {}
        if p.align != d["align"]:
            lay["align"] = p.align
        if size and abs(size - d["size"]) > 0.01:
            lay["size_pt"] = size
        if bold is not None and bold != d["bold"]:
            lay["bold"] = bold
        if p.keep_next != d["keep"]:
            lay["keep_with_next"] = p.keep_next
        if p.before != d["before"]:
            lay["space_before_pt"] = p.before
        if p.after != d["after"]:
            lay["space_after_pt"] = p.after
        if p.indent != d["indent"]:
            lay["indent_twips"] = p.indent
        if p.fill != d["fill"]:
            lay["fill"] = p.fill or ""
        return Layout(**lay)

    def paragraph(self, p: ParInfo) -> Block:
        h = self.h
        runs = p.runs
        size = _uniform(runs, "size")
        bold = _uniform(runs, "bold")
        text = p.text
        vis = p.visible
        if not vis:
            d = self.defaults("paragraph")
            return Block(id=self.bid(), type=BlockType.paragraph, translated_text=text,
                         runs=[InlineRun(text=text or LRM + LRM, size_pt=runs[0].size if runs else None)],
                         layout=self.layout(p, d, None, None))
        open_, close_ = h.note_wrap.split("{text}")
        if (h.section_fill and p.fill == h.section_fill):
            d = self.defaults("heading", 2)
            return self._text_block(BlockType.heading, p, d, size, bold, level=2)
        if p.align == "center" and bold:
            d = self.defaults("heading", 1)
            return self._text_block(BlockType.heading, p, d, size, bold, level=1)
        if vis.startswith(open_) and vis.endswith(close_) and _uniform(runs, "color") == h.note_color:
            d = self.defaults("note")
            inner = [RunInfo(r.text, r.bold, False, r.size, None) for r in runs]
            # strip the wrap marks from the first and last runs
            inner[0].text = inner[0].text.replace(open_, "", 1)
            k = max(i for i, r in enumerate(inner) if close_ in r.text)
            inner[k].text = inner[k].text[::-1].replace(close_[::-1], "", 1)[::-1]
            inner = [r for r in inner if r.text]
            base = RunInfo("", False, False, size, None)
            return Block(id=self.bid(), type=BlockType.note, translated_text="".join(r.text for r in inner),
                         runs=_inline(inner, base), note_kind=None,
                         layout=self.layout(p, d, size, bold if bold else None))
        m = re.match(rf"^{LRM}([0-9A-Za-z]+){LRM}$", runs[0].text) if runs else None
        if m and len(runs) > 1 and runs[1].text.startswith(".") and RLM in runs[1].text[:3]:
            label = m.group(1) + "."
            rest = [RunInfo(runs[1].text.split(RLM, 1)[1].lstrip(" "), runs[1].bold, runs[1].italic, runs[1].size, runs[1].color)] + runs[2:]
            rest = [r for r in rest if r.text]
            d = self.defaults("paragraph")
            rb = RunInfo("", False, False, size, None)
            return Block(id=self.bid(), type=BlockType.numbered_item, label=label,
                         translated_text="".join(r.text for r in rest), runs=_inline(rest, rb),
                         layout=self.layout(p, d, size, None))
        if vis.startswith("•"):
            first = runs[0].text.replace(h.bullet, "", 1) if runs[0].text.startswith(h.bullet) else runs[0].text.lstrip("• ")
            rest = [RunInfo(first, runs[0].bold, runs[0].italic, runs[0].size, runs[0].color)] + runs[1:]
            rest = [r for r in rest if r.text]
            d = self.defaults("bullet")
            rb = RunInfo("", False, False, size, None)
            return Block(id=self.bid(), type=BlockType.bullet, translated_text="".join(r.text for r in rest),
                         runs=_inline(rest, rb), layout=self.layout(p, d, size, None))
        if bold and p.align != "center":
            d = self.defaults("heading", 3)
            return self._text_block(BlockType.heading, p, d, size, bold, level=3)
        d = self.defaults("paragraph")
        return self._text_block(BlockType.paragraph, p, d, size, bold)

    def _text_block(self, t, p: ParInfo, d: dict, size, bold, level=1) -> Block:
        base = RunInfo("", bool(bold) or d["bold"], False, size or d["size"], None)
        return Block(id=self.bid(), type=t, level=level, translated_text=p.text.replace(LRM, ""),
                     runs=_inline(p.runs, base), layout=self.layout(p, d, size, bold if bold is not None else None))

    def table(self, tbl) -> Block:
        h = self.h
        grid = [int(g.get(W + "w")) for g in tbl.find(W + "tblGrid")]
        rows_raw = []
        for tr in tbl.findall(W + "tr"):
            cells = []
            for tc in tr.findall(W + "tc"):
                tcp = tc.find(W + "tcPr")
                span = int(_attr(tcp.find(W + "gridSpan") if tcp is not None else None, "val") or 1)
                fill = _attr(tcp.find(W + "shd") if tcp is not None else None, "fill")
                pars = [parse_par(p) for p in tc.findall(W + "p")]
                cells.append((span, None if fill in (None, "auto") else fill.upper(), pars))
            rows_raw.append(cells)
        is_kv = all(len(c) % 2 == 0 or len(c) == 2 for c in rows_raw) and all(
            c[i][1] == h.label_fill for c in rows_raw for i in range(0, len(c), 2)) and all(
            c[i][1] != h.label_fill for c in rows_raw for i in range(1, len(c), 2))
        btype = BlockType.kv_table if is_kv else BlockType.table
        all_sizes = [r.size for c in rows_raw for (_, _, ps) in c for p in ps for r in p.runs
                     if r.text.replace(LRM, "").strip()]
        base = max(set(all_sizes), key=all_sizes.count) if all_sizes else self.body
        rows = []
        for cells in rows_raw:
            out = []
            for ci, (span, fill, pars) in enumerate(cells):
                is_label = is_kv and ci % 2 == 0
                runs: list[RunInfo] = []
                for k, p in enumerate(pars):
                    if k:
                        runs.append(RunInfo("\n", False, False, None, None))
                    runs.extend(p.runs or [RunInfo("", False, False, None, None)])
                default_after = h.label_after_pt if is_label else h.value_after_pt
                default_align = "start" if is_label else h.value_align
                rich = any(p.after != default_after or p.align != default_align or p.indent or p.before
                           for p in pars) and not (len(pars) == 1 and pars[0].after == default_after
                                                   and not pars[0].indent and not pars[0].before)
                if rich:
                    out.append(TableCell(translated_text="\n".join(p.text for p in pars).replace(LRM, ""),
                                         colspan=span, blocks=[self.paragraph(p) for p in pars],
                                         fill=(fill if fill != (h.label_fill if is_label else None) else None)
                                         if fill or is_label else None))
                    if is_label and fill is None:
                        out[-1].fill = ""
                    continue
                cb = _uniform([r for r in runs if r.text != "\n"], "bold")
                csize = _uniform([r for r in runs if r.text != "\n"], "size")
                bold_cell = bool(cb) and not is_label
                rb = RunInfo("", bool(cb), False, csize or base, None)
                inl = [ir for ir in _inline([r for r in runs if r.text], rb)]
                # "\n" separators must not carry formatting
                inl = [InlineRun(text="\n") if ir.text == "\n" else ir for ir in inl]
                align = pars[0].align if pars else None
                cell = TableCell(translated_text="".join(r.text for r in runs).replace(LRM, ""), runs=inl,
                                 colspan=span, bold=bold_cell,
                                 fill=(fill if (fill != (h.label_fill if is_label else None)) else None) if fill or is_label else None,
                                 size_pt=csize if csize and csize != base else None,
                                 align=align if align and align != default_align else None)
                if is_label and fill is None:
                    cell.fill = ""
                out.append(cell)
            rows.append(TableRow(cells=out))
        return Block(id=self.bid(), type=btype, rows=rows, column_widths=[float(g) for g in grid],
                     layout=Layout(size_pt=base) if abs(base - self.body) > 0.01 else Layout())


def import_docx(path: Path, source_language: str, target_language: str, house: HouseStyle,
                title: str | None = None) -> Document:
    d = load_docx(str(path))
    imp = _Importer(house, get_profile(target_language).body_size_pt)
    blocks: list[Block] = []
    prev_table = False
    for el in d.element.body:
        tag = el.tag.replace(W, "")
        if tag == "p":
            p = parse_par(el)
            if p.page_break and not p.visible:
                blocks.append(Block(id=imp.bid(), type=BlockType.page_break))
                prev_table = False
                continue
            if prev_table and not p.visible and house.spacer_after_table:
                prev_table = False
                continue  # spacer paragraph, regenerated by the Builder
            blocks.append(imp.paragraph(p))
            prev_table = False
        elif tag == "tbl":
            blocks.append(imp.table(el))
            prev_table = True
    return Document(id=Path(path).stem, title=title or Path(path).stem, source_language=source_language,
                    target_language=target_language, blocks=blocks)


# ------------------------------------------------------------------ compare

def _fp_par(p: ParInfo) -> tuple:
    merged: list[list] = []
    for r in p.runs:
        key = (r.bold, r.italic, r.size, r.color)
        if merged and merged[-1][0] == key:
            merged[-1][1] += r.text
        else:
            merged.append([key, r.text])
    return ("p", p.align, p.before, p.after, p.indent, p.keep_next, p.fill, p.page_break,
            tuple((k, t) for k, t in merged))


def signature(path: Path) -> list[tuple]:
    d = load_docx(str(path))
    out = []
    for el in d.element.body:
        tag = el.tag.replace(W, "")
        if tag == "p":
            out.append(_fp_par(parse_par(el)))
        elif tag == "tbl":
            grid = tuple(int(g.get(W + "w")) for g in el.find(W + "tblGrid"))
            rows = []
            for tr in el.findall(W + "tr"):
                cells = []
                for tc in tr.findall(W + "tc"):
                    tcp = tc.find(W + "tcPr")
                    span = int(_attr(tcp.find(W + "gridSpan") if tcp is not None else None, "val") or 1)
                    fill = _attr(tcp.find(W + "shd") if tcp is not None else None, "fill")
                    cells.append((span, None if fill in (None, "auto") else fill.upper(),
                                  tuple(_fp_par(parse_par(p)) for p in tc.findall(W + "p"))))
                rows.append(tuple(cells))
            out.append(("t", grid, tuple(rows)))
    return out


@dataclass
class CompareResult:
    golden_elements: int
    rebuilt_elements: int
    identical: int
    diffs: list[str]

    @property
    def exact(self) -> bool:
        return not self.diffs and self.golden_elements == self.rebuilt_elements


def compare(golden: Path, rebuilt: Path, max_diffs: int = 20) -> CompareResult:
    import difflib
    a, b = signature(golden), signature(rebuilt)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    diffs, same = [], 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            same += i2 - i1
            continue
        for k in range(max(i2 - i1, j2 - j1)):
            ga = a[i1 + k] if i1 + k < i2 else None
            gb = b[j1 + k] if j1 + k < j2 else None
            diffs.append(f"{op} golden#{i1 + k}: {_short(ga)}\n      rebuilt#{j1 + k}: {_short(gb)}")
    return CompareResult(len(a), len(b), same, diffs[:max_diffs])


def _short(x) -> str:
    return "-" if x is None else repr(x)[:400]


# ------------------------------------------------------------------ harness

def extract_source_from_approved_pdf(pdf: Path, out: Path) -> Path | None:
    """Approved PDFs carry the stamped source pages after the translation. Each
    source page is one full-page scan plus the seal images; take the scan only."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c
    doc = pdfium.PdfDocument(str(pdf))
    ims = []
    try:
        for i in range(len(doc)):
            page = doc[i]
            pw, ph = page.get_width(), page.get_height()
            objs = list(page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=4))
            if not objs:
                continue
            area = lambda o: (o.get_bounds()[2] - o.get_bounds()[0]) * (o.get_bounds()[3] - o.get_bounds()[1])  # noqa: E731
            big = max(objs, key=area)
            if area(big) >= 0.5 * pw * ph:
                ims.append(big.get_bitmap(render=False).to_pil().convert("RGB"))
    finally:
        doc.close()
    if not ims:
        return None
    ims[0].save(out, "PDF", resolution=130, save_all=True, append_images=ims[1:])
    return out


def approved_translation_pages(pdf: Path) -> int:
    """Pages before the first full-page scan."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c
    doc = pdfium.PdfDocument(str(pdf))
    try:
        for i in range(len(doc)):
            page = doc[i]
            pw, ph = page.get_width(), page.get_height()
            for o in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=4):
                l, b, r, t = o.get_bounds()
                if (r - l) * (t - b) >= 0.5 * pw * ph:
                    return i
        return len(doc)
    finally:
        doc.close()


@dataclass
class CaseResult:
    case: str
    pair: str
    body_exact: bool
    body_identical: int
    body_total: int
    tr_pages: int | None
    approved_tr_pages: int | None
    diffs: list[str]


def run_golden_set(root: Path, library, user_id: str, outdir: Path, stamp: str = "certified") -> list[CaseResult]:
    """root/<src>-<tgt>/<case>/approved.docx [approved.pdf] [source.pdf|png|jpg]"""
    from .builder.package import build_package
    from .house import HouseStyle
    from .model import JobSpec
    results = []
    for pair_dir in sorted(p for p in root.iterdir() if p.is_dir() and "-" in p.name):
        src, tgt = pair_dir.name.split("-", 1)
        tpl = library.template_for(tgt, src)
        house = HouseStyle.model_validate(tpl.house_style or {})
        for case in sorted(p for p in pair_dir.iterdir() if p.is_dir()):
            approved = case / "approved.docx"
            if not approved.exists():
                continue
            model = import_docx(approved, src, tgt, house, title=case.name)
            (case / "model.json").write_text(model.model_dump_json(indent=1, exclude_defaults=True), "utf-8")
            apdf = case / "approved.pdf"
            source = next((p for p in sorted(case.glob("source.*"))), None)
            if source is None and apdf.exists():
                source = extract_source_from_approved_pdf(apdf, case / "source.pdf")
            tr_pages = None
            if source is not None:
                res = build_package(model, source, JobSpec(stamp=stamp, user_id=user_id), library,
                                    outdir / pair_dir.name / case.name)
                rebuilt, tr_pages = res.docx, res.translation_pages
            else:
                from .builder.docx_builder import BuildOptions, render
                rebuilt = render(model, library.path(tpl), outdir / pair_dir.name / case.name / "rebuilt.docx",
                                 BuildOptions(house=house, margins_mm=tpl.margins_mm))
            c = compare(approved, rebuilt)
            results.append(CaseResult(case.name, pair_dir.name, c.exact, c.identical, c.golden_elements, tr_pages,
                                      approved_translation_pages(apdf) if apdf.exists() else None, c.diffs))
    return results


# ------------------------------------------------------------------ scoring (pipeline vs approved)

_FIGS = re.compile(r"\d[\d/.,:-]*\d|\d")


def _all_text(doc: Document) -> str:
    parts = []
    for b in doc.blocks:
        if b.multilingual_duplicate:
            continue
        parts.append(b.translated_text)
        parts += [c.translated_text for r in b.rows for c in r.cells]
        for r in b.rows:
            for c in r.cells:
                for blk in c.blocks or []:
                    parts.append(blk.translated_text)
    return "\n".join(p for p in parts if p).replace(LRM, "").replace(RLM, "")


@dataclass
class Score:
    case: str
    figures_recall: float          # figures in the approved translation that the pipeline output also has
    identifiers_recall: float      # IDs/codes/emails in the approved translation found in the output
    length_ratio: float            # output characters / approved characters
    leftover_findings: int         # leftover source-script findings in the output
    open_blockers: int
    passed: bool


def score_against_approved(case: str, output: Document, approved: Document,
                           min_figures: float = 0.95, min_ids: float = 0.95,
                           length_band: tuple[float, float] = (0.75, 1.35)) -> Score:
    from .qa.scan import _IDENT, leftover_source_script
    from .model import Severity
    a, o = _all_text(approved), _all_text(output)
    af, of_ = set(_FIGS.findall(a)), set(_FIGS.findall(o))
    ai, oi = set(_IDENT.findall(a)), o
    fig = len(af & of_) / len(af) if af else 1.0
    ids = sum(1 for x in ai if x in oi) / len(ai) if ai else 1.0
    ratio = len(o) / max(1, len(a))
    left = len(leftover_source_script(output))
    blockers = sum(1 for b in output.blocks for f in b.flags if f.severity == Severity.blocker and not f.resolved)
    ok = fig >= min_figures and ids >= min_ids and length_band[0] <= ratio <= length_band[1] and blockers == 0
    return Score(case, round(fig, 3), round(ids, 3), round(ratio, 3), left, blockers, ok)
