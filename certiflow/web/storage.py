"""Storage hardening (Phase 5): retention / automatic deletion, backups, backup encryption.

Retention (off until an admin switches it on):
* a job's *files* (uploads, stage files, release, page images, glossary) are deleted after a number of days without
  activity; its *record* stays: the database row, its events and usage, and the audit log reduced to the keys the
  audit view shows (no document text). Jobs marked "keep" (legal hold) are never deleted.

Backups:
* one ``.tar.gz`` with the database, the admin settings, the asset library and (optionally) the job folders
* encrypted when ``CERTIFLOW_BACKUP_KEY`` is set: scrypt key derivation + AES-256-GCM in 1 MiB chunks, the last
  chunk marked so a truncated file is detected (``certiflow web decrypt-backup`` turns it back into ``.tar.gz``)
* the newest ``backup_keep`` backups are kept; copy them off the server (another disk, another site)

Live job files are not encrypted by the app (LibreOffice, OCR and PDF tools read them directly): run the data volume
and the database on an encrypted disk (LUKS or the cloud provider's disk encryption)."""
from __future__ import annotations

import fcntl
import io
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import tarfile
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Iterator, Optional

from sqlalchemy import select

from .config import WebConfig
from .db import Job as JobRow
from .db import JobEvent, aware, utcnow

DEFAULTS = {"enabled": False, "released_days": 90, "unfinished_days": 30,
            "backup_daily": False, "backup_hour": 2, "backup_keep": 14, "backup_jobs": True}
BUSY = {"queued", "running", "releasing", "reworking"}
MAGIC = b"CFBK1\n"
CHUNK = 1 << 20
_backup_lock = threading.Lock()
_state: dict = {"running": False, "last_error": None}


class StorageError(ValueError):
    pass


# ------------------------------------------------------------------ settings


def settings_path(cfg: WebConfig) -> Path:
    return cfg.data_dir / "settings" / "storage.json"


def load_settings(cfg: WebConfig) -> dict:
    p = settings_path(cfg)
    return {**DEFAULTS, **(json.loads(p.read_text("utf-8")) if p.exists() else {})}


def save_settings(cfg: WebConfig, values: dict) -> tuple[dict, dict]:
    cur = load_settings(cfg)
    new = dict(cur)
    rules = {"released_days": (7, 3650), "unfinished_days": (7, 3650), "backup_hour": (0, 23), "backup_keep": (1, 365)}
    for k, v in values.items():
        if k not in DEFAULTS:
            raise StorageError(f"unknown setting {k}")
        if isinstance(DEFAULTS[k], bool):
            if not isinstance(v, bool):
                raise StorageError(f"{k} must be true or false")
        else:
            lo, hi = rules[k]
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                raise StorageError(f"{k} must be between {lo} and {hi}")
        new[k] = v
    p = settings_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new, indent=2) + "\n", "utf-8")
    tmp.replace(p)
    return new, {k: [cur[k], new[k]] for k in new if cur[k] != new[k]}


# ------------------------------------------------------------------ retention


def _last_activity(row: JobRow, jd: Path) -> datetime:
    t = aware(row.updated_at) or aware(row.created_at)
    if jd.is_dir():
        newest = max((f.stat().st_mtime for f in jd.rglob("*") if f.is_file()), default=0)
        if newest:
            t = max(t, datetime.fromtimestamp(newest, timezone.utc))
    return t


def candidates(s, cfg: WebConfig, now: Optional[datetime] = None) -> list[dict]:
    """Jobs whose files the retention rules would delete now (whether or not retention is switched on)."""
    st = load_settings(cfg)
    now = now or utcnow()
    out = []
    for row in s.scalars(select(JobRow).where(JobRow.purged_at.is_(None), JobRow.keep.is_(False))):
        if row.status in BUSY:
            continue
        days = st["released_days"] if row.status == "released" else st["unfinished_days"]
        last = _last_activity(row, cfg.jobs_dir / row.id)
        if now - last >= timedelta(days=days):
            out.append({"id": row.id, "title": row.title, "status": row.status, "last_activity": last.isoformat(),
                        "rule": "released" if row.status == "released" else "unfinished"})
    return out


