"""Usage and cost figures for the admin dashboard.

The job's ``audit.jsonl`` stays the source of truth. ``sync_job`` copies its model calls (numbers only) into the
``llm_usage`` table and stores the job's page count, so the dashboard never has to read every job folder.
It replaces the job's rows each time, so calling it again is always safe."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from .db import Job as JobRow
from .db import LlmUsage, User, aware


def _read_calls(jd: Path) -> list[dict]:
    p = jd / "audit.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text("utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("kind") == "llm_call":
            out.append(r)
    return out


def _pages(jd: Path) -> int | None:
    """Source pages counted by Intake, summed over the job's documents (None before Intake ran)."""
    total, seen = 0, False
    for f in sorted((jd / "docs").glob("*.intake.json")):
        try:
            total += len(json.loads(f.read_text("utf-8")).get("pages") or [])
            seen = True
        except ValueError:
            continue
    return total if seen else None


def sync_job(s, job_id: str, jd: Path) -> float:
    """Copy the job's model calls into ``llm_usage``; returns the job's total cost. Caller commits."""
    s.execute(delete(LlmUsage).where(LlmUsage.job_id == job_id))
    total = 0.0
    for r in _read_calls(jd):
        u = r.get("usage") or {}
        cost = float(r.get("cost_usd") or 0.0)
        total += cost
        s.add(LlmUsage(job_id=job_id, at=datetime.fromisoformat(r["at"]), document=str(r.get("document") or "")[:10],
                       agent=str(r.get("agent") or "")[:40], model=str(r.get("model") or "")[:80],
                       prompt_version=str(r.get("prompt_version") or "")[:20],
                       input_tokens=int(u.get("input_tokens") or 0), output_tokens=int(u.get("output_tokens") or 0),
                       cache_read_tokens=int(u.get("cache_read_input_tokens") or 0),
                       cache_write_tokens=int(u.get("cache_creation_input_tokens") or 0), cost_usd=cost))
    row = s.get(JobRow, job_id)
    if row is not None:
        row.pages = _pages(jd)
    return round(total, 4)


def backfill(s, jobs_dir: Path) -> int:
    """Sync jobs that have never been synced (no usage rows and no page count). Caller commits."""
    have = set(s.scalars(select(LlmUsage.job_id).distinct()))
    n = 0
    for row in s.scalars(select(JobRow)):
        if row.id not in have and row.pages is None and (jobs_dir / row.id).is_dir():
            sync_job(s, row.id, jobs_dir / row.id)
            n += 1
    return n


def summary(s, days: int, tz: str, now: datetime | None = None) -> dict:
    """Dashboard figures for the last ``days`` days (office time zone), plus today / 7 days / this month."""
    zone = ZoneInfo(tz)
    now = (now or datetime.now(timezone.utc)).astimezone(zone)
    today = now.date()
    first = today - timedelta(days=days - 1)
    month_start = today.replace(day=1)
    since = datetime.combine(min(first, month_start, today - timedelta(days=6)), datetime.min.time(), zone)

    rows = s.execute(select(LlmUsage, JobRow.created_by, JobRow.title, JobRow.status, JobRow.pages)
                     .join(JobRow, JobRow.id == LlmUsage.job_id)
                     .where(LlmUsage.at >= since.astimezone(timezone.utc))).all()
    names = {u.id: (u.username, u.name) for u in s.scalars(select(User))}

    per_day: dict[date, dict] = {first + timedelta(days=i): {"cost_usd": 0.0, "calls": 0} for i in range(days)}
    agents: dict[str, dict] = defaultdict(lambda: {"calls": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                                                   "cache_read_tokens": 0})
    models: dict[str, dict] = defaultdict(lambda: {"calls": 0, "cost_usd": 0.0})
    users: dict[int, dict] = defaultdict(lambda: {"jobs": set(), "cost_usd": 0.0})
    jobs: dict[str, dict] = {}
    tiles = {"today": 0.0, "week": 0.0, "month": 0.0}
    total = {"cost_usd": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}

    for u, created_by, title, status, pages in rows:
        d = aware(u.at).astimezone(zone).date()
        c = u.cost_usd
        if d == today:
            tiles["today"] += c
        if d > today - timedelta(days=7):
            tiles["week"] += c
        if d >= month_start:
            tiles["month"] += c
        if d < first:
            continue
        per_day[d]["cost_usd"] += c
        per_day[d]["calls"] += 1
        a = agents[u.agent]
        a["calls"] += 1
        a["cost_usd"] += c
        a["input_tokens"] += u.input_tokens
        a["output_tokens"] += u.output_tokens
        a["cache_read_tokens"] += u.cache_read_tokens
        models[u.model]["calls"] += 1
        models[u.model]["cost_usd"] += c
        users[created_by]["jobs"].add(u.job_id)
        users[created_by]["cost_usd"] += c
        j = jobs.setdefault(u.job_id, {"id": u.job_id, "title": title, "status": status, "pages": pages,
                                       "by": names.get(created_by, ("?", "?"))[1], "cost_usd": 0.0, "calls": 0})
        j["cost_usd"] += c
        j["calls"] += 1
        total["cost_usd"] += c
        total["calls"] += 1
        total["input_tokens"] += u.input_tokens
        total["output_tokens"] += u.output_tokens
        total["cache_read_tokens"] += u.cache_read_tokens

    r4 = lambda x: round(x, 4)  # noqa: E731
    priced = [j for j in jobs.values() if j["pages"]]
    pages = sum(j["pages"] for j in priced)
    return {
        "days": days, "timezone": tz, "from": first.isoformat(), "to": today.isoformat(),
        "tiles": {k: r4(v) for k, v in tiles.items()},
        "total": {**total, "cost_usd": r4(total["cost_usd"]), "jobs": len(jobs)},
        "per_page_usd": r4(sum(j["cost_usd"] for j in priced) / pages) if pages else None,
        "pages": pages,
        "by_day": [{"day": d.isoformat(), "cost_usd": r4(v["cost_usd"]), "calls": v["calls"]} for d, v in per_day.items()],
        "by_agent": sorted(({"agent": k, **v, "cost_usd": r4(v["cost_usd"])} for k, v in agents.items()),
                           key=lambda x: -x["cost_usd"]),
        "by_model": sorted(({"model": k, **v, "cost_usd": r4(v["cost_usd"])} for k, v in models.items()),
                           key=lambda x: -x["cost_usd"]),
        "by_user": sorted(({"username": names.get(k, ("?", "?"))[0], "name": names.get(k, ("?", "?"))[1],
                            "jobs": len(v["jobs"]), "cost_usd": r4(v["cost_usd"])} for k, v in users.items()),
                          key=lambda x: -x["cost_usd"]),
        "top_jobs": sorted(({**j, "cost_usd": r4(j["cost_usd"])} for j in jobs.values()),
                           key=lambda x: -x["cost_usd"])[:10],
    }
