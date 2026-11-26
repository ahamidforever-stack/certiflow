"""One-shot office setup: raw scans + template -> Asset Library.

    certiflow setup-office --template T.docx --signature sig.jpg --certified-stamp c.jpg \
        --office-stamp o.jpg --translator-id amir.gomaa --translator-name "Amir Gomaa" --out assets/shoreline
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .imageprep import remove_background
from .templates import import_template


def setup_office(template: Path, signature: Path, certified_stamp: Path, office_stamp: Path, out: Path, *,
                 company: str, translator_id: str, translator_name: str,
                 certified_width_mm: float | None = None, office_width_mm: float | None = None,
                 signature_width_mm: float | None = None) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    for d in ("templates", "stamps", "signatures"):
        (out / d).mkdir(exist_ok=True)
    tpl = out / "templates" / "office_template.docx"
    shutil.copy(template, tpl)
    sig = out / "signatures" / f"{translator_id}.png"
    cst = out / "stamps" / f"certified_{translator_id}.png"
    ost = out / "stamps" / "office.png"
    info = {
        "signature": remove_background(signature, sig),
        "certified": remove_background(certified_stamp, cst),
        "office": remove_background(office_stamp, ost),
    }
    imp = import_template(tpl, sig, [cst, ost])

    # Physical sizes: the ink width the office used in its own template; office stamp defaults to the same.
    from .templates import baked_seal_images, classify
    baked = classify(baked_seal_images(tpl), sig, [cst, ost])
    sig_w = signature_width_mm or _baked_ink_width(baked.get("signature")) or 44.0
    cst_w = certified_width_mm or _baked_ink_width(baked.get("stamp")) or 45.0
    ost_w = office_width_mm or cst_w

    manifest = {
        "company": company,
        "users": [
            {"id": translator_id, "name": translator_name, "role": "certified_translator", "company": company},
            {"id": "admin", "name": "Administrator", "role": "admin", "company": company},
        ],
        "assets": [
            {"id": "tpl-office", "name": "Office template", "type": "template", "path": "templates/office_template.docx",
             "seal_layout": imp["seal_layout"], "strip_footer_images": imp["strip_footer_images"]},
            {"id": f"stamp-certified-{translator_id}", "name": f"Certified stamp - {translator_name}",
             "type": "stamp_certified", "path": f"stamps/certified_{translator_id}.png",
             "owner_user": translator_id, "width_mm": cst_w},
            {"id": "stamp-office", "name": "Office stamp", "type": "stamp_office", "path": "stamps/office.png",
             "owner_company": company, "width_mm": ost_w},
            {"id": f"sig-{translator_id}", "name": f"Signature - {translator_name}", "type": "signature",
             "path": f"signatures/{translator_id}.png", "owner_user": translator_id, "width_mm": sig_w},
        ],
    }
    m = out / "library.json"
    m.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return m


def _baked_ink_width(b: dict | None) -> float | None:
    """Width (mm) of the ink inside a baked template image, i.e. the stamp's real printed width."""
    if not b:
        return None
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "b.png"
        src.write_bytes(b["blob"])
        r = remove_background(src, Path(td) / "o.png")
    return round(b["w_mm"] * r["size"][0] / r["source_size"][0], 1)
