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
                     office_width_mm=args.office_width_mm, signature_width_mm=args.signature_width_mm,
                     reference_docx=Path(args.reference_docx) if args.reference_docx else None,
                     reference_pdf=Path(args.reference_pdf) if args.reference_pdf else None)
    print(Path(m).read_text("utf-8"))
    return 0


def cmd_golden(args) -> int:
    from .golden import import_docx, run_golden_set
    from .house import HouseStyle
    if args.action == "import":
        m = import_docx(Path(args.path), args.source_lang, args.target_lang, HouseStyle())
        print(m.model_dump_json(indent=1, exclude_defaults=True))
        return 0
    lib = AssetLibrary(Path(args.library))
    if args.action == "score":
        return _golden_score(args, lib)
    res = run_golden_set(Path(args.path), lib, args.user, Path(args.out))
    bad = 0
    for r in res:
        pages = "" if r.tr_pages is None else f"  translation pages {r.tr_pages}" + (
            f" (approved {r.approved_tr_pages})" if r.approved_tr_pages is not None else "")
        print(f"{'PASS' if r.body_exact else 'FAIL'}  {r.pair}/{r.case}: body {r.body_identical}/{r.body_total}{pages}")
        for d in r.diffs[:3]:
            print("      " + d[:300])
        bad += not r.body_exact
    return 1 if bad else 0


def cmd_fonts(args) -> int:
    from .fonts import FONT_DIR, available, install
    from .profiles import all_profiles
    if args.action == "install":
        print("installed:", ", ".join(install(Path(args.dir))), "->", FONT_DIR)
    for p in all_profiles():
        ok = available(p.pdf_font)
        used = p.pdf_font if ok or not p.pdf_font_fallback else p.pdf_font_fallback
        print(f"{p.code:3} pdf font {p.pdf_font:22} {'installed' if ok else 'MISSING':9} -> PDF uses {used}")
    return 0


def _client(mock_target: str | None):
    from .settings import load
    if mock_target:
        from .llm.mock_agents import make_mock
        print("NOTE: --mock uses offline pseudo-translations for testing; the output is not a real translation.")
        return make_mock(mock_target)
    import os
    from .llm.client import api_key_from_env
    if not api_key_from_env():
        sys.exit("error: no Claude API key in this environment. Set CERTIFLOW_ANTHROPIC_API_KEY "
                 "(or ANTHROPIC_API_KEY on your own server), or run with --mock for an offline test run")
    from .llm.client import AnthropicClient
    st = load()
    return AnthropicClient(fallbacks=st.fallbacks, validation_retries=st.pipeline.validation_retries)


def _print_run(r: dict, job) -> None:
    import json as _j
    print(f"stage: {r['stage']}")
    for w in r.get("waiting") or []:
        if w.get("waiting_for") == "glossary_confirmation":
            print(f"WAITING: glossary confirmation ({w['proposed']} proposed) -> edit {w['file']} if needed, then:"
                  f"\n  certiflow job confirm-glossary {job.dir} --by <user>")
        elif w.get("waiting_for") == "final_review":
            print("WAITING: final review by a certified translator. Review the model files:")
            for k, v in w["documents"].items():
                print(f"  {k}: {v}")
            print(f"  then: certiflow job approve {job.dir} --by <certified translator id>")
    if r.get("released"):
        print("RELEASED:")
        for p in r["released"]:
            print("  " + p)
    print(_j.dumps(job.status()["cost"], indent=1))


def cmd_translate(args) -> int:
    from .pipeline.job import Job
    job_spec = _job(args)
    lib = AssetLibrary(Path(args.library))
    lib.stamp_for(job_spec.stamp, job_spec.user_id)   # fail early if the user may not apply this stamp
    jd = Job.create(Path(args.job_dir), [Path(s) for s in args.sources], args.source_lang, args.target_lang,
                    job_spec, Path(args.library))
    job = Job(jd, _client(args.target_lang if args.mock else None))
    r = job.run()
    if args.auto_confirm_glossary and r["waiting"] and r["waiting"][0].get("waiting_for") == "glossary_confirmation":
        r = job.run(resume={"by": args.user})
    _print_run(r, job)
    return 0


