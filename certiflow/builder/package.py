"""Build one certified package (Word + integrated PDF + disclosures) and batch zips."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..assets import AssetLibrary
from ..model import BlockType, Document, JobSpec, PageInfo
from ..profiles import get_profile
from .docx_builder import BuildOptions, SealSpec, render
from .pdf_builder import (BuildError, docx_to_pdf, find_seal_on_page, merge, page_size, rasterize_source,
                          stamp_source_pages, upright, verify_certified_pdf)


class ReleaseBlocked(BuildError):
    pass


@dataclass
class PackageResult:
    docx: Path
    pdf: Path
    disclosures: list[str]
    translation_pages: int
    source_pages: int
    page_order: str
    stamp_asset: str
    signature_asset: str
    verify_failures: list[str] = field(default_factory=list)
    audit: dict = field(default_factory=dict)


def safe_title(t: str) -> str:
    t = re.sub(r"[^\w\- ]+", "", t, flags=re.UNICODE).strip().replace(" ", "_")
    return t[:60] or "Document"


def build_package(model: Document, source: Path, job: JobSpec, library: AssetLibrary, outdir: Path,
                  index: int = 1, *, dpi: int = 130, jpeg_quality: int = 80) -> PackageResult:
    stamp, sig = library.stamp_for(job.stamp, job.user_id)
    tpl = library.template_for(model.target_language, model.source_language, job.template_id)
    seal = SealSpec(stamp_png=library.path(stamp), signature_png=library.path(sig),
                    stamp_width_mm=stamp.width_mm or 38.0, signature_width_mm=sig.width_mm or 32.0)
    tgt = get_profile(model.target_language)
    base = f"{index:02d}_{safe_title(model.title)}_{tgt.code.upper()}"
    outdir.mkdir(parents=True, exist_ok=True)
    final_docx = outdir / f"{base}.docx"
    final_pdf = outdir / f"{base}.pdf"

    with tempfile.TemporaryDirectory(prefix="cf_build_") as td:
        td = Path(td)
        render(model, library.path(tpl), final_docx,
               BuildOptions(font_mode="word", seal=seal, page_order=job.pdf_page_order))
        pdf_docx = render(model, library.path(tpl), td / f"{base}.docx",
                          BuildOptions(font_mode="pdf", seal=seal, page_order=job.pdf_page_order))
        tr_pdf = docx_to_pdf(pdf_docx, td / "tr")
        n_tr = len(_reader(tr_pdf).pages)
        footer = find_seal_on_page(tr_pdf, 0, seal)
        if footer is None:
            raise BuildError("could not locate the seal in the translation footer")
        pw, ph = page_size(tr_pdf)

        rot = {p.number: p.rotation for p in model.pages}
        images = [upright(im, rot.get(i + 1, 0)) for i, im in enumerate(rasterize_source(source, td / "src", dpi))]
        src_pdf = td / "source_stamped.pdf"
        rep = stamp_source_pages(images, src_pdf, pw, ph, seal, footer, jpeg_quality=jpeg_quality)
        merged, effective = merge(tr_pdf, src_pdf, td / "merged.pdf", job.pdf_page_order)

        v = verify_certified_pdf(merged, seal, expected_pages=n_tr + len(images))
        if not v.ok:
            raise ReleaseBlocked("certified PDF failed verification: " + "; ".join(v.failures[:10]))
        shutil.copy(merged, final_pdf)

    disclosures = make_disclosures(model, rep.dense_pages, effective, job)
    return PackageResult(
        docx=final_docx, pdf=final_pdf, disclosures=disclosures, translation_pages=n_tr,
        source_pages=len(images), page_order=effective, stamp_asset=stamp.id, signature_asset=sig.id,
        audit={"at": datetime.now(timezone.utc).isoformat(), "user": job.user_id, "stamp_choice": job.stamp.value,
               "stamp_asset": stamp.id, "signature_asset": sig.id, "template": tpl.id,
               "page_order_requested": job.pdf_page_order.value, "page_order_effective": effective,
               "pdf_bytes": final_pdf.stat().st_size, "source_seal_ink": [round(x, 4) for x in rep.ink_covered]},
    )


def _reader(p: Path):
    from pypdf import PdfReader
    return PdfReader(str(p))


def make_disclosures(model: Document, dense_pages: list[int], effective_order: str, job: JobSpec) -> list[str]:
    out: list[str] = []
    for b in model.blocks:
        loc = f"source page {b.source_page}" if b.source_page else "document"
        if b.type == BlockType.unreadable:
            out.append(f"{loc}: {b.unreadable_reason.value.replace('_', ' ')} ({b.id})")
        if b.multilingual_duplicate:
            out.append(f"{loc}: text repeated in several languages, translated once ({b.id})")
        for f in b.flags:
            if b.type == BlockType.unreadable and b.unreadable_reason and f.code == b.unreadable_reason.value:
                continue  # already listed above
            if not f.resolved and f.code in ("covered_by_stamp", "low_confidence", "illegible"):
                out.append(f"{loc}: {f.code.replace('_', ' ')} - {f.message} ({b.id})")
    if dense_pages:
        out.append("The stamp and signature overlay may cover a few lines on dense source pages: "
                   + ", ".join(str(p) for p in dense_pages))
    if job.pdf_page_order.value == "interleaved" and effective_order != "interleaved":
        out.append("Interleaved page order was requested but the page mapping was not reliable; "
                   "the PDF uses translation then source.")
    return out


def write_disclosures(results: list[tuple[str, PackageResult]], path: Path) -> Path:
    lines = []
    for name, r in results:
        lines.append(f"== {name}")
        lines += [f"- {d}" for d in r.disclosures] or ["- none"]
        lines.append("")
    path.write_text("\n".join(lines), "utf-8")
    return path


def zip_batch(results: list[tuple[str, PackageResult]], outdir: Path, batch_name: str) -> Path:
    disc = write_disclosures(results, outdir / "disclosures.txt")
    z = outdir / f"{safe_title(batch_name)}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for _, r in results:
            zf.write(r.docx, f"{safe_title(batch_name)}/{r.docx.name}")
            zf.write(r.pdf, f"{safe_title(batch_name)}/{r.pdf.name}")
        zf.write(disc, f"{safe_title(batch_name)}/disclosures.txt")
    return z
