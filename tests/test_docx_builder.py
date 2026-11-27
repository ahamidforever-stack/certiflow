"""Builder unit tests across the pair matrix (no LibreOffice needed)."""
import zipfile

import pytest
from lxml import etree

from certiflow.builder.docx_builder import SEAL_MARKER, BuildOptions, SealSpec, render
from certiflow.model import PageOrder
from certiflow.profiles import get_profile
from certiflow.textdir import LRM, RLM, segment
from certiflow.model import Direction, RunKind

from .conftest import PAIRS, pair_model

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _xml(docx, part="word/document.xml"):
    with zipfile.ZipFile(docx) as z:
        return etree.fromstring(z.read(part))


def _seal(library):
    a = {x.id: x for x in library.lib.assets}
    return SealSpec(library.path(a["stamp-cert-translator1"]), library.path(a["sig-translator1"]), 38, 32)


@pytest.mark.parametrize("src,tgt", PAIRS, ids=[f"{s}-{t}" for s, t in PAIRS])
@pytest.mark.parametrize("mode", ["word", "pdf"])
def test_direction_and_fonts(src, tgt, mode, library, tmp_path):
    model = pair_model(src, tgt)
    tpl = library.path(library.template_for(tgt))
    out = render(model, tpl, tmp_path / "o.docx", BuildOptions(font_mode=mode, seal=_seal(library)))
    root = _xml(out)
    body = root.find(f"{W}body")
    prof = get_profile(tgt)
    rtl = prof.direction == Direction.rtl
    paras = [p for p in body.iter(f"{W}p") if "".join(p.itertext()).strip()]
    assert paras
    for p in paras:
        assert (p.find(f"{W}pPr/{W}bidi") is not None) == rtl, "paragraph direction must follow target profile"
    for t in body.iter(f"{W}tbl"):
        assert (t.find(f"{W}tblPr/{W}bidiVisual") is not None) == rtl

    from certiflow.builder.docx_builder import pdf_font_for
    want_font = prof.word_font if mode == "word" else pdf_font_for(prof)   # fallback when the licensed font is absent
    slot = {"ascii": "ascii", "cs": "cs", "eastAsia": "eastAsia"}[prof.font_slot]
    fonts = {r.find(f"{W}rPr/{W}rFonts").get(f"{W}{slot}") for r in body.iter(f"{W}r") if r.find(f"{W}rPr/{W}rFonts") is not None}
    assert fonts == {want_font}
    langs = [r.find(f"{W}rPr/{W}lang") for r in body.iter(f"{W}r")]
    assert all(l is not None for l in langs), "every run carries a proofing language"
    key = f"{W}bidi" if prof.font_slot == "cs" else f"{W}val"
    assert {l.get(key) for l in langs} == {prof.word_tag}

    text = "".join(body.itertext())
    if rtl:
        # identifiers, dates and numbers are isolated and not marked rtl
        assert f"{LRM}784-1990-1234567-1{LRM}" in text
        assert f"{LRM}14/03/2019{LRM}" in text
        assert f"{LRM}1{LRM}.{RLM}" in text  # numbering label survives RTL (house style)
        for r in body.iter(f"{W}r"):
            t = "".join(r.itertext())
            if t.startswith(LRM):
                assert r.find(f"{W}rPr/{W}rtl") is None
    else:
        assert RLM not in text and f"{LRM}784" not in text

    # repeated stamps described once at the end under the profile heading
    assert text.count(prof.labels.repeated_notes_heading) == 1


def test_seal_in_every_footer(library, tmp_path):
    out = render(pair_model("en", "ar"), library.path(library.template_for("ar")), tmp_path / "o.docx",
                 BuildOptions(seal=_seal(library)))
    with zipfile.ZipFile(out) as z:
        footers = [n for n in z.namelist() if n.startswith("word/footer")]
        assert footers
        for f in footers:
            root = etree.fromstring(z.read(f))
            assert len(root.findall(f".//{W}drawing")) == 2
            assert SEAL_MARKER not in "".join(root.itertext())   # marker lives in the PDF only
            # inline (not floating) so the footer grows and body text cannot overlap
            assert not root.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}anchor")


def test_template_header_footer_preserved(library, tmp_path):
    out = render(pair_model("fr", "en"), library.path(library.template_for("en")), tmp_path / "o.docx",
                 BuildOptions(seal=_seal(library)))
    with zipfile.ZipFile(out) as z:
        hdr = "".join(etree.fromstring(z.read("word/header1.xml")).itertext())
        ftr = "".join(etree.fromstring(z.read("word/footer1.xml")).itertext())
    assert "SAMPLE TRANSLATION OFFICE" in hdr and "Sample contact block" in ftr
    body = "".join(_xml(out).itertext())
    assert "Template body is replaced" not in body


def test_interleave_markers(library, tmp_path):
    out = render(pair_model("en", "ar", pages=2), library.path(library.template_for("ar")), tmp_path / "o.docx",
                 BuildOptions(page_order=PageOrder.interleaved))
    text = "".join(_xml(out).itertext())
    assert "CFSP001" in text and "CFSP002" in text


def test_segment_rtl_target():
    runs = segment("رمز التحقق 7F3A-91BC-22D0 والبريد a@b.com بتاريخ 02/11/2026 لشركة ABC", Direction.rtl)
    iso = [(r.text, r.kind) for r in runs if r.direction == Direction.ltr]
    assert ("7F3A-91BC-22D0", RunKind.identifier) in iso
    assert ("a@b.com", RunKind.email) in iso
    assert ("02/11/2026", RunKind.date) in iso
    assert ("ABC", RunKind.identifier) in iso
    src = "رمز التحقق 7F3A-91BC-22D0 والبريد a@b.com بتاريخ 02/11/2026 لشركة ABC"
    assert "".join(r.text for r in runs) == src  # segmentation is lossless


def test_segment_ltr_target_isolates_rtl_names():
    runs = segment("Issued to خالد العلي on 05/10/2026", Direction.ltr)
    assert [r.text for r in runs if r.direction == Direction.rtl] == ["خالد العلي"]
