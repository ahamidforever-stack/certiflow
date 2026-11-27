"""Template import: learn the office's seal layout from the template itself.

Many office templates already carry a signature and stamp in one footer (often
only the even-page footer). At import we:
  1. find footer images that are not shared by every active footer (= baked-in seal),
  2. tell stamp from signature by comparing with the library's assets,
  3. render the template with LibreOffice and measure where those images sit on the page.
The Builder then strips the baked-in images and draws the job's chosen stamp
and the translator's signature at exactly that place on every page.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import numpy as np
from docx import Document as load_docx
from docx.oxml.ns import qn
from PIL import Image

from .builder.pdf_builder import docx_to_pdf

A_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
WP_EXTENT = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent"


def active_footers(docx):
    out = []
    for si, s in enumerate(docx.sections):
        out.append((si, "default", s.footer))
        if docx.settings.odd_and_even_pages_header_footer:
            out.append((si, "even", s.even_page_footer))
        if s.different_first_page_header_footer:
            out.append((si, "first", s.first_page_footer))
    return out


def footer_images(footer) -> list[dict]:
    imgs = []
    for d in footer._element.iter(qn("w:drawing")):
        blip = next(d.iter(A_BLIP), None)
        if blip is None:
            continue
        part = footer.part.related_parts[blip.get(R_EMBED)]
        ext = next(d.iter(WP_EXTENT))
        imgs.append({"sha1": hashlib.sha1(part.blob).hexdigest(), "blob": part.blob,
                     "w_mm": int(ext.get("cx")) / 36000, "h_mm": int(ext.get("cy")) / 36000})
    return imgs


def baked_seal_images(path: Path) -> list[dict]:
    d = load_docx(str(path))
    feet = [(kind, footer_images(f)) for _, kind, f in active_footers(d)]
    if len(feet) < 2:
        return []
    common = set.intersection(*[{i["sha1"] for i in imgs} for _, imgs in feet])
    seen, out = set(), []
    for kind, imgs in feet:
        for i in imgs:
            if i["sha1"] not in common and i["sha1"] not in seen:
                seen.add(i["sha1"])
                out.append(dict(i, footer=kind))
    return out


def _sig(img: Image.Image) -> np.ndarray:
    g = img.convert("RGBA")
    bg = Image.new("RGBA", g.size, (255, 255, 255, 255))
    bg.alpha_composite(g)
    gray = bg.convert("L")
    ink = np.asarray(gray) < 200
    if ink.any():  # compare ink only: crop away paper margins
        ys, xs = np.nonzero(ink)
        gray = gray.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    a = np.asarray(gray.resize((64, 40)), dtype=np.float32)
    a = 255 - a
    return (a - a.mean()) / (a.std() + 1e-6)


def similarity(a: Image.Image, b: Image.Image) -> float:
    return float((_sig(a) * _sig(b)).mean())


def classify(baked: list[dict], signature_png: Path, stamp_pngs: list[Path]) -> dict[str, dict]:
    """Map 'signature' and 'stamp' to baked images by visual similarity."""
    import io
    sig_ref = Image.open(signature_png)
    stamp_refs = [Image.open(p) for p in stamp_pngs]
    scored = []
    for b in baked:
        im = Image.open(io.BytesIO(b["blob"]))
        s_sig = similarity(im, sig_ref)
        s_st = max(similarity(im, r) for r in stamp_refs)
        scored.append((b, s_sig, s_st))
    out = {}
    if scored:
        out["signature"] = max(scored, key=lambda t: t[1] - t[2])[0]
        rest = [t for t in scored if t[0] is not out["signature"]]
        if rest:
            out["stamp"] = max(rest, key=lambda t: t[2] - t[1])[0]
    return out


def measure_positions(path: Path, items: dict[str, dict]) -> dict[str, dict]:
    """Render the template (enough pages to show every footer) and measure the
    centre of each baked image, in mm from the page's top-left corner."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c
    d = load_docx(str(path))
    body = d.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)
    sect = body.find(qn("w:sectPr"))
    from docx.oxml import OxmlElement
    for i in range(3):
        p = OxmlElement("w:p")
        if i:
            r = OxmlElement("w:r")
            br = OxmlElement("w:br")
            br.set(qn("w:type"), "page")
            r.append(br)
            p.append(r)
        sect.addprevious(p)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "probe.docx"
        d.save(str(src))
        pdf = docx_to_pdf(src, Path(td))
        doc = pdfium.PdfDocument(str(pdf))
        out = {}
        try:
            for i in range(len(doc)):
                page = doc[i]
                ph = page.get_height()
                for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=4):
                    l, b, r, t = obj.get_bounds()
                    w_mm, h_mm = (r - l) * 25.4 / 72, (t - b) * 25.4 / 72
                    for k, it in items.items():
                        if k not in out and abs(w_mm - it["w_mm"]) < 1.0 and abs(h_mm - it["h_mm"]) < 1.0:
                            out[k] = {"cx_mm": round((l + r) / 2 * 25.4 / 72, 2),
                                      "cy_mm": round((ph - (b + t) / 2) * 25.4 / 72, 2),
                                      "box_w_mm": round(w_mm, 2), "box_h_mm": round(h_mm, 2)}
        finally:
            doc.close()
    return out


