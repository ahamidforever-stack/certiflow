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
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from .. import review as rv
from ..assets import AssetError, AssetLibrary
from ..model import JobSpec, PageOrder, StampChoice
from ..profiles import all_profiles, get_profile
from . import runner
from .auth import COOKIE, hash_password, make_token, read_token, verify_dummy, verify_password
from .config import WebConfig, get_config, set_config
from .db import Job as JobRow
from .db import (ROLES, AdminEvent, ClientTerm, JobDocument, JobEvent, LoginAttempt, User, UserSession, aware, revoke_sessions,
                 client_key, session_factory, user_by_username, utcnow)

SOURCE_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".docx", ".doc", ".odt", ".rtf"}
CONVERT_EXT = {".docx", ".doc", ".odt", ".rtf"}
PUBLIC_EVENT_KEYS = {"kind", "at", "agent", "stage", "document", "model", "cost_usd", "latency_s", "retries",
                     "blocks", "changes", "qa_loops", "open_blockers", "loop", "items", "by", "docx", "pdf",
                     "stamp_choice", "error", "block", "field", "action", "index"}   # never "instruction" (may quote text)
# audit view: the progress fields plus model details; never prompts, responses or instructions (document text)
AUDIT_KEYS = PUBLIC_EVENT_KEYS | {"prompt_version", "effort", "usage", "note", "status"}
REVIEW_STAGES = ("reviewed", "formatted")
_review_lock = threading.Lock()   # one review write at a time (thread runner; Celery workers never write review files)


# ------------------------------------------------------------------ request models


class LoginIn(BaseModel):
    username: str
    password: str


USERNAME = re.compile(r"[a-z0-9._-]{2,80}")


class UserCreateIn(BaseModel):
    username: str
    name: str
    role: str
    password: str


