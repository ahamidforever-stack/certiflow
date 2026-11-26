"""Placeholder assets for development and tests.

Everything generated here is clearly marked SAMPLE. Real templates, stamps and
signatures are uploaded into the Asset Library by an admin.
"""
from __future__ import annotations

import json
import math
import random
import subprocess
import tempfile
from pathlib import Path

from docx import Document as new_docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIRS = ["/usr/share/fonts"]


def _font(name_part: str, size: int) -> ImageFont.FreeTypeFont:
    for d in FONT_DIRS:
        for p in Path(d).rglob("*.tt[fc]"):
            if name_part.lower() in p.name.lower():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def make_template(out: Path, paper: str = "A4") -> Path:
    d = new_docx()
    s = d.sections[0]
    if paper == "A4":
        s.page_width, s.page_height = Mm(210), Mm(297)
    else:
        s.page_width, s.page_height = Mm(215.9), Mm(279.4)
    s.left_margin = s.right_margin = Mm(20)
    s.top_margin, s.bottom_margin = Mm(18), Mm(15)
    s.header_distance, s.footer_distance = Mm(8), Mm(8)
    h = s.header.paragraphs[0]
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = h.add_run("SAMPLE TRANSLATION OFFICE  (placeholder template)")
    r.bold, r.font.size, r.font.name = True, Pt(13), "Liberation Serif"
    r.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    f = s.footer.paragraphs[0]
    f.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = f.add_run("Sample contact block  |  Tel +000 0 000 0000  |  info@example.invalid  |  Dubai, U.A.E.")
    r.font.size, r.font.name = Pt(8), "Liberation Serif"
    d.add_paragraph("Template body is replaced by the builder.")
    out.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(out))
    return out


