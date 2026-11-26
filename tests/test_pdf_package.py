"""End-to-end Phase 1: model -> Word + integrated certified PDF (needs LibreOffice + poppler)."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter

from certiflow import samples
from certiflow.builder.docx_builder import SealSpec
from certiflow.builder.package import build_package, zip_batch
from certiflow.builder.pdf_builder import (PT_PER_MM, Rect, _ink_integral, _seal_images, choose_position,
                                           text_seal_overlaps, verify_certified_pdf)
from certiflow.model import JobSpec
from certiflow.qa.scan import scan

from .conftest import PAIRS, pair_model, requires_soffice


def _seal(library, stamp="stamp-cert-translator1"):
    a = {x.id: x for x in library.lib.assets}
    return SealSpec(library.path(a[stamp]), library.path(a["sig-translator1"]), 38, 32)


# ------------------------------------------------------------- placement

def test_least_ink_keeps_footer_on_blank_page():
    pw, ph = 595.0, 842.0
    im = Image.new("RGB", (1000, 1414), "white")
    ii = _ink_integral(im, pw, ph, Rect(0, 0, pw, ph))
    default = Rect(400, 30, 108, 72)
    r, ink = choose_position(ii, pw, ph, default, None)
    assert (r.x, r.y) == (default.x, default.y) and ink == 0


def test_least_ink_moves_off_text():
    pw, ph = 595.0, 842.0
    im = Image.new("RGB", (595, 842), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 600, 595, 842], fill="black")       # dense text band at the bottom (image y down)
    ii = _ink_integral(im, pw, ph, Rect(0, 0, pw, ph))
    default = Rect(400, 30, 108, 72)                      # sits in the black band
    r, ink = choose_position(ii, pw, ph, default, None)
    assert ink == 0 and r.y > 242                         # moved above the band


# ------------------------------------------------------------- packages

@requires_soffice
def test_en_ar_package(en_ar_model, source_pdf, library, tmp_path):
    job = JobSpec(stamp="certified", user_id="translator1")
    res = build_package(en_ar_model, source_pdf, job, library, tmp_path)
    assert res.docx.name == "01_Certificate_of_Good_Standing_AR.docx"
    assert res.pdf.name == "01_Certificate_of_Good_Standing_AR.pdf"
    n = len(PdfReader(str(res.pdf)).pages)
    assert n == res.translation_pages + res.source_pages == res.translation_pages + 2
    seal = _seal(library)
    assert verify_certified_pdf(res.pdf, seal, n).ok
    # same physical size of the seal on every page
    sizes = set()
    for i in range(n):
        f = _seal_images(res.pdf, i, seal)
        sizes.add((round(f["stamp"][0].w), round(f["stamp"][0].h), round(f["signature"][0].w)))
    assert len(sizes) == 1
    # no translated text runs under the seal
    assert text_seal_overlaps(res.pdf, seal, range(res.translation_pages)) == []
    assert scan(en_ar_model) == []
    assert res.audit["stamp_choice"] == "certified"


@requires_soffice
def test_office_stamp_is_applied(en_ar_model, source_pdf, library, tmp_path):
    res = build_package(en_ar_model, source_pdf, JobSpec(stamp="office", user_id="translator1"), library, tmp_path)
    assert res.stamp_asset == "stamp-office"
    n = len(PdfReader(str(res.pdf)).pages)
    assert verify_certified_pdf(res.pdf, _seal(library, "stamp-office"), n).ok


@requires_soffice
def test_verification_blocks_unstamped_page(en_ar_model, source_pdf, library, tmp_path):
    res = build_package(en_ar_model, source_pdf, JobSpec(stamp="certified", user_id="translator1"), library, tmp_path)
    r = PdfReader(str(res.pdf))
    w = PdfWriter()
    for p in r.pages:
        w.add_page(p)
    w.add_blank_page(595, 842)  # an unstamped page sneaks in
    bad = tmp_path / "bad.pdf"
    w.write(str(bad))
    v = verify_certified_pdf(bad, _seal(library), len(r.pages) + 1)
    assert not v.ok and any("stamp image missing" in f for f in v.failures)


@requires_soffice
@pytest.mark.parametrize("src,tgt", PAIRS, ids=[f"{s}-{t}" for s, t in PAIRS])
def test_pair_matrix_end_to_end(src, tgt, source_pdf, library, tmp_path):
    model = pair_model(src, tgt)
    res = build_package(model, source_pdf, JobSpec(stamp="certified", user_id="translator1"), library, tmp_path)
    n = len(PdfReader(str(res.pdf)).pages)
    seal = _seal(library)
    v = verify_certified_pdf(res.pdf, seal, res.translation_pages + res.source_pages)
    assert v.ok, v.failures
    assert text_seal_overlaps(res.pdf, seal, range(res.translation_pages)) == []
    assert res.pdf.name.endswith(f"_{tgt.upper()}.pdf")


@requires_soffice
def test_interleaved_order(source_pdf, library, tmp_path):
    model = pair_model("en", "ar", pages=2)
    res = build_package(model, source_pdf, JobSpec(stamp="certified", user_id="translator1",
                                                   pdf_page_order="interleaved"), library, tmp_path)
    assert res.page_order == "interleaved"
    r = PdfReader(str(res.pdf))
    kinds = ["src" if not any(c in (p.extract_text() or "") for c in "شهادة") else "tr" for p in r.pages]
    assert kinds[0] == "tr" and kinds[-1] == "src"
    assert kinds.count("src") == 2 and kinds.index("src") < len(kinds) - 1  # a source page sits between translations


@requires_soffice
def test_24_page_scan_size_budget(library, tmp_path):
    src = samples.make_source_pdf(tmp_path / "big.pdf", n_pages=24, landscape_pages=(3, 9))
    model = pair_model("en", "ar")
    res = build_package(model, src, JobSpec(stamp="certified", user_id="translator1"), library, tmp_path / "o")
    assert res.source_pages == 24
    size_mb = res.pdf.stat().st_size / 1e6
    assert size_mb <= 12, f"{size_mb:.1f} MB"


@requires_soffice
def test_rtl_source_to_ltr_target(library, tmp_path):
    from certiflow.model import Document
    root = Path(__file__).resolve().parents[1]
    model = Document.model_validate_json((root / "samples/models/ar_en_good_conduct.json").read_text("utf-8"))
    src = samples.make_rtl_source_pdf(tmp_path / "ar.pdf")
    res = build_package(model, src, JobSpec(stamp="office", user_id="translator1"), library, tmp_path / "o")
    assert res.pdf.name.endswith("_EN.pdf")
    assert any("covered by stamp" in d for d in res.disclosures)
    z = zip_batch([(model.title, res)], tmp_path / "o", "Batch 1")
    import zipfile
    names = zipfile.ZipFile(z).namelist()
    assert "Batch_1/disclosures.txt" in names and any(n.endswith("_EN.docx") for n in names)
