"""Asset Library administration from the web app (Phase 5).

The library stays a JSON manifest next to its files (jobs on any worker read it from the shared volume). Rules:
* files are never overwritten: an upload gets a new file and a new asset id; the asset it replaces is switched off
  but kept, so earlier choices stay traceable and can be switched back on
* stamps and signatures go through the same background removal as ``certiflow setup-office``; templates through the
  same import (baked seal detection, optional approved reference output for seal position and margins)
* the manifest is written atomically under a lock; the bundled sample library is read-only
"""
from __future__ import annotations

import io
import os
import secrets
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PIL import Image

from ..assets import Asset, AssetLibrary
from ..assets import User as LibUser

LOCK = threading.Lock()
IMAGE_TYPES = ("stamp_certified", "stamp_office", "signature")
OWNED = ("stamp_certified", "signature")
MAX_BYTES = 15 * 1024 * 1024
SAMPLES = (Path(__file__).resolve().parents[2] / "samples").resolve()


class AssetAdminError(ValueError):
    pass


def editable(manifest: Path) -> bool:
    m = Path(manifest).resolve()
    return m.exists() and SAMPLES not in m.parents and os.access(m.parent, os.W_OK)


def _save(lib: AssetLibrary) -> None:
    tmp = lib.manifest.with_suffix(".json.tmp")
    tmp.write_text(lib.lib.model_dump_json(indent=2, exclude_none=False) + "\n", "utf-8")
    tmp.replace(lib.manifest)


def _stamp_now() -> str:
    """Unique, sortable suffix for new files and asset ids (two uploads in one second must not collide)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(3)


def _check_writable(manifest: Path) -> AssetLibrary:
    if not editable(manifest):
        raise AssetAdminError("this asset library is read-only (sample library or no write access)")
    return AssetLibrary(manifest)


def asset_out(lib: AssetLibrary, a: Asset) -> dict:
    p = lib.path(a)
    d = a.model_dump(include={"id", "name", "type", "active", "owner_user", "owner_company", "width_mm",
                              "language", "pair", "margins_mm"})
    d["file"] = p.name
    d["size"] = p.stat().st_size if p.exists() else None
    d["seal_from_template"] = bool(a.seal_layout)
    d["source_layout"] = bool(a.source_layout)
    return d


def listing(manifest: Path) -> dict:
    lib = AssetLibrary(manifest)
    return {"company": lib.lib.company, "editable": editable(manifest),
            "users": [u.model_dump() for u in lib.lib.users],
            "assets": [asset_out(lib, a) for a in lib.lib.assets]}


def sync_user(manifest: Path, username: str, name: str, role: str) -> None:
    """Keep the library's user list in step with the web accounts (stamp rights are checked against it)."""
    if not editable(manifest):
        return
    with LOCK:
        lib = AssetLibrary(manifest)
        for u in lib.lib.users:
            if u.id == username:
                if (u.name, u.role) == (name, role):
                    return
                u.name, u.role = name, role
                break
        else:
            lib.lib.users.append(LibUser(id=username, name=name, role=role, company=lib.lib.company))
        _save(lib)


def _flatten_image(data: bytes, out: Path) -> None:
    """Open an upload as an image; transparent areas become white paper (the background removal expects a scan)."""
    if len(data) > MAX_BYTES:
        raise AssetAdminError("file too large (15 MB at most)")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # noqa: BLE001
        raise AssetAdminError("not an image file (PNG, JPEG, TIFF or WebP)") from e
    if im.width < 50 or im.height < 50:
        raise AssetAdminError("image too small (at least 50 x 50 pixels)")
    if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    im.convert("RGB").save(out, "PNG")


def add_image(manifest: Path, kind: str, data: bytes, *, owner: Optional[str], owner_name: Optional[str],
              width_mm: Optional[float], name: Optional[str]) -> Asset:
    """Add a stamp or signature (background removed), switching off the one it replaces."""
    from ..imageprep import remove_background
    if kind not in IMAGE_TYPES:
        raise AssetAdminError("unknown asset type")
    if kind in OWNED and not owner:
        raise AssetAdminError("a certified stamp or signature needs its translator")
    if width_mm is not None and not 15 <= width_mm <= 120:
        raise AssetAdminError("print width must be between 15 and 120 mm")
    with LOCK:
        lib = _check_writable(manifest)
        if kind in OWNED and owner not in {u.id for u in lib.lib.users}:
            raise AssetAdminError("this translator is not in the asset library")
        same = [a for a in lib.lib.assets if a.type == kind and a.active and
                (a.owner_user == owner if kind in OWNED else True)]
        stem = {"stamp_certified": f"certified_{owner}", "stamp_office": "office", "signature": owner}[kind]
        sub = "signatures" if kind == "signature" else "stamps"
        ts = _stamp_now()
        rel = f"{sub}/{stem}_{ts}.png"
        (lib.root / sub).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "upload.png"
            _flatten_image(data, src)
            remove_background(src, lib.root / rel)
        width = width_mm or (same[0].width_mm if same else None) or (44.0 if kind == "signature" else 45.0)
        label = {"stamp_certified": "Certified stamp", "stamp_office": "Office stamp", "signature": "Signature"}[kind]
        a = Asset(id=f"{kind.replace('_', '-')}-{owner or lib.lib.company}-{ts}",
                  name=(name or "").strip()[:120] or (f"{label} - {owner_name or owner}" if owner else label),
                  type=kind, path=rel, owner_user=owner if kind in OWNED else None,
                  owner_company=lib.lib.company if kind == "stamp_office" else None, width_mm=round(width, 1))
        for old in same:
            old.active = False
        lib.lib.assets.append(a)
        _save(lib)
        return a


