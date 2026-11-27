"""Page rendering and Tesseract OCR (the cheap first draft for Intake).

The OCR language pack comes from the source Language Profile (``ocr_pack``).
Born-digital PDFs also get their embedded text layer, which beats OCR.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .builder.pdf_builder import IMAGE_EXT


@dataclass
class OcrLine:
    text: str
    conf: float                       # mean word confidence 0-100
    bbox: tuple[int, int, int, int]   # pixels in the page image


@dataclass
class PageScan:
    number: int
    image: Image.Image                # upright-as-scanned page at ocr dpi
    lines: list[OcrLine] = field(default_factory=list)
    text_layer: str = ""              # embedded PDF text, if any
    mean_conf: float | None = None

    def draft_text(self) -> str:
        if len(self.text_layer.strip()) > 40:
            return self.text_layer
        return "\n".join(l.text for l in self.lines)

    def low_conf_lines(self, threshold: float) -> list[OcrLine]:
        return [l for l in self.lines if l.conf < threshold and len(l.text.strip()) > 2]


def render_pages(src: Path, dpi: int, workdir: Path) -> list[Image.Image]:
    workdir.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() in IMAGE_EXT:
        out = []
        with Image.open(src) as im:
            for i in range(getattr(im, "n_frames", 1)):
                im.seek(i)
                out.append(im.convert("RGB").copy())
        return out
    prefix = workdir / "ocr"
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(src), str(prefix)], check=True, capture_output=True)
    files = sorted(workdir.glob("ocr-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
    return [Image.open(f).convert("RGB") for f in files]


def text_layer(src: Path) -> list[str]:
    if src.suffix.lower() != ".pdf":
        return []
    try:
        from pypdf import PdfReader
        return [(p.extract_text() or "") for p in PdfReader(str(src)).pages]
    except Exception:  # noqa: BLE001 - damaged PDFs fall back to OCR
        return []


def available_packs() -> set[str]:
    if not shutil.which("tesseract"):
        return set()
    res = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
    return {l.strip() for l in res.stdout.splitlines()[1:] if l.strip()}


def ocr_image(im: Image.Image, packs: list[str]) -> list[OcrLine]:
    """Tesseract TSV -> lines with mean confidence. Missing packs are skipped
    (vision then carries the reading)."""
    have = available_packs()
    langs = "+".join(p for p in packs if p in have) or ("eng" if "eng" in have else "")
    if not langs:
        return []
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "p.png"
        im.save(p)
        res = subprocess.run(["tesseract", str(p), "stdout", "-l", langs, "--psm", "3", "tsv"],
                             capture_output=True, text=True)
    rows = [r.split("\t") for r in res.stdout.splitlines()[1:]]
    lines: dict[tuple, list] = {}
    for r in rows:
        if len(r) < 12 or not r[11].strip():
            continue
        try:
            conf = float(r[10])
        except ValueError:
            continue
        key = (int(r[2]), int(r[3]), int(r[4]))      # block, paragraph, line
        x, y, w, h = map(int, r[6:10])
        lines.setdefault(key, []).append((r[11], conf, (x, y, x + w, y + h)))
    out = []
    for key in sorted(lines):
        words = lines[key]
        text = " ".join(w[0] for w in words)
        conf = sum(w[1] for w in words) / len(words)
        x0 = min(w[2][0] for w in words); y0 = min(w[2][1] for w in words)
        x1 = max(w[2][2] for w in words); y1 = max(w[2][3] for w in words)
        out.append(OcrLine(text, conf, (x0, y0, x1, y1)))
    return out


def scan_document(src: Path, ocr_packs: list[str], dpi: int = 300) -> list[PageScan]:
    with tempfile.TemporaryDirectory() as td:
        images = render_pages(src, dpi, Path(td))
    layers = text_layer(src)
    pages = []
    for i, im in enumerate(images):
        layer = layers[i] if i < len(layers) else ""
        lines = [] if len(layer.strip()) > 40 else ocr_image(im, ocr_packs)
        mean = sum(l.conf for l in lines) / len(lines) if lines else None
        pages.append(PageScan(i + 1, im, lines, layer, mean))
    return pages


def jpeg_bytes(im: Image.Image, max_side: int = 1600, quality: int = 85) -> bytes:
    """Downscale for the vision call (keeps tokens and request size reasonable)."""
    im = im.copy()
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def crop_norm(im: Image.Image, bbox_1000: list[int], pad: int = 15, scale: float = 2.0) -> Image.Image:
    """Crop a 0-1000 normalised box (with padding) and upscale for a re-read."""
    x0, y0, x1, y1 = bbox_1000
    W, H = im.size
    box = (max(0, int((x0 - pad) * W / 1000)), max(0, int((y0 - pad) * H / 1000)),
           min(W, int((x1 + pad) * W / 1000)), min(H, int((y1 + pad) * H / 1000)))
    c = im.crop(box)
    if scale != 1.0:
        c = c.resize((max(1, int(c.width * scale)), max(1, int(c.height * scale))), Image.LANCZOS)
    return c
