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
    a = np.asarray(bg.convert("L").resize((64, 40)), dtype=np.float32)
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