def _check_docx(data: bytes, what: str) -> None:
    if len(data) > MAX_BYTES:
        raise AssetAdminError(f"{what}: file too large (15 MB at most)")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "word/document.xml" not in z.namelist():
                raise AssetAdminError(f"{what}: not a Word .docx file")
    except zipfile.BadZipFile as e:
        raise AssetAdminError(f"{what}: not a Word .docx file") from e


def add_template(manifest: Path, data: bytes, *, name: Optional[str], language: Optional[str], pair: Optional[str],
                 reference_docx: Optional[bytes] = None, reference_pdf: Optional[bytes] = None) -> Asset:
    """Add a Word template the way ``setup-office`` does, switching off the template with the same binding."""
    from ..templates import align_footer_graphics, import_template, seal_from_reference, source_layout_from_reference_pdf
    _check_docx(data, "template")
    if reference_docx:
        _check_docx(reference_docx, "approved Word output")
    if reference_pdf is not None and not reference_pdf.startswith(b"%PDF"):
        raise AssetAdminError("approved PDF output: not a PDF file")
    language = (language or "").strip() or None
    pair = (pair or "").strip() or None
    with LOCK:
        lib = _check_writable(manifest)
        sig = next((a for a in lib.lib.assets if a.type == "signature" and a.active), None)
        stamps = [lib.path(a) for a in lib.lib.assets if a.type in ("stamp_certified", "stamp_office") and a.active]
        if sig is None or not stamps:
            raise AssetAdminError("add the signature and stamps first: the template import compares against them")
        same = [a for a in lib.lib.assets if a.type == "template" and a.active and a.language == language
                and a.pair == pair]
        ts = _stamp_now()
        rel = f"templates/template_{ts}.docx"
        tpl = lib.root / rel
        tpl.parent.mkdir(parents=True, exist_ok=True)
        tpl.write_bytes(data)
        try:
            with tempfile.TemporaryDirectory() as td:
                ref_docx = ref_pdf = None
                if reference_docx:
                    ref_docx = Path(td) / "reference.docx"
                    ref_docx.write_bytes(reference_docx)
                    align_footer_graphics(tpl, ref_docx)
                if reference_pdf:
                    ref_pdf = Path(td) / "reference.pdf"
                    ref_pdf.write_bytes(reference_pdf)
                imp = import_template(tpl, lib.path(sig), stamps)
                margins, source_layout = None, None
                if ref_docx:
                    ref = seal_from_reference(ref_docx, lib.path(sig), stamps)
                    imp["seal_layout"] = ref["seal_layout"] or imp["seal_layout"]
                    margins = ref["margins_mm"]
                if ref_pdf:
                    source_layout = source_layout_from_reference_pdf(ref_pdf, lib.path(sig), stamps)
        except AssetAdminError:
            raise
        except Exception as e:  # noqa: BLE001 - a broken upload must not leave a half-added template
            tpl.unlink(missing_ok=True)
            raise AssetAdminError(f"the template could not be read ({type(e).__name__})") from e
        prev = same[0] if same else None
        a = Asset(id=f"tpl-{ts}", name=(name or "").strip()[:120] or "Office template", type="template", path=rel,
                  language=language, pair=pair, seal_layout=imp["seal_layout"],
                  strip_footer_images=imp["strip_footer_images"],
                  # without an approved sample, keep the layout settings measured for the template it replaces
                  margins_mm=margins if ref_docx else (prev.margins_mm if prev else None),
                  house_style=prev.house_style if prev else {},
                  source_layout=source_layout if ref_pdf else (prev.source_layout if prev else None))
        for old in same:
            old.active = False
        lib.lib.assets.append(a)
        _save(lib)
        return a


def update(manifest: Path, asset_id: str, *, active: Optional[bool], name: Optional[str],
           width_mm: Optional[float]) -> tuple[Asset, dict]:
    """Rename, resize or switch an asset on/off. Switching one on switches off the others it would compete with."""
    with LOCK:
        lib = _check_writable(manifest)
        a = next((x for x in lib.lib.assets if x.id == asset_id), None)
        if a is None:
            raise KeyError(asset_id)
        changed: dict = {}
        if name is not None and name.strip() and name.strip() != a.name:
            a.name = changed["name"] = name.strip()[:120]
        if width_mm is not None and a.type != "template" and width_mm != a.width_mm:
            if not 15 <= width_mm <= 120:
                raise AssetAdminError("print width must be between 15 and 120 mm")
            a.width_mm = changed["width_mm"] = round(width_mm, 1)
        if active is not None and active != a.active:
            if active:
                for x in lib.lib.assets:
                    if x is not a and x.type == a.type and x.active and (
                            (a.type in OWNED and x.owner_user == a.owner_user) or a.type == "stamp_office" or
                            (a.type == "template" and (x.language, x.pair) == (a.language, a.pair))):
                        x.active = False
            a.active = changed["active"] = active
        if changed:
            _save(lib)
        return a, changed
