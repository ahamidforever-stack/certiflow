"""Office setup: background removal, template seal import, anchored seal on every page,
and visual (rendered) order of identifiers in RTL output."""
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader

from certiflow.assets import AssetLibrary
from certiflow.builder.docx_builder import SealSpec
from certiflow.builder.package import build_package
from certiflow.builder.pdf_builder import text_seal_overlaps, verify_certified_pdf
from certiflow.imageprep import remove_background
from certiflow.model import JobSpec

from .conftest import pair_model, requires_soffice

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "inputs"
have_office_inputs = pytest.mark.skipif(not (INPUTS / "shoreline_template.docx").exists(),
                                        reason="office template/stamps not present (kept out of git)")


def test_remove_background(tmp_path):
    im = Image.new("RGB", (400, 260), (252, 251, 246))
    d = ImageDraw.Draw(im)
    d.ellipse([20, 20, 380, 240], outline=(40, 90, 200), width=10)
    d.line([(396, 0), (396, 259)], fill=(150, 150, 150), width=2)    # scanner edge line
    for x in range(5, 395, 37):
        im.putpixel((x, 250), (200, 200, 200))                         # dust
    src = tmp_path / "s.jpg"
    im.save(src, quality=90)
    info = remove_background(src, tmp_path / "o.png")
    out = Image.open(tmp_path / "o.png")
    a = np.asarray(out)
    assert out.mode == "RGBA"
    assert a[a.shape[0] // 2, a.shape[1] // 2, 3] == 0                # paper is transparent
    assert (a[..., 3] > 200).sum() > 1000                              # ink kept
    assert info["size"][0] < 380                                       # edge line cropped away
    ink = a[a[..., 3] > 200][:, :3].mean(axis=0)
    assert ink[2] > ink[0] + 60                                        # still blue


def _visual_lines(pdf: Path, page: int = 0) -> list[str]:
    doc = pdfium.PdfDocument(str(pdf))
    tp = doc[page].get_textpage()
    chars = []
    for i in range(tp.count_chars()):
        ch = tp.get_text_range(i, 1)
        if ch in "0123456789-/":
            l, b, r, t = tp.get_charbox(i)
            chars.append(((b + t) / 2, l, ch))
    chars.sort(key=lambda c: -c[0])
    lines: list[list] = []
    for c in chars:
        if lines and abs(lines[-1][0][0] - c[0]) < 6:
            lines[-1].append(c)
        else:
            lines.append([c])
    doc.close()
    return ["".join(ch for _, _, ch in sorted(L, key=lambda c: c[1])) for L in lines]


@requires_soffice
def test_rtl_identifiers_render_left_to_right(source_pdf, library, tmp_path):
    """Rendered PDF, not XML: in Arabic output the ID and date must read left to right."""
    res = build_package(pair_model("en", "ar"), source_pdf, JobSpec(stamp="certified", user_id="translator1"),
                        library, tmp_path)
    text = " ".join(_visual_lines(res.pdf))
    assert "784-1990-1234567-1" in text and "14/03/2019" in text
    assert "1-1234567-1990-784" not in text


@pytest.fixture(scope="module")
def office_lib(tmp_path_factory):
    from certiflow.office_setup import setup_office
    out = tmp_path_factory.mktemp("office")
    m = setup_office(INPUTS / "shoreline_template.docx", INPUTS / "raw/signature.jpg",
                     INPUTS / "raw/stamp_certified.jpg", INPUTS / "raw/stamp_office.jpg", out,
                     company="shoreline", translator_id="amir.gomaa", translator_name="Amir Gomaa")
    return AssetLibrary(m)


@have_office_inputs
@requires_soffice
def test_template_import_finds_baked_seal(office_lib):
    tpl = office_lib.template_for("ar")
    assert set(tpl.seal_layout) == {"stamp", "signature"}
    assert len(tpl.strip_footer_images) == 2
    assert tpl.seal_layout["stamp"]["cx_mm"] > tpl.seal_layout["signature"]["cx_mm"]   # stamp right of signature


@have_office_inputs
@requires_soffice
@pytest.mark.parametrize("stamp", ["certified", "office"])
@pytest.mark.parametrize("pair", [("en", "ar"), ("ar", "en")])
def test_office_template_every_page_sealed(office_lib, source_pdf, tmp_path, stamp, pair):
    model = pair_model(*pair, pages=8)          # several translation pages: odd and even footers
    res = build_package(model, source_pdf, JobSpec(stamp=stamp, user_id="amir.gomaa"), office_lib, tmp_path)
    assert res.translation_pages >= 3
    st, sig = office_lib.stamp_for(JobSpec(stamp=stamp, user_id="amir.gomaa").stamp, "amir.gomaa")
    seal = SealSpec(office_lib.path(st), office_lib.path(sig), st.width_mm, sig.width_mm)
    n = len(PdfReader(str(res.pdf)).pages)
    v = verify_certified_pdf(res.pdf, seal, n)
    assert v.ok, v.failures
    assert text_seal_overlaps(res.pdf, seal, range(res.translation_pages)) == []
    # the template's own baked-in seal is gone: exactly one stamp + one signature per page
    from certiflow.builder.pdf_builder import _seal_images
    for i in range(n):
        f = _seal_images(res.pdf, i, seal)
        assert len(f["stamp"]) == 1 and len(f["signature"]) == 1