def import_template(path: Path, signature_png: Path, stamp_pngs: list[Path]) -> dict:
    """Returns the template asset fields: seal_layout and strip_footer_images."""
    baked = baked_seal_images(path)
    cls = classify(baked, signature_png, stamp_pngs)
    layout = measure_positions(path, cls) if cls else {}
    return {"seal_layout": layout or None, "strip_footer_images": [b["sha1"] for b in baked]}


def all_footer_images(path: Path) -> list[dict]:
    d = load_docx(str(path))
    seen, out = set(), []
    for _, kind, f in active_footers(d):
        for i in footer_images(f):
            if i["sha1"] not in seen:
                seen.add(i["sha1"])
                out.append(dict(i, footer=kind))
    return out


def seal_from_reference(reference: Path, signature_png: Path, stamp_pngs: list[Path], min_sim: float = 0.25) -> dict:
    """Seal layout (ink centre and ink width, mm) and page margins from an approved
    output whose footers carry the seal on every page."""
    import io
    import tempfile as _tf

    from .imageprep import remove_background
    imgs = all_footer_images(reference)
    sig_ref = Image.open(signature_png)
    st_refs = [Image.open(p) for p in stamp_pngs]
    best: dict[str, tuple[float, dict]] = {}
    for b in imgs:
        im = Image.open(io.BytesIO(b["blob"]))
        s_sig, s_st = similarity(im, sig_ref), max(similarity(im, r) for r in st_refs)
        for k, s, other in (("signature", s_sig, s_st), ("stamp", s_st, s_sig)):
            if s >= min_sim and s > other and (k not in best or s > best[k][0]):
                best[k] = (s, b)
    items = {k: v[1] for k, v in best.items()}
    boxes = measure_positions(reference, items)
    layout = {}
    for k, b in items.items():
        if k not in boxes:
            continue
        with _tf.TemporaryDirectory() as td:
            src = Path(td) / "b.png"
            src.write_bytes(b["blob"])
            r = remove_background(src, Path(td) / "o.png")
        (x0, y0, x1, y1), (W_, H_) = r["crop"], r["source_size"]
        box = boxes[k]
        sx, sy = box["box_w_mm"] / W_, box["box_h_mm"] / H_
        left = box["cx_mm"] - box["box_w_mm"] / 2
        top = box["cy_mm"] - box["box_h_mm"] / 2
        layout[k] = {"cx_mm": round(left + (x0 + x1) / 2 * sx, 2), "cy_mm": round(top + (y0 + y1) / 2 * sy, 2),
                     "width_mm": round((x1 - x0) * sx, 1)}
    s = load_docx(str(reference)).sections[0]
    margins = {"top": round(s.top_margin.mm, 2), "bottom": round(s.bottom_margin.mm, 2),
               "left": round(s.left_margin.mm, 2), "right": round(s.right_margin.mm, 2)}
    return {"seal_layout": layout, "margins_mm": margins}


def source_layout_from_reference_pdf(pdf: Path, signature_png: Path, stamp_pngs: list[Path]) -> dict | None:
    """Office convention for source pages, measured on an approved PDF: the box the
    scan is fitted into, and the seal positions (ink centres, mm from top-left)."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c
    import tempfile as _tf

    from .imageprep import remove_background
    sig_ref = Image.open(signature_png)
    st_refs = [Image.open(p) for p in stamp_pngs]
    doc = pdfium.PdfDocument(str(pdf))
    mm = lambda v: v * 25.4 / 72  # noqa: E731
    try:
        for i in range(len(doc)):
            page = doc[i]
            pw, ph = page.get_width(), page.get_height()
            objs = list(page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=4))
            if not objs:
                continue
            big = max(objs, key=lambda o: (o.get_bounds()[2] - o.get_bounds()[0]) * (o.get_bounds()[3] - o.get_bounds()[1]))
            l, b, r, t = big.get_bounds()
            if (r - l) * (t - b) < 0.5 * pw * ph:
                continue  # not a source page
            area = {"left": round(mm(l), 1), "right": round(mm(pw - r), 1), "top": round(mm(ph - t), 1),
                    "bottom": round(mm(b), 1)}
            seal = {}
            for o in objs:
                if o is big:
                    continue
                im = o.get_bitmap(render=False).to_pil()
                s_sig, s_st = similarity(im, sig_ref), max(similarity(im, x) for x in st_refs)
                key = "signature" if s_sig > s_st else "stamp"
                if max(s_sig, s_st) < 0.25:
                    continue
                ol, ob, or_, ot = o.get_bounds()
                with _tf.TemporaryDirectory() as td:
                    src = Path(td) / "i.png"
                    im.convert("RGB").save(src)
                    rr = remove_background(src, Path(td) / "o.png")
                (x0, y0, x1, y1), (W_, H_) = rr["crop"], rr["source_size"]
                sx, sy = mm(or_ - ol) / W_, mm(ot - ob) / H_
                seal[key] = {"cx_mm": round(mm(ol) + (x0 + x1) / 2 * sx, 2),
                             "cy_mm": round(mm(ph - ot) + (y0 + y1) / 2 * sy, 2)}
            return {"mode": "band", "area_mm": area, "seal": seal}
    finally:
        doc.close()
    return None
