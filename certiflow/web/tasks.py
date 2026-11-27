"""Celery worker entry point:  celery -A certiflow.web.tasks worker --concurrency=2"""
from __future__ import annotations

from celery import Celery

from .config import get_config

app = Celery("certiflow", broker=get_config().redis_url, backend=None)
app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_serializer="json", accept_content=["json"])


@app.task(name="certiflow.advance_job")
def advance_job(job_id: str, resume=None):
    from .runner import advance
    return advance(job_id, resume)


@app.task(name="certiflow.rerun_job")
def rerun_job(job_id: str, doc_key: str, agent: str, blocks: list, instruction: str = "", by: str = ""):
    from .runner import rerun
    return rerun(job_id, doc_key, agent, blocks, instruction, by)