def make_oval_stamp(out: Path, top: str, bottom: str, middle: str, color=(30, 60, 170)) -> Path:
    W, H = 900, 600
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    c = color + (235,)
    dr.ellipse([10, 10, W - 10, H - 10], outline=c, width=14)
    dr.ellipse([70, 70, W - 70, H - 70], outline=c, width=6)
    f = _font("LiberationSans-Bold", 46)
    for text, sign in ((top, -1), (bottom, 1)):
        n = len(text)
        span = math.radians(150)
        for i, ch in enumerate(text):
            a = -math.pi / 2 * -sign + (i - (n - 1) / 2) * span / max(n, 1) * sign * -1
            ang = (math.pi / 2 if sign > 0 else -math.pi / 2) + (i - (n - 1) / 2) * (span / max(n, 1)) * (-1 if sign > 0 else 1)
            x = W / 2 + (W / 2 - 40) * math.cos(ang)
            y = H / 2 + (H / 2 - 40) * math.sin(ang)
            g = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
            ImageDraw.Draw(g).text((30, 30), ch, font=f, fill=c, anchor="mm")
            rot = -math.degrees(ang) - 90 if sign < 0 else -math.degrees(ang) + 90
            g = g.rotate(rot, resample=Image.BICUBIC)
            im.alpha_composite(g, (int(x - 30), int(y - 30)))
    fm = _font("LiberationSans-Bold", 58)
    for k, line in enumerate(middle.split("\n")):
        dr.text((W / 2, H / 2 - 35 + 70 * k), line, font=fm, fill=c, anchor="mm")
    im = im.filter(ImageFilter.SMOOTH)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def make_signature(out: Path) -> Path:
    W, H = 800, 300
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    rnd = random.Random(7)
    pts = []
    for i in range(160):
        t = i / 159
        x = 40 + t * (W - 80)
        y = H / 2 + 70 * math.sin(t * 13) * (1 - t * 0.6) + rnd.uniform(-4, 4)
        pts.append((x, y))
    dr.line(pts, fill=(15, 25, 90, 255), width=7, joint="curve")
    dr.line([(120, H - 60), (W - 150, H - 80)], fill=(15, 25, 90, 255), width=5)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def _scan_page(lines: list[str], size=(1240, 1754), landscape=False, seed=0, with_stamp=True,
               font_part="LiberationSerif-Regular") -> Image.Image:
    W, H = (size[1], size[0]) if landscape else size
    im = Image.new("RGB", (W, H), (250, 249, 244))
    dr = ImageDraw.Draw(im)
    f = _font(font_part, 30)
    fb = _font("LiberationSerif-Bold", 40)
    y = 120
    for i, line in enumerate(lines):
        dr.text((110, y), line, font=fb if i == 0 else f, fill=(20, 20, 20))
        y += 70 if i == 0 else 48
    if with_stamp:
        dr.ellipse([W - 420, y + 20, W - 140, y + 210], outline=(160, 40, 60), width=8)
        dr.text((W - 280, y + 115), "REGISTRY", font=fb, fill=(160, 40, 60), anchor="mm")
    rnd = random.Random(seed)
    px = im.load()
    for _ in range(W * H // 400):
        x, yy = rnd.randrange(W), rnd.randrange(H)
        v = rnd.randint(170, 235)
        px[x, yy] = (v, v, v)
    return im.rotate(0.4, fillcolor=(250, 249, 244)).filter(ImageFilter.GaussianBlur(0.6))


SAMPLE_SOURCE_EN = [
    ["CERTIFICATE OF GOOD STANDING (SAMPLE)",
     "Company name: Blue Harbour Trading LLC",
     "Registration No.: CN-1234567",
     "Date of incorporation: 14/03/2019",
     "Registered address: Office 1204, Marina Plaza, Dubai",
     "",
     "This is to certify that the above company is duly registered",
     "and is in good standing as of 02/11/2026.",
     "Verification code: 7F3A-91BC-22D0",
     "Contact: registry@example.invalid",
     "",
     "Registrar: John A. Smith"],
    ["SCHEDULE OF SHAREHOLDERS (SAMPLE)",
     "1. Ahmed Hassan Ali         Passport P1234567     60%",
     "2. Maria Lopez Garcia       Passport X7654321     40%",
     "",
     "Issued at Dubai on 02/11/2026. Ref: REG/2026/00451"],
]


def make_source_pdf(out: Path, pages: list[list[str]] = None, landscape_pages=(2,), n_pages: int | None = None,
                    seed: int = 1) -> Path:
    pages = pages or SAMPLE_SOURCE_EN
    if n_pages:
        pages = [pages[i % len(pages)] for i in range(n_pages)]
    ims = [_scan_page(p, landscape=(i + 1) in landscape_pages, seed=seed + i) for i, p in enumerate(pages)]
    out.parent.mkdir(parents=True, exist_ok=True)
    ims[0].save(out, "PDF", resolution=150, save_all=True, append_images=ims[1:])
    return out


def make_rtl_source_pdf(out: Path) -> Path:
    """An Arabic-script source, produced through LibreOffice for correct shaping."""
    d = new_docx()
    for i, line in enumerate(["شهادة حسن سيرة وسلوك (نموذج)", "الاسم: خالد محمد العلي",
                              "رقم الهوية: \u200e784-1990-1234567-1\u200e", "تاريخ الإصدار: \u200e05/10/2026\u200e",
                              "تشهد الإدارة بأن المذكور أعلاه لا توجد عليه أية سوابق.", "المدير العام"]):
        p = d.add_paragraph()
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT  # in a bidi paragraph "left" = start (right edge)
        pPr = p._p.get_or_add_pPr()
        from docx.oxml import OxmlElement
        pPr.insert(0, OxmlElement("w:bidi"))
        r = p.add_run(line)
        r.font.size = Pt(20 if i == 0 else 16)
        r.font.rtl = True
        r._r.get_or_add_rPr().get_or_add_rFonts().set(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}cs", "Amiri")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "ar_source.docx"
        d.save(str(src))
        from .builder.pdf_builder import docx_to_pdf
        pdf = docx_to_pdf(src, Path(td))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(pdf.read_bytes())
    return out


def make_library(root: Path) -> Path:
    """Template + stamps + signature + manifest in ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    make_template(root / "templates" / "sample_template_a4.docx")
    make_oval_stamp(root / "stamps" / "certified_sample.png", "SAMPLE CERTIFIED TRANSLATOR", "LICENCE No. 0000",
                    "J. DOE\nSAMPLE")
    make_oval_stamp(root / "stamps" / "office_sample.png", "SAMPLE TRANSLATION OFFICE", "DUBAI - U.A.E.",
                    "OFFICE\nSAMPLE", color=(20, 90, 60))
    make_signature(root / "signatures" / "translator_sample.png")
    manifest = {
        "company": "sample-office",
        "users": [
            {"id": "translator1", "name": "J. Doe (sample)", "role": "certified_translator", "company": "sample-office"},
            {"id": "reviewer1", "name": "Reviewer (sample)", "role": "reviewer", "company": "sample-office"},
            {"id": "admin", "name": "Admin", "role": "admin", "company": "sample-office"},
        ],
        "assets": [
            {"id": "tpl-default", "name": "Sample A4 template", "type": "template",
             "path": "templates/sample_template_a4.docx"},
            {"id": "stamp-cert-translator1", "name": "Certified stamp (sample)", "type": "stamp_certified",
             "path": "stamps/certified_sample.png", "owner_user": "translator1", "width_mm": 38},
            {"id": "stamp-office", "name": "Office stamp (sample)", "type": "stamp_office",
             "path": "stamps/office_sample.png", "owner_company": "sample-office", "width_mm": 38},
            {"id": "sig-translator1", "name": "Signature (sample)", "type": "signature",
             "path": "signatures/translator_sample.png", "owner_user": "translator1", "width_mm": 32},
        ],
    }
    m = root / "library.json"
    m.write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    return m


if __name__ == "__main__":  # pragma: no cover
    import sys
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
    make_library(base / "assets")
    make_source_pdf(base / "sources" / "en_good_standing.pdf")
    make_rtl_source_pdf(base / "sources" / "ar_good_conduct.pdf")
    print("samples written to", base)