def cmd_job(args) -> int:
    import json as _j
    from .pipeline.job import Job
    meta = _j.loads((Path(args.job_dir) / "job.json").read_text("utf-8"))
    tgt = meta["documents"][0]["target_language"]
    job = Job(Path(args.job_dir), _client(tgt if args.mock else None))
    if args.action == "status":
        print(_j.dumps(job.status(), indent=1, ensure_ascii=False))
        return 0
    if args.action == "confirm-glossary":
        ans = {"by": args.by}
        if args.file:
            ans["glossary"] = _j.loads(Path(args.file).read_text("utf-8"))
        r = job.run(resume=ans)
    elif args.action == "approve":
        if args.reviewed:
            import shutil
            for f in Path(args.reviewed).glob("*.json"):
                shutil.copy(f, job.dir / "docs" / f.name.replace(".formatted.", ".reviewed."))
        r = job.run(resume={"approved_by": args.by, "note": args.note})
    else:
        r = job.run()
    _print_run(r, job)
    return 0


def _golden_score(args, lib) -> int:
    """Run the agent pipeline on every golden case's source and score it against the approved translation."""
    from .golden import extract_source_from_approved_pdf, import_docx, score_against_approved
    from .house import HouseStyle
    from .model import JobSpec
    from .pipeline.job import Job
    root, out = Path(args.path), Path(args.out)
    failed = 0
    for pair_dir in sorted(p for p in root.iterdir() if p.is_dir() and "-" in p.name):
        src, tgt = pair_dir.name.split("-", 1)
        for case in sorted(p for p in pair_dir.iterdir() if p.is_dir()):
            source = next(iter(sorted(case.glob("source.*"))), None)
            if source is None and (case / "approved.pdf").exists():
                source = extract_source_from_approved_pdf(case / "approved.pdf", case / "source.pdf")
            if source is None:
                print(f"SKIP  {pair_dir.name}/{case.name}: no source document")
                continue
            jd = out / pair_dir.name / case.name
            if not (jd / "job.json").exists():
                Job.create(jd, [source], src, tgt, JobSpec(stamp="certified", user_id=args.user), Path(args.library),
                           titles=[case.name])
            job = Job(jd, _client(tgt if args.mock else None))
            r = job.run()
            if r["waiting"] and r["waiting"][0].get("waiting_for") == "glossary_confirmation":
                job.run(resume={"by": args.user})
            output = job.load_doc("d01", "formatted")
            approved = import_docx(case / "approved.docx", src, tgt, HouseStyle())
            s = score_against_approved(case.name, output, approved)
            cost = sum(a["cost_usd"] for a in job.audit_totals().values())
            print(f"{'PASS' if s.passed else 'FAIL'}  {pair_dir.name}/{case.name}: figures {s.figures_recall:.0%}  "
                  f"ids {s.identifiers_recall:.0%}  length x{s.length_ratio}  leftover {s.leftover_findings}  "
                  f"open blockers {s.open_blockers}  cost ${cost:.2f}")
            failed += not s.passed
    return 1 if failed else 0