def purge_job(s, cfg: WebConfig, row: JobRow, keep_keys: set[str], by: str) -> int:
    """Delete a job's files, keep its record. Returns the bytes freed. Caller commits."""
    jd = cfg.jobs_dir / row.id
    freed = 0
    if jd.is_dir():
        freed = sum(f.stat().st_size for f in jd.rglob("*") if f.is_file())
        audit = jd / "audit.jsonl"
        kept = []
        if audit.exists():
            for line in audit.read_text("utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                kept.append(json.dumps({k: v for k, v in r.items() if k in keep_keys}, ensure_ascii=False))
        shutil.rmtree(jd)
        jd.mkdir(parents=True)
        (jd / "audit.jsonl").write_text("\n".join(kept) + ("\n" if kept else ""), "utf-8")
    row.purged_at = utcnow()
    s.add(JobEvent(job_id=row.id, kind="purged", data={"by": by}))
    return freed


def run_retention(s, cfg: WebConfig, keep_keys: set[str], by: str = "retention") -> dict:
    """Apply the retention rules (only when switched on). Caller commits."""
    if not load_settings(cfg)["enabled"]:
        return {"enabled": False, "purged": [], "freed": 0}
    purged, freed = [], 0
    for c in candidates(s, cfg):
        row = s.get(JobRow, c["id"])
        freed += purge_job(s, cfg, row, keep_keys, by)
        purged.append(c["id"])
    return {"enabled": True, "purged": purged, "freed": freed}


def usage(cfg: WebConfig, s) -> dict:
    total = sum(f.stat().st_size for f in cfg.jobs_dir.rglob("*") if f.is_file())
    jobs = s.scalars(select(JobRow)).all()
    return {"jobs": len(jobs), "purged": sum(1 for j in jobs if j.purged_at), "kept": sum(1 for j in jobs if j.keep),
            "job_bytes": total, "free_bytes": shutil.disk_usage(cfg.data_dir).free}


# ------------------------------------------------------------------ backup encryption


def _derive(passphrase: str, salt: bytes) -> bytes:
    import hashlib
    return hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)


def encrypt_stream(src: BinaryIO, dst: BinaryIO, passphrase: str) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, prefix = os.urandom(16), os.urandom(8)
    aes = AESGCM(_derive(passphrase, salt))
    dst.write(MAGIC + salt + prefix)
    n, buf = 0, src.read(CHUNK)
    while True:
        nxt = src.read(CHUNK)
        final = not nxt
        ct = aes.encrypt(prefix + struct.pack(">I", n), buf, b"final" if final else b"chunk")
        dst.write(struct.pack(">I", len(ct)) + ct)
        if final:
            return
        n, buf = n + 1, nxt


def decrypt_stream(src: BinaryIO, dst: BinaryIO, passphrase: str) -> None:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if src.read(len(MAGIC)) != MAGIC:
        raise StorageError("not an encrypted CertiFlow backup")
    salt, prefix = src.read(16), src.read(8)
    aes = AESGCM(_derive(passphrase, salt))
    n = 0
    while True:
        head = src.read(4)
        if len(head) < 4:
            raise StorageError("the backup is truncated")
        ct = src.read(struct.unpack(">I", head)[0])
        nonce = prefix + struct.pack(">I", n)
        try:
            dst.write(aes.decrypt(nonce, ct, b"chunk"))
        except InvalidTag:
            try:
                dst.write(aes.decrypt(nonce, ct, b"final"))
            except InvalidTag:
                raise StorageError("wrong key or damaged backup") from None
            if src.read(1):
                raise StorageError("unexpected data after the end of the backup")
            return
        n += 1


# ------------------------------------------------------------------ backups


def backup_dir(cfg: WebConfig) -> Path:
    p = Path(os.environ.get("CERTIFLOW_BACKUP_DIR") or cfg.data_dir / "backups")
    p.mkdir(parents=True, exist_ok=True)
    return p


def backup_key() -> Optional[str]:
    return os.environ.get("CERTIFLOW_BACKUP_KEY") or None


def _db_dump(cfg: WebConfig, out: Path) -> str:
    url = cfg.database_url
    if url.startswith("sqlite"):
        src = sqlite3.connect(url.split("///", 1)[1])
        dst = sqlite3.connect(out / "certiflow.db")
        with dst:
            src.backup(dst)                      # consistent copy while the app keeps running
        src.close()
        dst.close()
        return "certiflow.db"
    if url.startswith("postgresql"):
        pg_url = url.replace("postgresql+psycopg://", "postgresql://")
        with open(out / "certiflow.sql", "wb") as f:
            r = subprocess.run(["pg_dump", "--no-owner", "--dbname", pg_url], stdout=f, stderr=subprocess.PIPE)
        if r.returncode:
            raise StorageError(f"pg_dump failed: {r.stderr.decode(errors='replace')[:200]}")
        return "certiflow.sql"
    raise StorageError("unsupported database for backups")


