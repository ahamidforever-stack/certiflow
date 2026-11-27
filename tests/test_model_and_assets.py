import json

import pytest
from pydantic import ValidationError

from certiflow.assets import AssetError, AssetLibrary
from certiflow.cli import main as cli
from certiflow.model import Block, Document, JobSpec, StampChoice
from certiflow.profiles import all_profiles, get_profile, resolve_pair

REQUIRED_LANGS = {"ar", "en", "fr", "de", "es", "it", "pt", "tr", "ru", "fa", "ur", "he", "zh", "ja", "ko", "hi", "nl"}


def test_jobspec_requires_stamp():
    with pytest.raises(ValidationError):
        JobSpec(user_id="translator1")
    assert JobSpec(stamp="office", user_id="u").stamp == StampChoice.office


def test_cli_refuses_job_without_stamp(lib_dir, source_pdf, tmp_path):
    with pytest.raises(SystemExit) as e:
        cli(["build", "samples/models/en_ar_good_standing.json", "--source", str(source_pdf), "--user", "translator1",
             "--library", str(lib_dir / "library.json"), "--out", str(tmp_path)])
    assert "stamp must be chosen" in str(e.value)


def test_block_validation():
    with pytest.raises(ValidationError):
        Block(id="x", type="kv_table", rows=[{"cells": [{"translated_text": "a"}]}])
    with pytest.raises(ValidationError):
        Block(id="x", type="unreadable")
    with pytest.raises(ValidationError):
        Document(id="d", title="t", source_language="en", target_language="en", blocks=[])
    with pytest.raises(ValidationError):
        Document(id="d", title="t", source_language="en", target_language="ar",
                 blocks=[Block(id="a", type="paragraph"), Block(id="a", type="paragraph")])


def test_schema_exports():
    s = Document.model_json_schema()
    assert "Block" in json.dumps(s)


def test_profiles_cover_required_languages():
    codes = {p.code for p in all_profiles()}
    assert REQUIRED_LANGS <= codes
    for p in all_profiles():
        assert p.labels.unreadable_illegible and p.style_guide and p.ocr_pack
    assert get_profile("ar").direction.value == "rtl" and get_profile("ar").word_font == "Sakkal Majalla"
    assert get_profile("ar").body_size_pt == 13 and get_profile("ar").pdf_font == "Amiri"
    assert get_profile("en").word_font == "Times New Roman"


def test_pair_resolution():
    p = resolve_pair("en", "ar")
    assert not p.same_script and p.no_foreign_script and p.transliteration_standard
    p = resolve_pair("fr", "en")
    assert p.same_script and p.transliteration_standard is None


def test_stamp_authorisation(library: AssetLibrary):
    st, sig = library.stamp_for(StampChoice.certified, "translator1")
    assert st.type == "stamp_certified" and sig.owner_user == "translator1"
    st, _ = library.stamp_for(StampChoice.office, "translator1")
    assert st.type == "stamp_office"
    with pytest.raises(AssetError):          # reviewer owns no certified stamp and no signature
        library.stamp_for(StampChoice.certified, "reviewer1")
    with pytest.raises(AssetError):
        library.stamp_for(StampChoice.office, "reviewer1")


def test_stamp_png_must_be_transparent(lib_dir, tmp_path):
    from PIL import Image
    from certiflow.assets import Asset
    lib = AssetLibrary(lib_dir / "library.json")
    Image.new("RGB", (10, 10), "white").save(lib_dir / "opaque.png")
    with pytest.raises(ValueError):
        lib.add(Asset(id="bad", name="bad", type="stamp_office", path="opaque.png"))
