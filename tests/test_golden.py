"""Golden tools: importer/builder symmetry (synthetic) and the office golden set (if present)."""
from pathlib import Path

import pytest

from certiflow.builder.docx_builder import BuildOptions, render
from certiflow.golden import compare, import_docx
from certiflow.house import HouseStyle
from certiflow.model import Document

from .conftest import requires_soffice

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "inputs" / "golden_set"


def _rich_model() -> Document:
    return Document.model_validate({
        "id": "rich", "title": "rich", "source_language": "en", "target_language": "ar",
        "blocks": [
            {"id": "n0", "type": "note", "translated_text": "شعار الشركة؛ الهاتف: ", "runs": [
                {"text": "شعار الشركة؛ الهاتف: "}, {"text": "+971 4 000 0000", "kind": "identifier", "direction": "ltr"}]},
            {"id": "h1", "type": "heading", "level": 1, "translated_text": "تقرير خدمة العملاء"},
            {"id": "k1", "type": "kv_table", "column_widths": [2200, 2786, 2200, 2786], "rows": [
                {"cells": [{"translated_text": "الرقم التسلسلي"}, {"translated_text": "18730"},
                           {"translated_text": "التاريخ"}, {"translated_text": "14 نوفمبر 2026"}]}]},
            {"id": "h2", "type": "heading", "level": 2, "translated_text": "تفاصيل الإجراء"},
            {"id": "h3", "type": "heading", "level": 3, "translated_text": "أعمال أُنجزت", "layout": {"keep_with_next": False}},
            {"id": "i1", "type": "numbered_item", "label": "1.", "translated_text": "جرى حل المشكلة في الكاميرا رقم 19."},
            {"id": "u1", "type": "bullet", "translated_text": "الموقع: عيادة الجهة الخلفية"},
            {"id": "p1", "type": "paragraph", "translated_text": "مع الشكر والتقدير،",
             "layout": {"size_pt": 12, "align": "start", "space_after_pt": 0.5}},
            {"id": "t1", "type": "table", "column_widths": [4986, 4986], "rows": [{"cells": [
                {"blocks": [{"id": "c1", "type": "heading", "level": 3, "translated_text": "توقيع العميل",
                             "layout": {"align": "start", "space_after_pt": 1, "keep_with_next": False}},
                            {"id": "c2", "type": "note", "translated_text": "خانة التوقيع فارغة"}]},
                {"translated_text": "فير بهادور سينغ\nاسم الموظف"}]}]},
        ]})


def test_roundtrip_builder_importer(library, tmp_path):
    """render(model) -> import -> render again must give the same document."""
    tpl = library.path(library.template_for("ar"))
    house = HouseStyle()
    first = render(_rich_model(), tpl, tmp_path / "a.docx", BuildOptions(house=house))
    again = render(import_docx(first, "en", "ar", house), tpl, tmp_path / "b.docx", BuildOptions(house=house))
    r = compare(first, again)
    assert r.exact, "\n".join(r.diffs)


@requires_soffice
@pytest.mark.skipif(not GOLDEN.exists(), reason="office golden set not present (confidential, kept out of git)")
def test_office_golden_set_rebuilds_exactly(tmp_path):
    from certiflow.assets import AssetLibrary
    from certiflow.golden import run_golden_set
    lib_path = ROOT / "assets" / "shoreline" / "library.json"
    if not lib_path.exists():
        pytest.skip("office asset library not set up")
    res = run_golden_set(GOLDEN, AssetLibrary(lib_path), "amir.gomaa", tmp_path)
    assert res
    from certiflow.fonts import available
    exact_font = available("Sakkal Majalla")
    for r in res:
        assert r.body_exact, (r.case, r.diffs[:3])
        if exact_font and r.approved_tr_pages is not None:
            assert r.tr_pages == r.approved_tr_pages, (r.case, r.tr_pages, r.approved_tr_pages)