def create_backup(cfg: WebConfig, include_jobs: bool = True) -> dict:
    """Write one backup file; returns its listing entry. One backup at a time."""
    if not _backup_lock.acquire(blocking=False):
        raise StorageError("a backup is already running")
    try:
        _state.update(running=True, last_error=None)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        key = backup_key()
        out = backup_dir(cfg) / f"certiflow-{stamp}.tar.gz{'.enc' if key else ''}"
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            db_name = _db_dump(cfg, tdp)
            raw = tdp / "backup.tar.gz"
            with tarfile.open(raw, "w:gz") as tar:
                manifest = {"created": stamp, "database": db_name, "jobs": include_jobs,
                            "library": str(cfg.library.parent.name)}
                data = json.dumps(manifest, indent=1).encode()
                info = tarfile.TarInfo("MANIFEST.json")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
                tar.add(tdp / db_name, arcname=f"database/{db_name}")
                if (cfg.data_dir / "settings").is_dir():
                    tar.add(cfg.data_dir / "settings", arcname="settings",
                            filter=lambda ti: None if Path(ti.name).name.startswith(".") else ti)
                if cfg.library.parent.is_dir():
                    tar.add(cfg.library.parent, arcname="library")
                if include_jobs:
                    tar.add(cfg.jobs_dir, arcname="jobs")
            tmp = out.with_name(out.name + ".part")
            with open(raw, "rb") as src, open(tmp, "wb") as dst:
                if key:
                    encrypt_stream(src, dst, key)
                else:
                    shutil.copyfileobj(src, dst)
            tmp.chmod(0o600)
            tmp.replace(out)
        rotate(cfg)
        return _entry(out)
    except Exception as e:
        _state["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
        raise
    finally:
        _state["running"] = False
        _backup_lock.release()


def _entry(p: Path) -> dict:
    st = p.stat()
    return {"name": p.name, "size": st.st_size, "encrypted": p.name.endswith(".enc"),
            "created": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()}


def list_backups(cfg: WebConfig) -> list[dict]:
    files = [p for p in backup_dir(cfg).glob("certiflow-*.tar.gz*") if not p.name.endswith(".part")]
    return [_entry(p) for p in sorted(files, key=lambda p: p.name, reverse=True)]


def rotate(cfg: WebConfig) -> None:
    keep = load_settings(cfg)["backup_keep"]
    for e in list_backups(cfg)[keep:]:
        (backup_dir(cfg) / e["name"]).unlink(missing_ok=True)


def state() -> dict:
    return dict(_state)


# ------------------------------------------------------------------ scheduler


@contextmanager
def _file_lock(path: Path) -> Iterator[bool]:
    """Only one process (of several API workers) runs the scheduled work at a time."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def scheduled(cfg: WebConfig, Session, keep_keys: set[str], now: Optional[datetime] = None) -> dict:
    """One scheduler tick: retention, then the daily backup once its hour has come (office time zone)."""
    from zoneinfo import ZoneInfo
    done: dict = {}
    with _file_lock(cfg.data_dir / "settings" / ".scheduler.lock") as got:
        if not got:
            return {"skipped": True}
        with Session() as s:
            done["retention"] = run_retention(s, cfg, keep_keys)
            s.commit()
        st = load_settings(cfg)
        if st["backup_daily"]:
            local = (now or utcnow()).astimezone(ZoneInfo(cfg.timezone))
            today = [b for b in list_backups(cfg)
                     if datetime.fromisoformat(b["created"]).astimezone(ZoneInfo(cfg.timezone)).date() == local.date()]
            if local.hour >= st["backup_hour"] and not today:
                done["backup"] = create_backup(cfg, include_jobs=st["backup_jobs"])["name"]
    return done


def start_scheduler(cfg: WebConfig, Session, keep_keys: set[str], every_s: int = 900) -> threading.Thread:
    def loop():
        import time
        import traceback
        time.sleep(60)
        while True:
            try:
                scheduled(cfg, Session, keep_keys)
            except Exception:  # noqa: BLE001 - logged, the next tick tries again
                traceback.print_exc()
            time.sleep(every_s)
    t = threading.Thread(target=loop, name="certiflow-scheduler", daemon=True)
    t.start()
    return t