class UserUpdateIn(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None


class AssetUpdateIn(BaseModel):
    active: Optional[bool] = None
    name: Optional[str] = None
    width_mm: Optional[float] = None


class TermIn(BaseModel):
    target: str
    kind: str = "term"


class AgentSettingsIn(BaseModel):
    model: str
    effort: str
    prompt_version: str
    max_tokens: int


class KeepIn(BaseModel):
    keep: bool


class PasswordIn(BaseModel):
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


class CellEditIn(BaseModel):
    row: int
    col: int
    text: str


class BlockEditIn(BaseModel):
    text: Optional[str] = None
    cells: Optional[list[CellEditIn]] = None
    reason: str = ""


class ResolveIn(BaseModel):
    comment: str = ""


class RerunIn(BaseModel):
    agent: str
    blocks: list[str]
    instruction: str = ""


def create_app(cfg: WebConfig | None = None) -> FastAPI:
    cfg = cfg or get_config()
    set_config(cfg)
    Session = session_factory(cfg.database_url)
    app = FastAPI(title="CertiFlow", docs_url="/api/docs", openapi_url="/api/openapi.json")
    if cfg.scheduler:
        from .storage import start_scheduler
        start_scheduler(cfg, Session, AUDIT_KEYS)

    def library() -> AssetLibrary:
        return AssetLibrary(cfg.library)

    # ------------------------------------------------------------------ auth

    def _session(request: Request) -> tuple[User, UserSession]:
        tok = request.cookies.get(COOKIE)
        got = read_token(tok, cfg.secret_key) if tok else None
        if got is None:
            raise HTTPException(401, "not signed in")
        uid, sid = got
        with Session() as s:
            row = s.get(UserSession, sid)
            now = utcnow()
            if (row is None or row.user_id != uid or row.revoked_at is not None or aware(row.expires_at) <= now):
                raise HTTPException(401, "not signed in")
            u = s.get(User, uid)
            if u is None or not u.active:
                raise HTTPException(401, "not signed in")
            if now - aware(row.last_seen_at) > timedelta(minutes=1):   # throttled write
                row.last_seen_at = now
                s.commit()
            return u, row

    def current_user(request: Request) -> User:
        return _session(request)[0]

    def csrf(request: Request) -> None:
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-certiflow") != "1":
            raise HTTPException(403, "missing X-CertiFlow header")

    def _client_ip(request: Request) -> str:
        return (request.client.host if request.client else "")[:64]

    def _user_failures(s, username: str) -> int:
        """Failed sign-ins for this username in the lock window, counted after its last success."""
        since = utcnow() - timedelta(minutes=cfg.login_lock_minutes)
        last_ok = s.scalar(select(func.max(LoginAttempt.at)).where(LoginAttempt.username == username,
                                                                   LoginAttempt.ok.is_(True)))
        start = max(since, aware(last_ok)) if last_ok else since
        return s.scalar(select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.username == username, LoginAttempt.ok.is_(False), LoginAttempt.at > start))

    def _locked(s, username: str, ip: str) -> bool:
        """Too many recent failures for this username (since its last success) or from this address."""
        since = utcnow() - timedelta(minutes=cfg.login_lock_minutes)
        by_ip = s.scalar(select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.ip == ip, LoginAttempt.ok.is_(False), LoginAttempt.at > since))
        return _user_failures(s, username) >= cfg.login_max_failures or by_ip >= cfg.login_ip_max_failures

    @app.post("/api/auth/login")
    def login(body: LoginIn, request: Request, response: Response, _=Depends(csrf)):
        username, ip = body.username.strip().lower()[:80], _client_ip(request)
        with Session() as s:
            s.execute(delete(LoginAttempt).where(LoginAttempt.at < utcnow() - timedelta(days=30)))
            s.execute(delete(UserSession).where(UserSession.expires_at < utcnow() - timedelta(days=30)))
            if _locked(s, username, ip):
                s.commit()
                raise HTTPException(429, "too many failed sign-ins; try again later",
                                    headers={"Retry-After": str(cfg.login_lock_minutes * 60)})
            u = user_by_username(s, username)
            if u is None:
                verify_dummy(body.password)
            ok = u is not None and u.active and verify_password(body.password, u.password_hash)
            s.add(LoginAttempt(username=username, ip=ip, ok=ok))
            if not ok:
                s.commit()
                raise HTTPException(401, "wrong username or password")
            sess = UserSession(id=secrets.token_hex(24), user_id=u.id, ip=ip,
                               user_agent=(request.headers.get("user-agent") or "")[:200],
                               expires_at=utcnow() + timedelta(hours=cfg.session_hours))
            s.add(sess)
            s.commit()
            response.set_cookie(COOKIE, make_token(u.id, sess.id, cfg.secret_key, cfg.session_hours), httponly=True,
                                samesite="strict", secure=cfg.secure_cookies, max_age=cfg.session_hours * 3600)
            return _user_out(u)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, _=Depends(csrf)):
        got = read_token(request.cookies.get(COOKIE) or "", cfg.secret_key)
        if got:
            with Session() as s:
                row = s.get(UserSession, got[1])
                if row is not None and row.user_id == got[0] and row.revoked_at is None:
                    row.revoked_at = utcnow()
                    s.commit()
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me/sessions")
    def my_sessions(request: Request):
        u, cur = _session(request)
        with Session() as s:
            rows = s.scalars(select(UserSession).where(UserSession.user_id == u.id, UserSession.revoked_at.is_(None),
                                                       UserSession.expires_at > utcnow())
                             .order_by(UserSession.last_seen_at.desc())).all()
            return [{"id": r.id[:8], "created_at": _iso(r.created_at), "last_seen_at": _iso(r.last_seen_at),
                     "ip": r.ip, "user_agent": r.user_agent, "current": r.id == cur.id} for r in rows]

    @app.post("/api/me/sessions/revoke-others")
    def revoke_others(request: Request, _=Depends(csrf)):
        u, cur = _session(request)
        with Session() as s:
            n = revoke_sessions(s, u.id, keep=cur.id)
            s.commit()
        return {"revoked": n}

    # ------------------------------------------------------------------ admin: users

    def admin_user(u: User = Depends(current_user)) -> User:
        if u.role != "admin":
            raise HTTPException(403, "administrators only")
        return u

    def _admin_out(s, r: User) -> dict:
        last = s.scalar(select(func.max(LoginAttempt.at)).where(LoginAttempt.username == r.username,
                                                                LoginAttempt.ok.is_(True)))
        devices = s.scalar(select(func.count()).select_from(UserSession).where(
            UserSession.user_id == r.id, UserSession.revoked_at.is_(None), UserSession.expires_at > utcnow()))
        try:
            library().stamp_for(StampChoice.certified, r.username)
            stamp = True
        except AssetError:
            stamp = False
        return {**_user_out(r), "active": r.active, "created_at": _iso(r.created_at),
                "last_login_at": _iso(last) if last else None, "devices": devices,
                "locked": _user_failures(s, r.username) >= cfg.login_max_failures, "certified_stamp": stamp}

    def _sync_lib_user(r: User) -> None:
        """Stamp rights are checked against the library's user list; keep names and roles in step."""
        from . import assets_admin as aa
        try:
            aa.sync_user(cfg.library, r.username, r.name, r.role)
        except Exception:  # noqa: BLE001 - the account change itself has succeeded
            pass

    def _log(s, actor: User, action: str, target: str, **data) -> None:
        s.add(AdminEvent(actor=actor.username, action=action, target=target, data=data))

    def _target(s, user_id: int) -> User:
        r = s.get(User, user_id)
        if r is None:
            raise HTTPException(404, "no such user")
        return r

    def _check_password(pw: str) -> None:
        if len(pw) < 10:
            raise HTTPException(422, "the password needs at least 10 characters")

    def _keeps_an_admin(s, r: User, role: str, active: bool) -> None:
        """Refuse a change that would leave no active administrator."""
        if r.role == "admin" and r.active and (role != "admin" or not active):
            others = s.scalar(select(func.count()).select_from(User).where(
                User.role == "admin", User.active.is_(True), User.id != r.id))
            if not others:
                raise HTTPException(409, "this is the last active administrator")

    @app.get("/api/admin/users")
    def admin_users(_: User = Depends(admin_user)):
        with Session() as s:
            return [_admin_out(s, r) for r in s.scalars(select(User).order_by(User.active.desc(), User.name))]

    @app.post("/api/admin/users", status_code=201)
    def admin_create_user(body: UserCreateIn, a: User = Depends(admin_user), _=Depends(csrf)):
        username = body.username.strip().lower()
        if not USERNAME.fullmatch(username):
            raise HTTPException(422, "username: 2-80 characters, letters a-z, digits, dot, dash or underscore")
        if body.role not in ROLES:
            raise HTTPException(422, "unknown role")
        if not body.name.strip():
            raise HTTPException(422, "name is required")
        _check_password(body.password)
        with Session() as s:
            if user_by_username(s, username):
                raise HTTPException(409, "this username exists")
            r = User(username=username, name=body.name.strip()[:200], role=body.role,
                     password_hash=hash_password(body.password))
            s.add(r)
            _log(s, a, "user_created", username, role=body.role)
            s.commit()
            _sync_lib_user(r)
            return _admin_out(s, r)

    @app.patch("/api/admin/users/{user_id}")
    def admin_update_user(user_id: int, body: UserUpdateIn, a: User = Depends(admin_user), _=Depends(csrf)):
        with Session() as s:
            r = _target(s, user_id)
            role = body.role if body.role is not None else r.role
            active = body.active if body.active is not None else r.active
            if role not in ROLES:
                raise HTTPException(422, "unknown role")
            if r.id == a.id and (role != r.role or not active):
                raise HTTPException(409, "you cannot change your own role or deactivate yourself")
            _keeps_an_admin(s, r, role, active)
            changed = {}
            if body.name is not None and body.name.strip() and body.name.strip() != r.name:
                r.name, changed["name"] = body.name.strip()[:200], True
            if role != r.role:
                changed["role"] = [r.role, role]
                r.role = role
            if active != r.active:
                changed["active"] = active
                r.active = active
                if not active:
                    revoke_sessions(s, r.id)
            if changed:
                _log(s, a, "user_updated", r.username, **changed)
            s.commit()
            if "name" in changed or "role" in changed:
                _sync_lib_user(r)
            return _admin_out(s, r)

    @app.post("/api/admin/users/{user_id}/password")
    def admin_reset_password(user_id: int, body: PasswordIn, a: User = Depends(admin_user), _=Depends(csrf)):
        _check_password(body.password)
        with Session() as s:
            r = _target(s, user_id)
            r.password_hash = hash_password(body.password)
            n = revoke_sessions(s, r.id, keep=None)
            _log(s, a, "password_reset", r.username, signed_out=n)
            s.commit()
            return _admin_out(s, r)

    @app.post("/api/admin/users/{user_id}/unlock")
    def admin_unlock(user_id: int, a: User = Depends(admin_user), _=Depends(csrf)):
        with Session() as s:
            r = _target(s, user_id)
            s.execute(delete(LoginAttempt).where(LoginAttempt.username == r.username, LoginAttempt.ok.is_(False)))
            _log(s, a, "user_unlocked", r.username)
            s.commit()
            return _admin_out(s, r)

    @app.post("/api/admin/users/{user_id}/sessions/revoke")
    def admin_revoke_sessions(user_id: int, request: Request, a: User = Depends(admin_user), _=Depends(csrf)):
        cur = _session(request)[1]
        with Session() as s:
            r = _target(s, user_id)
            n = revoke_sessions(s, r.id, keep=cur.id if r.id == a.id else None)   # never the admin's own browser
            _log(s, a, "signed_out", r.username, sessions=n)
            s.commit()
            return _admin_out(s, r)

    # ------------------------------------------------------------------ admin: asset library

    @app.get("/api/admin/assets")
    def admin_assets(_: User = Depends(admin_user)):
        from . import assets_admin as aa
        out = aa.listing(cfg.library)
        with Session() as s:
            accounts = {u.username: u for u in s.scalars(select(User))}
        out["accounts"] = [{"username": u.username, "name": u.name, "role": u.role} for u in accounts.values()
                           if u.active and u.role == "certified_translator"]
        return out

    @app.get("/api/admin/assets/{asset_id}/file")
    def admin_asset_file(asset_id: str, _: User = Depends(admin_user)):
        lib = library()
        a = next((x for x in lib.lib.assets if x.id == asset_id), None)
        if a is None or not lib.path(a).is_file():
            raise HTTPException(404, "no such asset")
        p = lib.path(a)
        if a.type == "template":
            return FileResponse(p, filename=p.name, headers={"Cache-Control": "private, no-store"},
                                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        return FileResponse(p, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    def _asset_error(e: Exception):
        from . import assets_admin as aa
        if isinstance(e, KeyError):
            raise HTTPException(404, "no such asset")
        if isinstance(e, aa.AssetAdminError):
            raise HTTPException(409 if "read-only" in str(e) else 422, str(e))
        raise e

    @app.post("/api/admin/assets/image", status_code=201)
    async def admin_add_image(kind: str = Form(...), file: UploadFile = File(...), owner: Optional[str] = Form(None),
                              width_mm: Optional[float] = Form(None), name: Optional[str] = Form(None),
                              a: User = Depends(admin_user), _=Depends(csrf)):
        from . import assets_admin as aa
        data = await file.read(aa.MAX_BYTES + 1)
        owner_name = None
        if owner:
            with Session() as s:
                acc = user_by_username(s, owner)
                if acc is None or acc.role != "certified_translator" or not acc.active:
                    raise HTTPException(422, "the owner must be an active certified translator")
                owner_name = acc.name
            aa.sync_user(cfg.library, acc.username, acc.name, acc.role)
        try:
            asset = await asyncio.to_thread(aa.add_image, cfg.library, kind, data, owner=owner,
                                            owner_name=owner_name, width_mm=width_mm, name=name)
        except Exception as e:  # noqa: BLE001
            _asset_error(e)
        with Session() as s:
            _log(s, a, "asset_added", asset.id, type=kind, owner=owner)
            s.commit()
        return aa.asset_out(library(), asset)

    @app.post("/api/admin/assets/template", status_code=201)
    async def admin_add_template(file: UploadFile = File(...), name: Optional[str] = Form(None),
                                 language: Optional[str] = Form(None), pair: Optional[str] = Form(None),
                                 reference_docx: Optional[UploadFile] = File(None),
                                 reference_pdf: Optional[UploadFile] = File(None),
                                 a: User = Depends(admin_user), _=Depends(csrf)):
        from . import assets_admin as aa
        langs = {p.code for p in all_profiles()}
        if language and language not in langs:
            raise HTTPException(422, "unknown language")
        if pair and (pair.count(">") != 1 or any(x not in langs for x in pair.split(">"))):
            raise HTTPException(422, "pair must look like en>ar")
        data = await file.read(aa.MAX_BYTES + 1)
        ref_docx = await reference_docx.read(aa.MAX_BYTES + 1) if reference_docx and reference_docx.filename else None
        ref_pdf = await reference_pdf.read(aa.MAX_BYTES + 1) if reference_pdf and reference_pdf.filename else None
        try:
            asset = await asyncio.to_thread(aa.add_template, cfg.library, data, name=name, language=language, pair=pair,
                                            reference_docx=ref_docx, reference_pdf=ref_pdf)
        except Exception as e:  # noqa: BLE001
            _asset_error(e)
        with Session() as s:
            _log(s, a, "asset_added", asset.id, type="template", reference=bool(ref_docx or ref_pdf))
            s.commit()
        return aa.asset_out(library(), asset)

    @app.patch("/api/admin/assets/{asset_id}")
    def admin_update_asset(asset_id: str, body: AssetUpdateIn, a: User = Depends(admin_user), _=Depends(csrf)):
        from . import assets_admin as aa
        try:
            asset, changed = aa.update(cfg.library, asset_id, active=body.active, name=body.name,
                                       width_mm=body.width_mm)
        except Exception as e:  # noqa: BLE001
            _asset_error(e)
        if changed:
            with Session() as s:
                _log(s, a, "asset_updated", asset.id, **changed)
                s.commit()
        return aa.asset_out(library(), asset)

    # ------------------------------------------------------------------ admin: model settings

    def _settings_error(e: Exception):
        from . import settings_admin as sa
        if isinstance(e, KeyError):
            raise HTTPException(404, "no such agent")
        if isinstance(e, sa.SettingsError):
            raise HTTPException(422, str(e))
        raise e

    @app.get("/api/admin/settings")
    def admin_settings(_: User = Depends(admin_user)):
        from . import settings_admin as sa
        return sa.view()

    @app.put("/api/admin/settings/agents/{name}")
    def admin_set_agent(name: str, body: AgentSettingsIn, a: User = Depends(admin_user), _=Depends(csrf)):
        from . import settings_admin as sa
        try:
            changed = sa.set_agent(name, body.model, body.effort, body.prompt_version, body.max_tokens)
        except Exception as e:  # noqa: BLE001
            _settings_error(e)
        if changed:
            with Session() as s:
                _log(s, a, "settings_changed", name, **changed)
                s.commit()
        return sa.view()

    @app.delete("/api/admin/settings/agents/{name}")
    def admin_reset_agent(name: str, a: User = Depends(admin_user), _=Depends(csrf)):
        from . import settings_admin as sa
        try:
            sa.reset_agent(name)
        except Exception as e:  # noqa: BLE001
            _settings_error(e)
        with Session() as s:
            _log(s, a, "settings_reset", name)
            s.commit()
        return sa.view()

    @app.put("/api/admin/settings/pipeline")
    def admin_set_pipeline(body: dict[str, int], a: User = Depends(admin_user), _=Depends(csrf)):
        from . import settings_admin as sa
        try:
            changed = sa.set_pipeline(body)
        except Exception as e:  # noqa: BLE001
            _settings_error(e)
        if changed:
            with Session() as s:
                _log(s, a, "settings_changed", "pipeline", **changed)
                s.commit()
        return sa.view()

    # ------------------------------------------------------------------ admin: languages and pairs

    def _lang_error(e: Exception):
        from . import languages_admin as la
        if isinstance(e, KeyError):
            raise HTTPException(404, "no such language")
        if isinstance(e, (la.LanguageError, ValueError)):
            raise HTTPException(422, str(e).splitlines()[0][:300])
        raise e

    def _templates() -> list[dict]:
        return [{"id": a.id, "name": a.name, "language": a.language, "pair": a.pair}
                for a in library().lib.assets if a.type == "template" and a.active]

    @app.get("/api/admin/languages")
    def admin_languages(_: User = Depends(admin_user)):
        from . import languages_admin as la
        return {**la.view(), "templates": _templates()}

    @app.put("/api/admin/languages/{code}")
    def admin_set_language(code: str, body: dict, a: User = Depends(admin_user), _=Depends(csrf)):
        from . import languages_admin as la
        try:
            changed = la.set_profile(code, body)
        except Exception as e:  # noqa: BLE001
            _lang_error(e)
        if changed:
            with Session() as s:
                _log(s, a, "language_changed", code, **changed)
                s.commit()
        return {**la.view(), "templates": _templates()}

    @app.delete("/api/admin/languages/{code}")
    def admin_reset_language(code: str, a: User = Depends(admin_user), _=Depends(csrf)):
        from . import languages_admin as la
        la.reset_profile(code)
        with Session() as s:
            _log(s, a, "language_reset", code)
            s.commit()
        return {**la.view(), "templates": _templates()}

    @app.put("/api/admin/pairs/{source}/{target}")
    def admin_set_pair(source: str, target: str, body: dict, a: User = Depends(admin_user), _=Depends(csrf)):
        from . import languages_admin as la
        try:
            la.set_pair(source, target, body, {t["id"] for t in _templates()})
        except Exception as e:  # noqa: BLE001
            _lang_error(e)
        with Session() as s:
            _log(s, a, "pair_changed", f"{source}>{target}")
            s.commit()
        return {**la.view(), "templates": _templates()}

    @app.delete("/api/admin/pairs/{source}/{target}")
    def admin_reset_pair(source: str, target: str, a: User = Depends(admin_user), _=Depends(csrf)):
        from . import languages_admin as la
        la.reset_pair(source, target)
        with Session() as s:
            _log(s, a, "pair_reset", f"{source}>{target}")
            s.commit()
        return {**la.view(), "templates": _templates()}

    # ------------------------------------------------------------------ admin: storage, retention, backups

    def _storage_error(e: Exception):
        from . import storage as stg
        if isinstance(e, stg.StorageError):
            raise HTTPException(422 if "already running" not in str(e) else 409, str(e))
        raise e

    def _storage_view() -> dict:
        from . import storage as stg
        with Session() as s:
            return {"settings": stg.load_settings(cfg), "usage": stg.usage(cfg, s), "candidates": stg.candidates(s, cfg),
                    "backups": stg.list_backups(cfg), "backup_state": stg.state(),
                    "backup_encrypted": stg.backup_key() is not None, "backup_dir": str(stg.backup_dir(cfg))}

    @app.get("/api/admin/storage")
    def admin_storage(_: User = Depends(admin_user)):
        return _storage_view()

    @app.put("/api/admin/storage/settings")
    def admin_storage_settings(body: dict, a: User = Depends(admin_user), _=Depends(csrf)):
        from . import storage as stg
        try:
            _new, changed = stg.save_settings(cfg, body)
        except Exception as e:  # noqa: BLE001
            _storage_error(e)
        if changed:
            with Session() as s:
                _log(s, a, "storage_changed", "storage", **changed)
                s.commit()
        return _storage_view()

    @app.post("/api/admin/storage/retention/run")
    def admin_run_retention(a: User = Depends(admin_user), _=Depends(csrf)):
        from . import storage as stg
        with Session() as s:
            res = stg.run_retention(s, cfg, AUDIT_KEYS, by=a.username)
            if res["purged"]:
                _log(s, a, "retention_run", "storage", jobs=len(res["purged"]))
            s.commit()
        return {**_storage_view(), "result": res}

    @app.post("/api/admin/storage/backups", status_code=202)
    def admin_create_backup(a: User = Depends(admin_user), _=Depends(csrf)):
        from . import storage as stg
        if stg.state()["running"]:
            raise HTTPException(409, "a backup is already running")
        st = stg.load_settings(cfg)

        def work():
            try:
                stg.create_backup(cfg, include_jobs=st["backup_jobs"])
            except Exception:  # noqa: BLE001 - shown as backup_state.last_error
                pass
        threading.Thread(target=work, name="certiflow-backup", daemon=True).start()
        with Session() as s:
            _log(s, a, "backup_started", "storage")
            s.commit()
        return {"started": True}

    @app.put("/api/jobs/{job_id}/keep")
    def set_keep(job_id: str, body: KeepIn, a: User = Depends(admin_user), _=Depends(csrf)):
        with Session() as s:
            row = s.get(JobRow, job_id)
            if row is None:
                raise HTTPException(404, "no such job")
            row.keep = body.keep
            _log(s, a, "job_hold" if body.keep else "job_release_hold", job_id)
            s.commit()
            return _job_out(row)

    @app.get("/api/admin/usage")
    def admin_usage(days: int = 30, _: User = Depends(admin_user)):
        from .usage import summary
        if days not in (7, 30, 90, 365):
            raise HTTPException(422, "days must be 7, 30, 90 or 365")
        with Session() as s:
            return summary(s, days, cfg.timezone)

    @app.get("/api/admin/events")
    def admin_events(_: User = Depends(admin_user)):
        with Session() as s:
            rows = s.scalars(select(AdminEvent).order_by(AdminEvent.at.desc()).limit(200))
            return [{"at": _iso(e.at), "actor": e.actor, "action": e.action, "target": e.target, "data": e.data}
                    for e in rows]

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
        client: Optional[str] = Form(None),
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
        client = " ".join((client or "").split())[:200] or None
        if client:
            # snapshot of the client's glossary memory; the pipeline picks the terms that occur in the batch
            with Session() as s:
                terms = s.scalars(select(ClientTerm).where(ClientTerm.client_key == client_key(client),
                                                           ClientTerm.target_language.in_({b for _a, b, _n in docs_meta})))
                mem = [{"source_language": t.source_language, "target_language": t.target_language, "source": t.source,
                        "target": t.target, "kind": t.kind} for t in terms]
            if mem:
                (jd / "glossary.memory.json").write_text(json.dumps(mem, ensure_ascii=False, indent=1), "utf-8")
        with Session() as s:
            row = JobRow(id=job_id, created_by=u.id, title=titles[0] + (f" +{len(titles) - 1}" if len(titles) > 1 else ""),
                         source_language=source_language, target_language=target_language, stamp=stamp,
                         page_order=page_order, document_type=document_type, notes=notes, status="queued",
                         client=client)
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
        mem = jd / "glossary.memory.json"
        remembered = {(m["source"], m["target"]) for m in json.loads(mem.read_text("utf-8"))} if mem.exists() else set()
        for name in ("glossary.json", "glossary.proposed.json"):
            if (jd / name).exists():
                items = json.loads((jd / name).read_text("utf-8"))
                for i in items:
                    i["remembered"] = (i.get("source"), i.get("target")) in remembered
                return {"confirmed": name == "glossary.json", "items": items}
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
        _remember_terms(job_id, items, u.username)
        runner.submit(job_id, {"by": u.username, "glossary": items})
        return {"ok": True}

    def _remember_terms(job_id: str, items: list[dict], by: str) -> None:
        """Save a confirmed glossary in the client's memory (newest confirmation wins)."""
        with Session() as s:
            row = s.get(JobRow, job_id)
            if not row or not row.client or not items:
                return
            src = row.source_language
            intake = runner.job_dir(cfg, job_id) / "docs" / "d01.intake.json"
            if intake.exists():                           # the language Intake detected (the job may say "auto")
                src = json.loads(intake.read_text("utf-8")).get("source_language", src)
            if src == "auto":
                return
            key, tgt = client_key(row.client), row.target_language
            have = {t.source: t for t in s.scalars(select(ClientTerm).where(
                ClientTerm.client_key == key, ClientTerm.source_language == src, ClientTerm.target_language == tgt))}
            for i in items:
                source, target = i["source"][:500], i["target"][:500]
                t = have.get(source)
                if t is None:
                    t = ClientTerm(client_key=key, client=row.client, source_language=src, target_language=tgt,
                                   source=source, target=target, kind=i["kind"], updated_by=by, job_id=job_id, uses=1)
                    s.add(t)
                    have[source] = t
                else:
                    t.uses += 1
                    if (t.target, t.kind) != (target, i["kind"]):
                        t.target, t.kind = target, i["kind"]
                    t.client, t.updated_at, t.updated_by, t.job_id = row.client, utcnow(), by, job_id
            s.commit()

    # ------------------------------------------------------------------ glossary memory per client

    def translator_or_admin(u: User = Depends(current_user)) -> User:
        if u.role not in ("admin", "certified_translator"):
            raise HTTPException(403, "certified translators and admins only")
        return u

    @app.get("/api/clients")
    def clients(u: User = Depends(current_user)):
        """Client names for the New job suggestions: from the glossary memory and the user's own jobs."""
        by_key: dict[str, str] = {}
        with Session() as s:       # one spelling per client: the one used most recently
            q = select(JobRow.client).where(JobRow.client.is_not(None)).order_by(JobRow.created_at.desc())
            if u.role != "admin":
                q = q.where(JobRow.created_by == u.id)
            for n in s.scalars(q.limit(5000)):
                by_key.setdefault(client_key(n), n)
            for n in s.scalars(select(ClientTerm.client).order_by(ClientTerm.updated_at.desc())):
                by_key.setdefault(client_key(n), n)
        return sorted(by_key.values(), key=str.casefold)

    @app.get("/api/glossary-memory")
    def memory_overview(_: User = Depends(translator_or_admin)):
        with Session() as s:
            rows = s.execute(select(ClientTerm.client_key, ClientTerm.source_language, ClientTerm.target_language,
                                    func.count(), func.max(ClientTerm.updated_at), func.max(ClientTerm.client))
                             .group_by(ClientTerm.client_key, ClientTerm.source_language, ClientTerm.target_language)).all()
        out: dict[str, dict] = {}
        for key, a, b, n, last, name in rows:
            c = out.setdefault(key, {"client": name, "terms": 0, "pairs": [], "updated_at": None})
            c["terms"] += n
            c["pairs"].append({"source": a, "target": b, "terms": n})
            c["updated_at"] = max(filter(None, [c["updated_at"], _iso(last)]))
        return sorted(out.values(), key=lambda c: c["client"].casefold())

    @app.get("/api/glossary-memory/terms")
    def memory_terms(client: str, source: Optional[str] = None, target: Optional[str] = None,
                     _: User = Depends(translator_or_admin)):
        with Session() as s:
            q = select(ClientTerm).where(ClientTerm.client_key == client_key(client))
            if source:
                q = q.where(ClientTerm.source_language == source)
            if target:
                q = q.where(ClientTerm.target_language == target)
            return [_term_out(t) for t in s.scalars(q.order_by(ClientTerm.source))]

    @app.put("/api/glossary-memory/terms/{term_id}")
    def memory_update(term_id: int, body: TermIn, u: User = Depends(translator_or_admin), _=Depends(csrf)):
        target = body.target.strip()[:500]
        if not target:
            raise HTTPException(422, "the translation cannot be empty")
        if body.kind not in ("name", "acronym", "term", "organisation", "place"):
            raise HTTPException(422, "unknown kind")
        with Session() as s:
            t = s.get(ClientTerm, term_id)
            if t is None:
                raise HTTPException(404, "no such term")
            t.target, t.kind, t.updated_at, t.updated_by = target, body.kind, utcnow(), u.username
            s.commit()
            return _term_out(t)

    @app.delete("/api/glossary-memory/terms/{term_id}")
    def memory_delete(term_id: int, _: User = Depends(translator_or_admin), __=Depends(csrf)):
        with Session() as s:
            t = s.get(ClientTerm, term_id)
            if t is None:
                raise HTTPException(404, "no such term")
            s.delete(t)
            s.commit()
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


    @app.get("/api/jobs/{job_id}/audit")
    def audit_log(job_id: str, u: User = Depends(current_user)):
        """Who did what and when: pipeline steps, model calls (model, prompt version, tokens, cost), review
        actions and status changes. Document text is never included."""
        with Session() as s:
            row = _job_for(s, job_id, u)
            creator = s.get(User, row.created_by)
            recs = [{"kind": "created", "at": _iso(row.created_at),
                     "by": creator.username if creator else None}]
            for e in s.scalars(select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.kind == "status")
                               .order_by(JobEvent.id)):
                recs.append({"kind": "status", "at": _iso(e.at), "status": e.data.get("status"),
                             "error": e.data.get("error")})
        audit = runner.job_dir(cfg, job_id) / "audit.jsonl"
        if audit.exists():
            for line in audit.read_text("utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                recs.append({k: v for k, v in rec.items() if k in AUDIT_KEYS})
        recs.sort(key=lambda r: r.get("at") or "")
        return {"records": recs[-3000:], "truncated": len(recs) > 3000}

    # ------------------------------------------------------------------ review (Phase 4)

    @app.get("/api/jobs/{job_id}/documents/{doc_key}/pages/{number}.png")
    def source_page(job_id: str, doc_key: str, number: int, u: User = Depends(current_user)):
        """One source page as an image, for the side-by-side editor (rendered once, then cached)."""
        from ..ocr import render_page
        from ..settings import load
        with Session() as s:
            _job_for(s, job_id, u)
        if not re.fullmatch(r"d\d{2}", doc_key):
            raise HTTPException(404, "no such document")
        jd = runner.job_dir(cfg, job_id)
        meta = json.loads((jd / "job.json").read_text("utf-8")) if (jd / "job.json").exists() else {"documents": []}
        d = next((x for x in meta["documents"] if x["id"] == doc_key), None)
        if d is None:
            raise HTTPException(404, "no such document")
        out = jd / "pages" / doc_key / f"{number}.png"
        if not out.exists():
            try:
                render_page(Path(d["source"]), number, load().pipeline.vision_dpi, out)
            except IndexError:
                raise HTTPException(404, "no such page")
        return FileResponse(out, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    def _review(job_id: str, doc_key: str, u: User, fn) -> dict:
        """Load the document under review, apply ``fn(doc)``, save it as ``<doc>.reviewed.json``.

        Only while the job waits for review. Audit records carry ids only, never text."""
        from ..model import Document
        with Session() as s:
            row = _job_for(s, job_id, u)
            if row.status != "waiting_review":
                raise HTTPException(409, f"job is {row.status}, not waiting for review")
        if not re.fullmatch(r"d\d{2}", doc_key):
            raise HTTPException(404, "no such document")
        docs = runner.job_dir(cfg, job_id) / "docs"
        with _review_lock:
            src = next((docs / f"{doc_key}.{st}.json" for st in REVIEW_STAGES
                        if (docs / f"{doc_key}.{st}.json").exists()), None)
            if src is None:
                raise HTTPException(404, "document not processed yet")
            doc = Document.model_validate_json(src.read_text("utf-8"))
            try:
                audit = fn(doc)
            except rv.ReviewConflict as e:
                raise HTTPException(409, str(e))
            except rv.ReviewError as e:
                raise HTTPException(422, str(e))
            tmp = docs / f"{doc_key}.reviewed.json.tmp"
            tmp.write_text(doc.model_dump_json(indent=1, exclude_defaults=True), "utf-8")
            tmp.replace(docs / f"{doc_key}.reviewed.json")
            if audit:
                from ..agents.base import AuditLog
                AuditLog(runner.job_dir(cfg, job_id) / "audit.jsonl").record(
                    {"at": datetime.now(timezone.utc).isoformat(), "job": job_id, "document": doc_key,
                     "by": u.username, **audit})
        return {"stage": "reviewed", "model": json.loads(doc.model_dump_json(exclude_defaults=True)),
                "open_blockers": rv.open_blockers(doc)}

    @app.put("/api/jobs/{job_id}/documents/{doc_key}/blocks/{block_id}")
    def edit_block(job_id: str, doc_key: str, block_id: str, body: BlockEditIn,
                   u: User = Depends(current_user), _=Depends(csrf)):
        def fn(doc):
            cells = [(c.row, c.col, c.text) for c in body.cells or []]
            added = rv.edit_block(doc, block_id, u.username, text=body.text, cells=cells, reason=body.reason)
            return {"kind": "review_edit", "block": block_id, "field": [h.field for h in added]} if added else None
        return _review(job_id, doc_key, u, fn)

    @app.post("/api/jobs/{job_id}/documents/{doc_key}/blocks/{block_id}/changes/{index}/{decision}")
    def decide_change(job_id: str, doc_key: str, block_id: str, index: int, decision: str,
                      u: User = Depends(current_user), _=Depends(csrf)):
        if decision not in ("accept", "reject"):
            raise HTTPException(404, "decision must be accept or reject")

        def fn(doc):
            rv.decide_change(doc, block_id, index, u.username, accept=decision == "accept")
            return {"kind": "review_change", "block": block_id, "index": index, "action": decision}
        return _review(job_id, doc_key, u, fn)

    @app.post("/api/jobs/{job_id}/documents/{doc_key}/blocks/{block_id}/flags/{index}/resolve")
    def resolve_flag(job_id: str, doc_key: str, block_id: str, index: int, body: ResolveIn,
                     u: User = Depends(current_user), _=Depends(csrf)):
        def fn(doc):
            rv.resolve_flag(doc, block_id, index, u.username, body.comment)
            return {"kind": "review_flag", "block": block_id, "index": index, "action": "resolve"}
        return _review(job_id, doc_key, u, fn)


    @app.post("/api/jobs/{job_id}/documents/{doc_key}/rerun", status_code=202)
    def rerun(job_id: str, doc_key: str, body: RerunIn, u: User = Depends(current_user), _=Depends(csrf)):
        """Run the translator, proofreader or QA again on selected blocks (with an optional instruction).

        Runs in the background; the job shows ``reworking`` and returns to ``waiting_review``."""
        from ..pipeline.job import RERUN_AGENTS
        if body.agent not in RERUN_AGENTS:
            raise HTTPException(422, f"agent must be one of {sorted(RERUN_AGENTS)}")
        if not body.blocks:
            raise HTTPException(422, "select at least one block")
        if len(body.instruction) > 2000:
            raise HTTPException(422, "instruction is too long (2000 characters at most)")
        if not re.fullmatch(r"d\d{2}", doc_key):
            raise HTTPException(404, "no such document")
        with Session() as s:
            row = _job_for(s, job_id, u)
            if row.status != "waiting_review":
                raise HTTPException(409, f"job is {row.status}, not waiting for review")
            if doc_key not in {d.doc_key for d in row.documents}:
                raise HTTPException(404, "no such document")
            row.status, row.error = "reworking", None
            s.add(JobEvent(job_id=job_id, kind="rerun", data={"by": u.username, "agent": body.agent,
                                                              "document": doc_key, "blocks": len(body.blocks)}))
            s.commit()
        runner.submit_rerun(job_id, doc_key, body.agent, body.blocks, body.instruction, u.username)
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/documents/{doc_key}/preview.pdf")
    def preview(job_id: str, doc_key: str, u: User = Depends(current_user)):
        """Watermarked PDF with the chosen stamp, before approval (built on demand, cached until the next edit)."""
        from ..builder.pdf_builder import BuildError
        from ..pipeline.job import Job
        with Session() as s:
            row = _job_for(s, job_id, u)
            if row.status != "waiting_review":
                raise HTTPException(409, f"job is {row.status}, not waiting for review")
        if not re.fullmatch(r"d\d{2}", doc_key):
            raise HTTPException(404, "no such document")
        try:
            with _review_lock:
                out = Job(runner.job_dir(cfg, job_id), None).build_preview(doc_key)
        except ValueError as e:
            raise HTTPException(404, str(e))
        except BuildError as e:
            raise HTTPException(422, f"the preview could not be built: {e}")
        return FileResponse(out, media_type="application/pdf", filename=f"{doc_key}_preview.pdf",
                            content_disposition_type="inline", headers={"Cache-Control": "no-store"})

    @app.post("/api/jobs/{job_id}/approve")
    def approve(job_id: str, body: ApproveIn, u: User = Depends(current_user), _=Depends(csrf)):
        with Session() as s:
            row = _job_for(s, job_id, u)
            if row.status != "waiting_review":
                raise HTTPException(409, f"job is {row.status}, not waiting for review")
            signer = s.get(User, row.created_by)
            if u.role != "admin" and (u.role != "certified_translator" or u.id != signer.id):
                raise HTTPException(403, "only the signing certified translator (or an admin) can approve")
            blocked = _open_blockers(runner.job_dir(cfg, job_id), [d.doc_key for d in row.documents])
            if blocked:
                raise HTTPException(409, "open QA blockers must be resolved before approval: "
                                         + ", ".join(f"{k}: {', '.join(v)}" for k, v in blocked.items()))
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


def _iso(dt: datetime) -> str:
    """UTC ISO time (SQLite drops the time zone)."""
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "name": u.name, "role": u.role, "ui_language": u.ui_language}


def _may_see(row: JobRow, u: User) -> bool:
    return u.role == "admin" or row.created_by == u.id or row.approved_by == u.id


def _term_out(t: ClientTerm) -> dict:
    return {"id": t.id, "client": t.client, "source_language": t.source_language, "target_language": t.target_language,
            "source": t.source, "target": t.target, "kind": t.kind, "updated_at": _iso(t.updated_at),
            "updated_by": t.updated_by, "job_id": t.job_id, "uses": t.uses}


def _job_out(r: JobRow, brief: bool = False) -> dict:
    out = {"id": r.id, "title": r.title, "created_at": r.created_at.isoformat(), "status": r.status,
           "stage": r.stage, "source_language": r.source_language, "target_language": r.target_language,
           "stamp": r.stamp, "cost_usd": r.cost_usd, "error": r.error, "documents_count": len(r.documents),
           "client": r.client, "keep": bool(r.keep), "purged_at": r.purged_at.isoformat() if r.purged_at else None}
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


def _open_blockers(jd: Path, doc_keys: list[str]) -> dict[str, list[str]]:
    """Blocks with unresolved blocker flags, per document, from the latest review state."""
    from ..model import Document
    out = {}
    for k in doc_keys:
        for st in REVIEW_STAGES:
            p = jd / "docs" / f"{k}.{st}.json"
            if p.exists():
                ids = rv.open_blockers(Document.model_validate_json(p.read_text("utf-8")))
                if ids:
                    out[k] = ids
                break
    return out
