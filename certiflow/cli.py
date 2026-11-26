"""CertiFlow command line (Phase 1).

  certiflow samples  OUT_DIR
  certiflow build    MODEL.json --source SRC --stamp certified|office --user ID --library library.json --out DIR
  certiflow batch    JOB.json --library library.json --out DIR
  certiflow verify   CERTIFIED.pdf --library library.json --stamp ... --user ... --pages N
  certiflow schema   [OUT.json]
  certiflow profiles
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .assets import AssetLibrary
from .model import Document, JobSpec


def _job(args) -> JobSpec:
    try:
        return JobSpec(stamp=args.stamp, user_id=args.user, template_id=args.template,
                       pdf_page_order=args.order)
    except ValidationError as e:
        if any(err["loc"] == ("stamp",) for err in e.errors()):
            sys.exit("error: a stamp must be chosen for every job: --stamp certified or --stamp office")
        raise


def cmd_build(args) -> int:
    from .builder.package import build_package, write_disclosures
    model = Document.model_validate_json(Path(args.model).read_text("utf-8"))
    lib = AssetLibrary(Path(args.library))
    res = build_package(model, Path(args.source), _job(args), lib, Path(args.out))
    write_disclosures([(model.title, res)], Path(args.out) / "disclosures.txt")
    print(json.dumps({"docx": str(res.docx), "pdf": str(res.pdf), "translation_pages": res.translation_pages,
                      "source_pages": res.source_pages, "page_order": res.page_order,
                      "disclosures": res.disclosures, "audit": res.audit}, ensure_ascii=False, indent=2))
    return 0


def cmd_batch(args) -> int:
    """JOB.json: {"name": "...", "stamp": "...", "user_id": "...", "documents": [{"model": "...", "source": "..."}]}"""
    from concurrent.futures import ProcessPoolExecutor
    from .builder.package import zip_batch
    spec = json.loads(Path(args.job).read_text("utf-8"))
    base = Path(args.job).parent
    job = JobSpec(**{k: v for k, v in spec.items() if k in JobSpec.model_fields})
    out = Path(args.out)
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_build_one, base / d["model"], base / d["source"], job, args.library, out, i + 1)
                for i, d in enumerate(spec["documents"])]
        results = [f.result() for f in futs]
    z = zip_batch(results, out, spec.get("name", "batch"))
    print(z)
    return 0


def _build_one(model_p, src_p, job, library, out, idx):
    from .builder.package import build_package
    m = Document.model_validate_json(Path(model_p).read_text("utf-8"))
    return m.title, build_package(m, Path(src_p), job, AssetLibrary(Path(library)), out, idx)


def cmd_verify(args) -> int:
    from .builder.docx_builder import SealSpec
    from .builder.pdf_builder import verify_certified_pdf
    lib = AssetLibrary(Path(args.library))
    stamp, sig = lib.stamp_for(_job(args).stamp, args.user)
    seal = SealSpec(lib.path(stamp), lib.path(sig), stamp.width_mm or 38, sig.width_mm or 32)
    v = verify_certified_pdf(Path(args.pdf), seal, args.pages)
    print(json.dumps(v.__dict__, indent=2))
    return 0 if v.ok else 2


def cmd_samples(args) -> int:
    from . import samples
    base = Path(args.out)
    samples.make_library(base / "assets")
    samples.make_source_pdf(base / "sources" / "en_good_standing.pdf")
    samples.make_rtl_source_pdf(base / "sources" / "ar_good_conduct.pdf")
    print(f"samples written to {base}")
    return 0


def cmd_setup_office(args) -> int:
    from .office_setup import setup_office
    m = setup_office(Path(args.template), Path(args.signature), Path(args.certified_stamp), Path(args.office_stamp),
                     Path(args.out), company=args.company, translator_id=args.translator_id,
                     translator_name=args.translator_name, certified_width_mm=args.certified_width_mm,
                     office_width_mm=args.office_width_mm, signature_width_mm=args.signature_width_mm)
    print(Path(m).read_text("utf-8"))
    return 0


def cmd_schema(args) -> int:
    s = json.dumps(Document.model_json_schema(), indent=2)
    if args.out:
        Path(args.out).write_text(s, "utf-8")
    else:
        print(s)
    return 0


def cmd_profiles(args) -> int:
    from .profiles import all_profiles
    for p in all_profiles():
        print(f"{p.code:3} {p.display_name:22} {p.script} {p.direction.value}  word={p.word_font}  pdf={p.pdf_font}  ocr={p.ocr_pack}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="certiflow")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def job_args(p):
        p.add_argument("--stamp", choices=["certified", "office"], default=None,
                       help="required: which stamp to apply (no default)")
        p.add_argument("--user", required=True)
        p.add_argument("--template")
        p.add_argument("--order", choices=["translation_then_source", "interleaved"], default="translation_then_source")
        p.add_argument("--library", required=True)

    b = sub.add_parser("build")
    b.add_argument("model")
    b.add_argument("--source", required=True)
    b.add_argument("--out", required=True)
    job_args(b)
    b.set_defaults(fn=cmd_build)

    bt = sub.add_parser("batch")
    bt.add_argument("job")
    bt.add_argument("--library", required=True)
    bt.add_argument("--out", required=True)
    bt.add_argument("--workers", type=int, default=2)
    bt.set_defaults(fn=cmd_batch)

    v = sub.add_parser("verify")
    v.add_argument("pdf")
    v.add_argument("--pages", type=int, required=True)
    job_args(v)
    v.set_defaults(fn=cmd_verify)

    s = sub.add_parser("samples")
    s.add_argument("out")
    s.set_defaults(fn=cmd_samples)

    so = sub.add_parser("setup-office", help="register template, stamps and signature from raw scans")
    for a in ("--template", "--signature", "--certified-stamp", "--office-stamp", "--out", "--translator-id",
              "--translator-name"):
        so.add_argument(a, required=True)
    so.add_argument("--company", default="shoreline")
    for a in ("--certified-width-mm", "--office-width-mm", "--signature-width-mm"):
        so.add_argument(a, type=float)
    so.set_defaults(fn=cmd_setup_office)

    sc = sub.add_parser("schema")
    sc.add_argument("out", nargs="?")
    sc.set_defaults(fn=cmd_schema)

    pr = sub.add_parser("profiles")
    pr.set_defaults(fn=cmd_profiles)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
