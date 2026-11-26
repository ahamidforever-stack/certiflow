from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from certiflow import samples
from certiflow.assets import AssetLibrary
from certiflow.model import Document

ROOT = Path(__file__).resolve().parents[1]

# Pair matrix required by the brief. Text per language is synthetic but real script.
PAIRS = [("en", "ar"), ("ar", "en"), ("fr", "en"), ("en", "de"), ("es", "ar"), ("ru", "en")]

SAMPLE_TEXT = {
    "ar": ("شهادة", "نشهد بأن السيد {name} حامل الهوية رقم 784-1990-1234567-1 مسجل بتاريخ 14/03/2019.", "أحمد علي"),
    "en": ("Certificate", "We certify that Mr {name}, holder of ID No. 784-1990-1234567-1, was registered on 14/03/2019.", "Ahmed Ali"),
    "fr": ("Certificat", "Nous certifions que M. {name}, titulaire de la pièce n° 784-1990-1234567-1, est inscrit le 14/03/2019.", "Ahmed Ali"),
    "de": ("Bescheinigung", "Wir bescheinigen, dass Herr {name}, Inhaber des Ausweises Nr. 784-1990-1234567-1, am 14/03/2019 eingetragen wurde.", "Ahmed Ali"),
    "es": ("Certificado", "Certificamos que el Sr. {name}, titular del documento n.º 784-1990-1234567-1, fue inscrito el 14/03/2019.", "Ahmed Ali"),
    "ru": ("Свидетельство", "Настоящим удостоверяется, что г-н {name}, паспорт № 784-1990-1234567-1, зарегистрирован 14/03/2019.", "Ахмед Али"),
}


def pair_model(src: str, tgt: str, pages: int = 1) -> Document:
    sh, sp, sn = SAMPLE_TEXT[src]
    th, tp, tn = SAMPLE_TEXT[tgt]
    blocks = []
    for p in range(1, pages + 1):
        blocks += [
            {"id": f"h{p}", "type": "heading", "source_page": p, "source_text": sh, "translated_text": th},
            {"id": f"p{p}", "type": "paragraph", "source_page": p, "source_text": sp.format(name=sn),
             "translated_text": tp.format(name=tn)},
            {"id": f"n{p}", "type": "numbered_item", "source_page": p, "label": "1.", "source_text": "x",
             "translated_text": tp.format(name=tn)},
            {"id": f"k{p}", "type": "kv_table", "source_page": p, "rows": [
                {"cells": [{"source_text": "ID", "translated_text": th}, {"source_text": "AB-12345", "translated_text": "AB-12345"}]},
                {"cells": [{"source_text": "Date", "translated_text": th}, {"source_text": "14/03/2019", "translated_text": "14/03/2019"}]},
            ]},
            {"id": f"t{p}", "type": "table", "source_page": p, "rows": [
                {"header": True, "cells": [{"translated_text": "1"}, {"translated_text": th}, {"translated_text": "%"}]},
                {"cells": [{"translated_text": "1"}, {"translated_text": tn}, {"translated_text": "60%"}]},
            ]},
            {"id": f"s{p}", "type": "note", "source_page": p, "note_kind": "stamp", "note_scope": "document_end",
             "translated_text": th},
        ]
    return Document.model_validate({"id": f"t-{src}-{tgt}", "title": f"Test {src} {tgt}", "source_language": src,
                                    "target_language": tgt, "blocks": blocks})


@pytest.fixture(scope="session")
def lib_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("assets")
    samples.make_library(d)
    return d


@pytest.fixture(scope="session")
def library(lib_dir) -> AssetLibrary:
    return AssetLibrary(lib_dir / "library.json")


@pytest.fixture(scope="session")
def source_pdf(tmp_path_factory) -> Path:
    return samples.make_source_pdf(tmp_path_factory.mktemp("src") / "src.pdf")


@pytest.fixture(scope="session")
def en_ar_model() -> Document:
    return Document.model_validate_json((ROOT / "samples/models/en_ar_good_standing.json").read_text("utf-8"))


requires_soffice = pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")
