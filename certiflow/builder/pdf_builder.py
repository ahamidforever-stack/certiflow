"""PDF side of the Builder.

translation .docx --LibreOffice--> translation.pdf
source (pdf/images) --pdftoppm--> page images --upright+fit+stamp--> source_stamped.pdf
both --pypdf--> one integrated certified PDF --verify--> release or block
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

from ..model import PageOrder
from .docx_builder import SEAL_MARKER, SEGMENT_MARKER, SealSpec

PT_PER_MM = 72 / 25.4
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


class BuildError(RuntimeError):
    pass


# ------------------------------------------------------------ LibreOffice

def docx_to_pdf(docx: Path, outdir: Path, timeout: int = 180) -> Path:
    """Headless conversion with a private LibreOffice profile (safe in parallel workers)."""
    outdir.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="lo_profile_"))
    filt = 'pdf:writer_pdf_Export:{"ReduceImageResolution":{"type":"boolean","value":"false"},' \
           '"Quality":{"type":"long","value":"90"},"EmbedStandardFonts":{"type":"boolean","value":"true"}}'
    cmd = ["soffice", f"-env:UserInstallation=file://{profile}", "--headless", "--norestore",
           "--convert-to", filt, "--outdir", str(outdir), str(docx)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    out = outdir / (docx.stem + ".pdf")
    if res.returncode != 0 or not out.exists():
        raise BuildError(f"LibreOffice conversion failed: {res.stderr.strip()[:500]}")
    return out


# ------------------------------------------------------------ geometry

@dataclass
class Rect:
    x: float  # points, origin bottom-left
    y: float
    w: float
    h: float

    def overlaps(self, o: "Rect", pad: float = 0) -> bool:
        return not (self.x + self.w + pad <= o.x or o.x + o.w + pad <= self.x or
                    self.y + self.h + pad <= o.y or o.y + o.h + pad <= self.y)


@dataclass
class SealPlacement:
    signature: Rect
    stamp: Rect


def _png_aspect(p: Path) -> float:
    with Image.open(p) as im:
        return im.height / im.width


def find_seal_on_page(pdf: Path, page_index: int, seal: SealSpec) -> SealPlacement | None:
    """Locate signature and stamp images on a rendered page by physical size and aspect."""
    found = _seal_images(pdf, page_index, seal)
    if found["stamp"] and found["signature"]:
        return SealPlacement(signature=found["signature"][0], stamp=found["stamp"][0])
    return None


def _seal_images(pdf: Path, page_index: int, seal: SealSpec, tol: float = 0.04) -> dict[str, list[Rect]]:
    want = {
        "stamp": (seal.stamp_width_mm * PT_PER_MM, _png_aspect(seal.stamp_png)),
        "signature": (seal.signature_width_mm * PT_PER_MM, _png_aspect(seal.signature_png)),
    }
    out: dict[str, list[Rect]] = {"stamp": [], "signature": []}
    doc = pdfium.PdfDocument(str(pdf))
    try:
        page = doc[page_index]
        for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=4):
            l, b, r, t = obj.get_bounds()
            w, h = r - l, t - b
            for k, (ww, asp) in want.items():
                if abs(w - ww) <= ww * tol and abs(h / w - asp) <= asp * tol:
                    out[k].append(Rect(l, b, w, h))
    finally:
        doc.close()
    return out


def page_size(pdf: Path) -> tuple[float, float]:
    r = PdfReader(str(pdf))
    mb = r.pages[0].mediabox
    return float(mb.width), float(mb.height)


# ------------------------------------------------------------ source pages

def rasterize_source(src: Path, workdir: Path, dpi: int = 130) -> list[Image.Image]:
    workdir.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() in IMAGE_EXT:
        ims = []
        with Image.open(src) as im:
            for i in range(getattr(im, "n_frames", 1)):
                im.seek(i)
                ims.append(im.convert("RGB").copy())
        return ims
    prefix = workdir / "src"
    res = subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(src), str(prefix)], capture_output=True, text=True)
    if res.returncode != 0:
        raise BuildError(f"pdftoppm failed: {res.stderr[:300]}")
    files = sorted(workdir.glob("src-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
    return [Image.open(f).convert("RGB") for f in files]


def upright(im: Image.Image, rotation: int = 0) -> Image.Image:
    """Apply the Intake rotation (if known), then turn landscape pages to portrait."""
    if rotation:
        im = im.rotate(-rotation, expand=True)
    if im.width > im.height:
        im = im.rotate(90, expand=True)
    return im


def _ink_integral(im: Image.Image, pw: float, ph: float, place: Rect) -> np.ndarray:
    """Integral image of dark pixels on a 1 px = 1 pt canvas of the page."""
    canvas = Image.new("L", (int(round(pw)), int(round(ph))), 255)
    g = im.convert("L").resize((max(1, int(place.w)), max(1, int(place.h))))
    canvas.paste(g, (int(place.x), int(ph - place.y - place.h)))
    ink = (np.asarray(canvas) < 150).astype(np.int32)
    return np.pad(ink.cumsum(0).cumsum(1), ((1, 0), (1, 0)))


def _ink(ii: np.ndarray, r: Rect, ph: float) -> float:
    x0, x1 = int(max(0, r.x)), int(min(ii.shape[1] - 1, r.x + r.w))
    top = int(max(0, ph - r.y - r.h))
    bot = int(min(ii.shape[0] - 1, ph - r.y))
    s = ii[bot, x1] - ii[top, x1] - ii[bot, x0] + ii[top, x0]
    return float(s) / max(1.0, r.w * r.h)


def choose_position(ii: np.ndarray, pw: float, ph: float, default: Rect, avoid: Rect | None,
                    margin: float = 6 * PT_PER_MM, step: float = 4 * PT_PER_MM) -> tuple[Rect, float]:
    """Least-ink position for a seal image of fixed size.

    The translation-footer position wins unless another position covers clearly
    less source ink; candidates are penalised by distance so seals stay near the
    footer when the page is uniformly dense.
    """
    best, best_score, best_ink = default, None, 0.0
    diag = (pw ** 2 + ph ** 2) ** 0.5
    ys = np.arange(margin, ph - default.h - margin + 1, step)
    xs = np.arange(margin, pw - default.w - margin + 1, step)
    cands = [default] + [Rect(float(x), float(y), default.w, default.h) for y in ys for x in xs]
    for r in cands:
        if avoid and r.overlaps(avoid, pad=2 * PT_PER_MM):
            continue
        ink = _ink(ii, r, ph)
        dist = ((r.x - default.x) ** 2 + (r.y - default.y) ** 2) ** 0.5 / diag
        score = ink + 0.03 * dist
        if best_score is None or score < best_score - 1e-9:
            best, best_score, best_ink = r, score, ink
    return best, best_ink


@dataclass
class SourceStampReport:
    pages: int = 0
    ink_covered: list[float] = field(default_factory=list)   # fraction of seal area over dark pixels, per page
    dense_pages: list[int] = field(default_factory=list)      # 1-based source pages where the seal covers text


def stamp_source_pages(images: list[Image.Image], out: Path, page_w: float, page_h: float,
                       seal: SealSpec, footer: SealPlacement, jpeg_quality: int = 80,
                       margin_mm: float = 5.0, dense_threshold: float = 0.004,
                       source_layout: dict | None = None) -> SourceStampReport:
    """Two modes. ``overlay`` (default): scan fills the page, seal placed where it covers
    least ink. ``band`` (office convention from the template): scan fitted into
    ``area_mm`` and the seal drawn at fixed positions in the free band, so it never
    covers the source."""
    band = bool(source_layout and source_layout.get("mode") == "band")
    rep = SourceStampReport(pages=len(images))
    c = rl_canvas.Canvas(str(out), pagesize=(page_w, page_h), pageCompression=1)
    c.setTitle("source")
    tmpd = Path(tempfile.mkdtemp(prefix="srcjpg_"))
    try:
        for i, im in enumerate(images):
            if band:
                a = {k: v * PT_PER_MM for k, v in source_layout["area_mm"].items()}
                bw, bh = page_w - a["left"] - a["right"], page_h - a["top"] - a["bottom"]
                scale = min(bw / im.width, bh / im.height)
                w, h = im.width * scale, im.height * scale
                place = Rect(a["left"] + (bw - w) / 2, a["bottom"] + (bh - h) / 2, w, h)
            else:
                m = margin_mm * PT_PER_MM
                scale = min((page_w - 2 * m) / im.width, (page_h - 2 * m) / im.height)
                w, h = im.width * scale, im.height * scale
                place = Rect((page_w - w) / 2, (page_h - h) / 2, w, h)
            # grayscale scans save as 1-channel JPEG (smaller)
            arr = np.asarray(im.resize((64, 64)), dtype=np.int16)
            is_gray = np.abs(arr[..., 0] - arr[..., 1]).max() < 12 and np.abs(arr[..., 1] - arr[..., 2]).max() < 12
            jp = tmpd / f"p{i:04d}.jpg"
            (im.convert("L") if is_gray else im).save(jp, "JPEG", quality=jpeg_quality, optimize=True)
            c.drawImage(str(jp), place.x, place.y, w, h)

            ii = _ink_integral(im, page_w, page_h, place)
            if band and {"stamp", "signature"} <= set(source_layout.get("seal", {})):
                def fixed(key: str, size: Rect) -> Rect:
                    pos = source_layout["seal"][key]
                    return Rect(pos["cx_mm"] * PT_PER_MM - size.w / 2,
                                page_h - pos["cy_mm"] * PT_PER_MM - size.h / 2, size.w, size.h)
                st, sg = fixed("stamp", footer.stamp), fixed("signature", footer.signature)
                ink_st, ink_sg = _ink(ii, st, page_h), _ink(ii, sg, page_h)
            else:
                st, ink_st = choose_position(ii, page_w, page_h, footer.stamp, avoid=None)
                sg, ink_sg = choose_position(ii, page_w, page_h, footer.signature, avoid=st)
            c.drawImage(str(seal.signature_png), sg.x, sg.y, sg.w, sg.h, mask="auto")
            c.drawImage(str(seal.stamp_png), st.x, st.y, st.w, st.h, mask="auto")
            t = c.beginText(2, 2)
            t.setTextRenderMode(3)  # invisible
            t.setFont("Helvetica", 1)
            t.textLine(seal.marker)
            c.drawText(t)
            ink = max(ink_st, ink_sg)
            rep.ink_covered.append(ink)
            if ink > dense_threshold:
                rep.dense_pages.append(i + 1)
            c.showPage()
        c.save()
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    return rep


# ------------------------------------------------------------ merge

def _page_texts(pdf: Path) -> list[str]:
    return [(p.extract_text() or "") for p in PdfReader(str(pdf)).pages]


def merge(translation_pdf: Path, source_pdf: Path, out: Path, order: PageOrder) -> tuple[Path, str]:
    """Returns (path, effective_order). Interleaving falls back to
    translation-then-source when the page mapping is not reliable."""
    tr, sr = PdfReader(str(translation_pdf)), PdfReader(str(source_pdf))
    w = PdfWriter()
    effective = PageOrder.translation_then_source.value
    plan: list[tuple[str, int]] | None = None
    if order == PageOrder.interleaved:
        plan = _interleave_plan(_page_texts(translation_pdf), len(sr.pages))
    if plan:
        effective = PageOrder.interleaved.value
        for kind, idx in plan:
            w.add_page((tr if kind == "t" else sr).pages[idx])
    else:
        for p in tr.pages:
            w.add_page(p)
        for p in sr.pages:
            w.add_page(p)
    w.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    with open(out, "wb") as f:
        w.write(f)
    return out, effective


def _interleave_plan(t_texts: list[str], n_src: int) -> list[tuple[str, int]] | None:
    seg_of_page: list[int | None] = []
    cur = None
    for txt in t_texts:
        import re
        m = re.findall(rf"{SEGMENT_MARKER}(\d{{3}})", txt)
        if m:
            nums = [int(x) for x in m]
            if cur is not None and nums[0] <= cur:
                return None
            cur = nums[-1]
        seg_of_page.append(cur)
    if any(s is None for s in seg_of_page) or not seg_of_page:
        return None
    used = sorted(set(seg_of_page))
    if used[-1] > n_src:
        return None
    plan: list[tuple[str, int]] = []
    src_done = 0
    for i, s in enumerate(seg_of_page):
        plan.append(("t", i))
        last_of_seg = i == len(seg_of_page) - 1 or seg_of_page[i + 1] != s
        if last_of_seg:
            nxt = seg_of_page[i + 1] if i + 1 < len(seg_of_page) else n_src + 1
            # this source page, plus any source pages with no translated blocks before the next segment
            for sp in range(max(src_done + 1, s), nxt):
                plan.append(("s", sp - 1))
            src_done = nxt - 1
    for sp in range(src_done + 1, n_src + 1):
        plan.append(("s", sp - 1))
    return plan


# ------------------------------------------------------------ verification

@dataclass
class VerifyResult:
    ok: bool
    pages: int
    expected_pages: int
    failures: list[str]


def verify_certified_pdf(pdf: Path, seal: SealSpec, expected_pages: int) -> VerifyResult:
    """Release gate: page count, and on every page the seal marker plus a
    signature image and a stamp image at the exact physical size."""
    fails: list[str] = []
    r = PdfReader(str(pdf))
    n = len(r.pages)
    if n != expected_pages:
        fails.append(f"page count {n} != expected {expected_pages}")
    for i, p in enumerate(r.pages):
        txt = p.extract_text() or ""
        if seal.marker not in txt.replace(" ", ""):
            fails.append(f"page {i + 1}: seal marker missing")
        found = _seal_images(pdf, i, seal)
        if not found["stamp"]:
            fails.append(f"page {i + 1}: stamp image missing or wrong size")
        if not found["signature"]:
            fails.append(f"page {i + 1}: signature image missing or wrong size")
    return VerifyResult(ok=not fails, pages=n, expected_pages=expected_pages, failures=fails)


def text_seal_overlaps(pdf: Path, seal: SealSpec, pages: range | None = None) -> list[str]:
    """Translation pages: any visible character whose box intersects the seal images."""
    problems = []
    doc = pdfium.PdfDocument(str(pdf))
    try:
        idxs = pages if pages is not None else range(len(doc))
        for i in idxs:
            found = _seal_images(pdf, i, seal)
            rects = found["stamp"] + found["signature"]
            tp = doc[i].get_textpage()
            for ci in range(tp.count_chars()):
                ch = tp.get_text_range(ci, 1)
                if not ch.strip():
                    continue
                l, b, rr, t = tp.get_charbox(ci)
                if (t - b) < 2:  # 1pt hidden marker
                    continue
                cr = Rect(l, b, rr - l, t - b)
                if any(cr.overlaps(s) for s in rects):
                    problems.append(f"page {i + 1}: '{ch}' overlaps seal")
                    break
    finally:
        doc.close()
    return problems
