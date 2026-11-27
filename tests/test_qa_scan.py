"""Deterministic QA checks: measurements, clock times and chemical symbols are not identifier/figure errors."""
from certiflow.model import Block, BlockType, Document
from certiflow.qa.scan import figures_added, figures_match, identifiers_match


def _doc(src: str, tgt: str) -> Document:
    return Document(id="t", title="t", source_language="en", target_language="ar",
                    blocks=[Block(id="b1", type=BlockType.paragraph, source_text=src, translated_text=tgt)])


def test_dose_with_arabic_unit_is_not_an_identifier_change():
    d = _doc("Mounjaro 7.5MG weekly, Ceftriaxone 1000mg in 100ML", "مونجارو ‎7.5‎ ملغ أسبوعياً، سيفترياكسون 1000 ملغ في 100 مل")
    assert identifiers_match(d) == []
    assert figures_match(d) == []


def test_dropped_dose_number_is_still_caught():
    d = _doc("Mounjaro 7.5MG weekly", "مونجارو ملغ أسبوعياً")
    assert [f.detail for f in figures_match(d)] == ["7.5"]


def test_clock_time_joined_to_text_accepts_hh_mm_form():
    d = _doc("1909H-Patient still gasping", "19:09 ساعة – لا يزال المريض يلهث")
    assert identifiers_match(d) == []
    assert figures_match(d) == []
    assert figures_added(d) == []


def test_chemical_symbol_digits_are_not_figures():
    d = _doc("SpO2-65% with bag mask. High flow O2", "تشبع الأكسجين 65% مع قناع الكيس. تدفق عالٍ من الأكسجين")
    assert figures_match(d) == []


def test_one_hour_and_first_written_as_words():
    assert figures_match(_doc("INFUSION UP TO 1 HOUR", "تسريب حتى ساعة واحدة")) == []
    assert figures_match(_doc("PUSH SINGLE/1ST DRUG", "دواء مفرد/الأول")) == []
    # a separate bare 1 in the same cell is still a figure
    assert figures_match(_doc("1 vial, UP TO 1 HOUR", "قارورة، حتى ساعة واحدة")) != []


def test_vitals_and_clinical_symbols_are_not_identifiers():
    d = _doc("BP-117/80mmHg, HR-68bpm, SP02:69%, BMI 31 kg/m2, at 7.35PM, SINGLE/1ST dose 2gm",
             "ضغط الدم 117/80 ملم زئبق، النبض 68 نبضة/دقيقة، تشبع الأكسجين: 69%، مؤشر كتلة الجسم 31 كغ/م²، "
             "الساعة 7.35 مساءً، جرعة واحدة/أولى 2 غرام")
    assert identifiers_match(d) == []


def test_reference_number_with_translated_prefix():
    assert identifiers_match(_doc("stamp 'No.00250490-001'", "ختم «رقم 00250490-001»")) == []
    assert identifiers_match(_doc("stamp 'No.00250490-001'", "ختم «رقم 00250490»")) != []


def test_url_does_not_swallow_arabic_punctuation():
    from certiflow.qa.scan import _IDENT
    text = "info@haniit.com | www.haniit.com؛ دعم تسجيل الدخول: https://haniitsupport.com/»."
    assert set(_IDENT.findall(text)) == {"info@haniit.com", "www.haniit.com", "https://haniitsupport.com/"}


def test_real_codes_are_still_protected():
    d = _doc("Flat 12C, ref DLJ0240732, file AB-12-CD", "شقة 12، المرجع DLJ0240732، الملف AB-12")
    missing = identifiers_match(d)[0].detail
    assert "12C" in missing and "AB-12-CD" in missing and "DLJ0240732" not in missing


def test_long_text_column_gets_the_width():
    from certiflow.builder.docx_builder import _balanced_widths
    from certiflow.model import TableCell, TableRow
    b = Block(id="t", type=BlockType.table, column_widths=[1.0, 3.0],
              rows=[TableRow(cells=[TableCell(source_text="x" * 1800, translated_text="x" * 1800),
                                    TableCell(source_text="Shanty Jojo", translated_text="شانتي جوجو")])])
    w = _balanced_widths(b, b.column_widths, 2)
    assert w[0] / sum(w) == 0.7
    # an ordinary table keeps its widths
    b2 = b.model_copy(update={"column_widths": [3.0, 1.0]})
    assert _balanced_widths(b2, b2.column_widths, 2) == [3.0, 1.0]