def cmd_web(args) -> int:
    import getpass
    from .web.config import get_config
    cfg = get_config()
    if args.action == "init-db":
        from alembic import command
        from alembic.config import Config
        root = Path(__file__).resolve().parents[1]
        ac = Config(str(root / "alembic.ini"))
        ac.set_main_option("script_location", str(root / "migrations"))
        ac.set_main_option("sqlalchemy.url", cfg.database_url)
        command.upgrade(ac, "head")
        print("database ready:", cfg.database_url.split("@")[-1])
        return 0
    if args.action == "create-user":
        from .web.auth import hash_password
        from .web.db import User, session_factory, user_by_username
        if args.role not in ("admin", "certified_translator", "reviewer"):
            sys.exit("role must be admin, certified_translator or reviewer")
        pw = args.password or getpass.getpass("Password: ")
        if len(pw) < 10:
            sys.exit("use at least 10 characters")
        with session_factory(cfg.database_url)() as s:
            u = user_by_username(s, args.username.lower())
            if u is None:
                u = User(username=args.username.lower(), name=args.name or args.username, role=args.role,
                         password_hash=hash_password(pw))
                s.add(u)
            else:
                u.role, u.password_hash = args.role, hash_password(pw)
                u.name = args.name or u.name
            s.commit()
        print(f"user {args.username.lower()} saved ({args.role})")
        return 0
    if args.action == "serve":
        import uvicorn
        from .web.app import create_app
        uvicorn.run(create_app(cfg), host=args.host, port=args.port, proxy_headers=True)
        return 0
    return 1


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
    so.add_argument("--reference-docx", help="an approved output: seal size/position and margins are taken from it")
    so.add_argument("--reference-pdf", help="the approved PDF: source-page layout (scan area, seal band) is taken from it")
    for a in ("--certified-width-mm", "--office-width-mm", "--signature-width-mm"):
        so.add_argument(a, type=float)
    so.set_defaults(fn=cmd_setup_office)

    gd = sub.add_parser("golden", help="golden set: import an approved .docx, or rebuild and compare a whole set")
    gd.add_argument("action", choices=["import", "run", "score"])
    gd.add_argument("path")
    gd.add_argument("--source-lang", default="en")
    gd.add_argument("--target-lang", default="ar")
    gd.add_argument("--library")
    gd.add_argument("--user")
    gd.add_argument("--out", default="out/golden_run")
    gd.add_argument("--mock", action="store_true", help="score: offline pseudo-translation (tests the harness only)")
    gd.set_defaults(fn=cmd_golden)

    fo = sub.add_parser("fonts", help="install licensed office fonts / show which PDF font each language uses")
    fo.add_argument("action", choices=["install", "status"])
    fo.add_argument("dir", nargs="?", default="assets/fonts")
    fo.set_defaults(fn=cmd_fonts)

    tr = sub.add_parser("translate", help="run the agent pipeline on source documents (stops at human gates)")
    tr.add_argument("sources", nargs="+")
    tr.add_argument("--from", dest="source_lang", required=True, help="source language code, or auto")
    tr.add_argument("--to", dest="target_lang", required=True)
    tr.add_argument("--job-dir", required=True)
    tr.add_argument("--auto-confirm-glossary", action="store_true")
    tr.add_argument("--mock", action="store_true", help="offline pseudo-translation (testing only)")
    job_args(tr)
    tr.set_defaults(fn=cmd_translate)

    jb = sub.add_parser("job", help="status / confirm-glossary / approve / resume a job")
    jb.add_argument("action", choices=["status", "confirm-glossary", "approve", "resume"])
    jb.add_argument("job_dir")
    jb.add_argument("--by")
    jb.add_argument("--file", help="edited glossary JSON")
    jb.add_argument("--reviewed", help="directory with reviewed model files (<doc>.formatted.json edited)")
    jb.add_argument("--note")
    jb.add_argument("--mock", action="store_true")
    jb.set_defaults(fn=cmd_job)

    wb = sub.add_parser("web", help="web app: init-db / create-user / serve")
    wb.add_argument("action", choices=["init-db", "create-user", "serve"])
    wb.add_argument("username", nargs="?")
    wb.add_argument("--role", default="certified_translator")
    wb.add_argument("--name")
    wb.add_argument("--password", help="omit to be prompted (recommended)")
    wb.add_argument("--host", default="127.0.0.1")
    wb.add_argument("--port", type=int, default=8000)
    wb.set_defaults(fn=cmd_web)

    sc = sub.add_parser("schema")
    sc.add_argument("out", nargs="?")
    sc.set_defaults(fn=cmd_schema)

    pr = sub.add_parser("profiles")
    pr.set_defaults(fn=cmd_profiles)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
