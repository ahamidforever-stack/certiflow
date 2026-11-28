"""Runs pipeline jobs for the web app.

``advance(job_id, resume)`` moves a job to its next human gate (glossary confirmation,
final review) or to release. It is the single unit of work for both runners:
* ``thread`` - a small in-process pool (development, tests, single-server installs)
* ``celery`` - Redis-backed Celery workers (production; see certiflow/web/tasks.py)
Stages are idempotent, so a worker crash resumes at the failed stage on the next ``advance``.
"""
from __future__ import annotations

import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import WebConfig, get_config
from .db import Job as JobRow
from .db import JobEvent, session_factory
from .usage import sync_job

_pool: ThreadPoolExecutor | None = None


def llm_client(cfg: WebConfig, target_language: str):
    if cfg.llm == "mock":
        from ..llm.mock_agents import make_mock
        return make_mock(target_language)
    from ..llm.client import AnthropicClient
    from ..settings import load
    st = load()
    return AnthropicClient(fallbacks=st.fallbacks, validation_retries=st.pipeline.validation_retries)


def job_dir(cfg: WebConfig, job_id: str) -> Path:
    return cfg.jobs_dir / job_id


def _event(s, job_id: str, kind: str, **data) -> None:
    s.add(JobEvent(job_id=job_id, kind=kind, data=data))


def advance(job_id: str, resume: Any = None, cfg: WebConfig | None = None) -> dict:
    from ..builder.package import ReleaseBlocked
    from ..pipeline.job import Job
    cfg = cfg or get_config()
    Session = session_factory(cfg.database_url)
    with Session() as s:
        row = s.get(JobRow, job_id)
        if row is None:
            return {"error": "no such job"}
        row.status, row.error = ("releasing" if isinstance(resume, dict) and resume.get("approved_by") else "running"), None
        _event(s, job_id, "status", status=row.status)
        s.commit()
        target = row.target_language
    try:
        job = Job(job_dir(cfg, job_id), llm_client(cfg, target))
        res = job.run(resume=resume, checkpoint_dsn=cfg.checkpoint_dsn or None)
        waiting = [w.get("waiting_for") for w in res.get("waiting") or []]
        status = ("waiting_glossary" if "glossary_confirmation" in waiting else
                  "waiting_review" if "final_review" in waiting else
                  "released" if res.get("stage") == "released" else "running")
        err = None
    except ReleaseBlocked as e:
        status, err, res, job = "waiting_review", f"Release blocked: {e}", {}, Job(job_dir(cfg, job_id), None)
    except Exception as e:  # noqa: BLE001 - recorded for the user; details in the server log only
        status, err, res = "failed", f"{type(e).__name__}: {str(e)[:300]}", {}
        traceback.print_exc()
        job = None
    with Session() as s:
        row = s.get(JobRow, job_id)
        row.status, row.error = status, err
        row.stage = res.get("stage") or row.stage
        if job is not None:
            row.cost_usd = sync_job(s, job_id, job_dir(cfg, job_id))
        if status == "released":
            appr = json.loads((job_dir(cfg, job_id) / "approval.json").read_text("utf-8"))
            row.approved_at = datetime.fromisoformat(appr["at"])
        _event(s, job_id, "status", status=status, error=err)
        s.commit()
    return {"status": status, "error": err}


def rerun(job_id: str, doc_key: str, agent: str, blocks: list[str], instruction: str = "", by: str = "",
          cfg: WebConfig | None = None) -> dict:
    """Run one agent again on selected blocks while the job waits for review (status ``reworking``).

    The job always returns to ``waiting_review``; a failure is shown as the job error, not as a failed job."""
    from ..pipeline.job import Job
    cfg = cfg or get_config()
    Session = session_factory(cfg.database_url)
    with Session() as s:
        row = s.get(JobRow, job_id)
        target = row.target_language
    err, changes = None, 0
    job = None
    try:
        job = Job(job_dir(cfg, job_id), llm_client(cfg, target))
        changes = job.rerun(doc_key, agent, blocks, instruction, by)
    except Exception as e:  # noqa: BLE001 - shown to the reviewer; details in the server log only
        err = f"Re-run failed: {type(e).__name__}: {str(e)[:300]}"
        traceback.print_exc()
    with Session() as s:
        row = s.get(JobRow, job_id)
        row.status, row.error = "waiting_review", err
        if job is not None:
            row.cost_usd = sync_job(s, job_id, job_dir(cfg, job_id))
        _event(s, job_id, "status", status="waiting_review", error=err)
        s.commit()
    return {"changes": changes, "error": err}


def submit_rerun(job_id: str, doc_key: str, agent: str, blocks: list[str], instruction: str, by: str) -> None:
    cfg = get_config()
    if cfg.queue == "celery":
        from .tasks import rerun_job
        rerun_job.delay(job_id, doc_key, agent, blocks, instruction, by)
        return
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="certiflow-job")
    _pool.submit(rerun, job_id, doc_key, agent, blocks, instruction, by, cfg)


def submit(job_id: str, resume: Any = None) -> None:
    cfg = get_config()
    if cfg.queue == "celery":
        from .tasks import advance_job
        advance_job.delay(job_id, resume)
        return
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="certiflow-job")
    _pool.submit(advance, job_id, resume, cfg)
