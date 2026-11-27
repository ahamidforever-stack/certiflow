"""CertiFlow web API (FastAPI).

Security rules applied here:
* session cookie is HttpOnly, SameSite=Strict, signed; state-changing requests also need the
  ``X-CertiFlow: 1`` header (simple CSRF guard - browsers cannot add it cross-site without CORS)
* the Anthropic API key never leaves the server; the browser only talks to this API
* every job is visible to its creator, its signing translator and admins only
* the stamp choice is required (no default) and checked against the Asset Library rights
* progress events never carry document text
"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from ..assets import AssetError, AssetLibrary
from ..model import JobSpec, PageOrder, StampChoice
from ..profiles import all_profiles, get_profile
from . import runner
from .auth import COOKIE, make_token, read_token, verify_password
from .config import WebConfig, get_config, set_config
from .db import Job as JobRow
from .db import JobDocument, JobEvent, User, session_factory, user_by_username

SOURCE_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".docx", ".doc", ".odt", ".rtf"}
CONVERT_EXT = {".docx", ".doc", ".odt", ".rtf"}
PUBLIC_EVENT_KEYS = {"kind", "at", "agent", "stage", "document", "model", "cost_usd", "latency_s", "retries",
                     "blocks", "changes", "qa_loops", "open_blockers", "loop", "items", "by", "docx", "pdf",
                     "stamp_choice", "error"}


# ------------------------------------------------------------------ request models


class LoginIn(BaseModel):
    username: str
    password: str


class PrefsIn(BaseModel):
    ui_language: str


class GlossaryItemIn(BaseModel):
    source: str
    target: str
    kind: str = "term"


class GlossaryIn(BaseModel):
    items: list[GlossaryItemIn]


class ApproveIn(BaseModel):
    note: Optional[str] = None


def create_app(cfg: WebConfig | None = None) -> FastAPI:
    cfg = cfg or get_config()
    set_config(cfg)
    Session = session_factory(cfg.database_url)
    app = FastAPI(title="CertiFlow", docs_url="/api/docs", openapi_url="/api/openapi.json")

    def library() -> AssetLibrary:
        return AssetLibrary(cfg.library)

    # ------------------------------------------------------------------ auth

    def current_user(request: Request) -> User:
        tok = request.cookies.get(COOKIE)
        uid = read_token(tok, cfg.secret_key) if tok else None
        if uid is None:
            raise HTTPException(401, "not signed in")
        with Session() as s:
            u = s.get(User, uid)
            if u is None or not u.active:
                raise HTTPException(401, "not signed in")
            return u

    def csrf(request: Request) -> None:
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-certiflow") != "1":
            raise HTTPException(403, "missing X-CertiFlow header")


    @app.post("/api/auth/login")
    def login(body: LoginIn, response: Response, _=Depends(csrf)):
        with Session() as s:
            u = user_by_username(s, body.username.strip().lower())
            if u is None or not u.active or not verify_password(body.password, u.password_hash):
                raise HTTPException(401, "wrong username or password")
            response.set_cookie(COOKIE, make_token(u.id, cfg.secret_key, cfg.session_hours), httponly=True,
                                samesite="strict", secure=cfg.secure_cookies, max_age=cfg.session_hours * 3600)
            return _user_out(u)

    @app.post("/api/auth/logout")
    def logout(response: Response, _=Depends(csrf)):
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(u: User = Depends(current_user)):
        return _user_out(u)


    @app.post("/api/me/prefs")
    def prefs(body: PrefsIn, u: User = Depends(current_user), _=Depends(csrf)):
        if body.ui_language not in ("en", "ar"):
            raise HTTPException(422, "ui_language must be en or ar")
        with Session() as s:
            s.get(User, u.id).ui_language = body.ui_language
            s.commit()
        return {"ok": True}

    # -------------------------------------------------------------- reference

    @app.get("/api/languages")
    def languages(_: User = Depends(current_user)):
        return [{"code": p.code, "name": p.display_name, "native": p.native_name, "direction": p.direction.value}
                for p in sorted(all_profiles(), key=lambda p: p.display_name)]

    @app.get("/api/stamps")
    def stamps(u: User = Depends(current_user)):
        """Stamp choices this user can apply (both are shown; unavailable ones say why)."""
        lib = library()
        out = []
        for choice, label in ((StampChoice.certified, "Certified stamp"), (StampChoice.office, "Office stamp")):
            try:
                st, _sig = lib.stamp_for(choice, u.username)
                out.append({"choice": choice.value, "label": label, "name": st.name, "available": True,
                            "image": f"/api/stamps/{choice.value}/image"})
            except AssetError as e:
                out.append({"choice": choice.value, "label": label, "available": False, "reason": str(e)})
        return out

    @app.get("/api/stamps/{choice}/image")
    def stamp_image(choice: StampChoice, u: User = Depends(current_user)):
        try:
            st, _sig = library().stamp_for(choice, u.username)
        except AssetError:
            raise HTTPException(403, "not authorised for this stamp")
        return FileResponse(library().path(st), media_type="image/png",
                            headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/recent-pairs")
    def recent_pairs(u: User = Depends(current_user)):
        with Session() as s:
            rows = s.execute(select(JobRow.source_language, JobRow.target_language)
                             .where(JobRow.created_by == u.id).order_by(JobRow.created_at.desc()).limit(50)).all()
        seen, out = set(), []
        for a, b in rows:
            if (a, b) not in seen:
                seen.add((a, b))
                out.append({"source": a, "target": b})
        return out[:5]

    # -------------------------------------------------------------------- jobs

    def _job_for(s, job_id: str, u: User) -> JobRow:
        row = s.get(JobRow, job_id)
        if row is None or not _may_see(row, u):
            raise HTTPException(404, "job not found")
        return row

    @app.post("/api/jobs", status_code=201)
    async def create_job(
        files: list[UploadFile] = File(...),
        source_language: str = Form(...),
        target_language: str = Form(...),
        stamp: Optional[str] = Form(None),
        page_order: str = Form("translation_then_source"),
        document_type: Optional[str] = Form(None),
        notes: Optional[str] = Form(None),
        overrides: Optional[str] = Form(None),
        u: User = Depends(current_user), _=Depends(csrf),
    ):
        from ..pipeline.job import Job
        if u.role not in ("certified_translator", "admin"):
            raise HTTPException(403, "only certified translators and admins can start jobs")
        if stamp not in ("certified", "office"):
            raise HTTPException(422, "choose a stamp: certified or office")
        codes = {p.code for p in all_profiles()}
        if (source_language != "auto" and source_language not in codes) or target_language not in codes:
            raise HTTPException(422, "unsupported language")
        if source_language == target_language:
            raise HTTPException(422, "source and target language must differ")
        try:
            PageOrder(page_order)
        except ValueError:
            raise HTTPException(422, "page_order must be translation_then_source or interleaved")
        try:
            library().stamp_for(StampChoice(stamp), u.username)
        except AssetError as e:
            raise HTTPException(403, f"stamp not available to you: {e}")
        if not files:
            raise HTTPException(422, "add at least one source document")
        per_doc = json.loads(overrides) if overrides else {}

        job_id = datetime.now(timezone.utc).strftime("J%Y%m%d-") + secrets.token_hex(3)
        jd = runner.job_dir(cfg, job_id)
        up = jd / "uploads"
        up.mkdir(parents=True, exist_ok=True)
        sources, titles, docs_meta = [], [], []
        try:
            for i, f in enumerate(files):
                name = Path(f.filename or f"document{i + 1}").name
                ext = Path(name).suffix.lower()
                if ext not in SOURCE_EXT:
                    raise HTTPException(422, f"{name}: unsupported file type")
                dest = up / f"{i + 1:02d}_{_safe(name)}"
                size = 0
                with open(dest, "wb") as out:
                    while chunk := await f.read(1 << 20):
                        size += len(chunk)
                        if size > cfg.max_upload_mb << 20:
                            raise HTTPException(413, f"{name}: larger than {cfg.max_upload_mb} MB")
                        out.write(chunk)
                if ext in CONVERT_EXT:
                    from ..builder.pdf_builder import docx_to_pdf
                    dest = await asyncio.to_thread(docx_to_pdf, dest, up)
                ov = per_doc.get(str(i), {})
                s_lang, t_lang = ov.get("source_language", source_language), ov.get("target_language", target_language)
                if (s_lang != "auto" and s_lang not in codes) or t_lang not in codes or s_lang == t_lang:
                    raise HTTPException(422, f"{name}: invalid language override")
                sources.append(dest)
                titles.append(Path(name).stem.replace("_", " ")[:120])
                docs_meta.append((s_lang, t_lang, name))
        except HTTPException:
            shutil.rmtree(jd, ignore_errors=True)
            raise
        spec = JobSpec(stamp=StampChoice(stamp), user_id=u.username, pdf_page_order=PageOrder(page_order),
                       notes=notes)
        Job.create(jd, sources, source_language, target_language, spec, cfg.library, titles=titles,
                   languages=[(a, b) for a, b, _n in docs_meta])
        with Session() as s:
            row = JobRow(id=job_id, created_by=u.id, title=titles[0] + (f" +{len(titles) - 1}" if len(titles) > 1 else ""),
                         source_language=source_language, target_language=target_language, stamp=stamp,
                         page_order=page_order, document_type=document_type, notes=notes, status="queued")
            for i, (a, b, n) in enumerate(docs_meta):
                row.documents.append(JobDocument(idx=i, doc_key=f"d{i + 1:02d}", title=titles[i], filename=n,
                                                 source_language=a, target_language=b))
            s.add(row)
            s.add(JobEvent(job_id=job_id, kind="status", data={"status": "queued"}))
            s.commit()
        runner.submit(job_id)
        return {"id": job_id}

    @app.get("/api/jobs")
    def list_jobs(u: User = Depends(current_user)):
        with Session() as s:
            q = select(JobRow).order_by(JobRow.created_at.desc()).limit(200)
            if u.role != "admin":
                q = q.where(JobRow.created_by == u.id)
            return [_job_out(r, brief=True) for r in s.scalars(q)]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, u: User = Depends(current_user)):
        from ..pipeline.job import Job
        with Session() as s:
            row = _job_for(s, job_id, u)
            out = _job_out(row)
        jd = runner.job_dir(cfg, job_id)
        if (jd / "job.json").exists():
            job = Job(jd, None)
            st = job.status()
            for d in out["documents"]:
                info = st["documents"].get(d["key"], {})
                d.update(stage=info.get("stage", "queued"), blocks=info.get("blocks", 0),
                         open_flags=info.get("open_flags", {}))
            out["cost_by_agent"] = st["cost"]
            # files appear only after the release passed verification (never a half-built release)
            out["files"] = _released_files(jd) if out["status"] == "released" else []
        return out

    @app.get("/api/jobs/{job_id}/events")
    async def events(job_id: str, request: Request, u: User = Depends(current_user)):
        """Server-sent events: pipeline progress (from the job's audit log) and status changes."""
        with Session() as s:
            _job_for(s, job_id, u)
        audit = runner.job_dir(cfg, job_id) / "audit.jsonl"

        async def stream():
            offset, last_event, last_status = 0, 0, None
            while not await request.is_disconnected():
                if audit.exists():
                    with open(audit, "r", encoding="utf-8") as f:
                        f.seek(offset)
                        chunk = f.read()
                        offset = f.tell()
                    for line in chunk.splitlines():
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        yield _sse("progress", {k: v for k, v in rec.items() if k in PUBLIC_EVENT_KEYS})
                with Session() as s:
                    evs = s.scalars(select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.id > last_event)
                                    .order_by(JobEvent.id)).all()
                    for e in evs:
                        last_event = e.id
                        yield _sse("status", {"kind": e.kind, **e.data, "at": e.at.isoformat()})
                        last_status = e.data.get("status", last_status)
                if last_status in ("released", "failed"):
                    yield _sse("end", {"status": last_status})
                    return
                yield ": keep-alive\n\n"
                await asyncio.sleep(1.0)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/jobs/{job_id}/glossary")
    def get_glossary(job_id: str, u: User = Depends(current_user)):
        with Session() as s:
            _job_for(s, job_id, u)
        jd = runner.job_dir(cfg, job_id)
        for name in ("glossary.json", "glossary.proposed.json"):
            if (jd / name).exists():
                return {"confirmed": name == "glossary.json", "items": json.loads((jd / name).read_text("utf-8"))}
        return {"confirmed": False, "items": []}



    @app.post("/api/jobs/{job_id}/glossary/confirm")
    def confirm_glossary(job_id: str, body: GlossaryIn, u: User = Depends(current_user), _=Depends(csrf)):
        with Session() as s:
            row = _job_for(s, job_id, u)
            if row.status != "waiting_glossary":
                raise HTTPException(409, f"job is {row.status}, not waiting for the glossary")
            row.status = "queued"
            s.add(JobEvent(job_id=job_id, kind="glossary_confirmed", data={"by": u.username, "items": len(body.items)}))
            s.commit()
        items = [{"source": i.source.strip(), "target": i.target.strip(),
                  "kind": i.kind if i.kind in ("name", "acronym", "term", "organisation", "place") else "term",
                  "confirmed": True} for i in body.items if i.source.strip() and i.target.strip()]
        runner.submit(job_id, {"by": u.username, "glossary": items})
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/documents/{doc_key}")
    def document_model(job_id: str, doc_key: str, u: User = Depends(current_user)):
        """Translated model for review (read-only in Phase 3; the side-by-side editor comes in Phase 4)."""
        with Session() as s:
            _job_for(s, job_id, u)
        if not re.fullmatch(r"d\d{2}", doc_key):
            raise HTTPException(404, "no such document")
        docs = runner.job_dir(cfg, job_id) / "docs"
        for stage in ("reviewed", "formatted", "qa", "proofread", "translated", "intake"):
            p = docs / f"{doc_key}.{stage}.json"
            if p.exists():
                return {"stage": stage, "model": json.loads(p.read_text("utf-8"))}
        raise HTTPException(404, "document not processed yet")


    @app.post("/api/jobs/{job_id}/approve")
    def approve(job_id: str, body: ApproveIn, u: User = Depends(current_user), _=Depends(csrf)):
        with Session() as s:
            row = _job_for(s, job_id, u)
            if row.status != "waiting_review":
                raise HTTPException(409, f"job is {row.status}, not waiting for review")
            signer = s.get(User, row.created_by)
            if u.role != "admin" and (u.role != "certified_translator" or u.id != signer.id):
                raise HTTPException(403, "only the signing certified translator (or an admin) can approve")
            row.status, row.approved_by = "queued", u.id
            s.add(JobEvent(job_id=job_id, kind="approved", data={"by": u.username}))
            s.commit()
        runner.submit(job_id, {"approved_by": u.username, "note": body.note})
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: str, u: User = Depends(current_user), _=Depends(csrf)):
        with Session() as s:
            row = _job_for(s, job_id, u)
            if row.status != "failed":
                raise HTTPException(409, "only failed jobs can be retried")
            row.status = "queued"
            s.commit()
        runner.submit(job_id)
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/files/{name}")
    def download(job_id: str, name: str, u: User = Depends(current_user)):
        with Session() as s:
            _job_for(s, job_id, u)
        with Session() as s:
            if s.get(JobRow, job_id).status != "released":
                raise HTTPException(409, "the release is not finished")
        rel = runner.job_dir(cfg, job_id) / "release"
        p = (rel / name).resolve()
        if rel.resolve() not in p.parents or not p.is_file():
            raise HTTPException(404, "file not found")
        return FileResponse(p, filename=p.name)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    # ----------------------------------------------------------- frontend

    if cfg.static_dir.exists():
        app.mount("/assets", StaticFiles(directory=cfg.static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = (cfg.static_dir / path).resolve()
            if path and f.is_file() and cfg.static_dir.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(cfg.static_dir / "index.html")

    return app


# ------------------------------------------------------------------ helpers

def _safe(name: str) -> str:
    return re.sub(r"[^\w.\- ]+", "_", name, flags=re.UNICODE)[:120]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "name": u.name, "role": u.role, "ui_language": u.ui_language}


def _may_see(row: JobRow, u: User) -> bool:
    return u.role == "admin" or row.created_by == u.id or row.approved_by == u.id


def _job_out(r: JobRow, brief: bool = False) -> dict:
    out = {"id": r.id, "title": r.title, "created_at": r.created_at.isoformat(), "status": r.status,
           "stage": r.stage, "source_language": r.source_language, "target_language": r.target_language,
           "stamp": r.stamp, "cost_usd": r.cost_usd, "error": r.error, "documents_count": len(r.documents)}
    if not brief:
        out.update(page_order=r.page_order, document_type=r.document_type, notes=r.notes,
                   approved_at=r.approved_at.isoformat() if r.approved_at else None,
                   documents=[{"key": d.doc_key, "title": d.title, "filename": d.filename,
                               "source_language": d.source_language, "target_language": d.target_language}
                              for d in r.documents])
    return out


def _released_files(jd: Path) -> list[dict]:
    rel = jd / "release"
    if not rel.exists():
        return []
    return [{"name": p.name, "size": p.stat().st_size, "kind": p.suffix.lstrip(".")}
            for p in sorted(rel.iterdir()) if p.is_file() and p.suffix in (".docx", ".pdf", ".zip", ".txt")]
