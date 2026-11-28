"""Job orchestration with LangGraph.

Graph (one job = one batch of 1..N documents):

    intake_all -> glossary -> [interrupt: confirm glossary] -> process_all -> [interrupt: final review] -> release

* ``process_all`` runs each document's translate -> proofread -> QA -> (fix loop, max N) -> format
  in parallel threads (independent documents in parallel, stages of one document in sequence).
* Every stage writes its result to the job directory and skips work already on disk, so a
  crashed job resumes at the failed stage; the SQLite checkpointer keeps the graph position
  (PostgreSQL in the web deployment).
* The stamp and signature are applied only in ``release``, after a certified translator approves.
"""
from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ..agents import steps
from ..agents.base import AgentContext, AuditLog
from ..assets import AssetLibrary
from ..builder.package import ReleaseBlocked, build_package, zip_batch
from ..llm.client import LLMClient
from ..model import BlockStatus, BlockType, Document, GlossaryEntry, JobSpec, Severity
from ..profiles import resolve_pair
from ..settings import Settings, load


RERUN_AGENTS = {"translator", "proofreader", "qa"}
PREVIEW_WATERMARK = "PREVIEW - NOT CERTIFIED"


class JobState(TypedDict, total=False):
    job_dir: str
    stage: str
    loops: dict
    released: list


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write a stage file atomically: readers (status, review API) never see a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding)
    tmp.replace(path)


class Job:
    """A translation job on disk: job.json (spec + documents), docs/*, glossary.json, audit.jsonl."""

    def __init__(self, job_dir: Path, client: LLMClient, settings: Settings | None = None):
        self.dir = Path(job_dir)
        self.client = client
        self.settings = settings or load()
        self.meta = json.loads((self.dir / "job.json").read_text("utf-8"))
        self.spec = JobSpec.model_validate(self.meta["spec"])
        self.audit = AuditLog(self.dir / "audit.jsonl")

    # ---------------------------------------------------------------- setup

    @staticmethod
    def create(job_dir: Path, sources: list[Path], source_language: str, target_language: str, spec: JobSpec,
               library: Path, titles: list[str] | None = None,
               languages: list[tuple[str, str]] | None = None) -> Path:
        """``languages`` optionally gives each document its own (source, target) pair."""
        job_dir.mkdir(parents=True, exist_ok=True)
        docs = []
        for i, s in enumerate(sources):
            src, tgt = languages[i] if languages else (source_language, target_language)
            docs.append({"id": f"d{i + 1:02d}", "source": str(Path(s).resolve()),
                         "title": (titles[i] if titles else Path(s).stem.replace("_", " ")),
                         "source_language": src, "target_language": tgt})
        _write((job_dir / "job.json"), json.dumps({
            "created": _now(), "spec": spec.model_dump(mode="json"), "library": str(Path(library).resolve()),
            "documents": docs}, indent=2, ensure_ascii=False), "utf-8")
        (job_dir / "docs").mkdir(exist_ok=True)
        return job_dir

    # -------------------------------------------------------------- helpers

    def doc_path(self, doc_id: str, stage: str) -> Path:
        return self.dir / "docs" / f"{doc_id}.{stage}.json"

    def save_doc(self, doc: Document, stage: str) -> None:
        _write(self.doc_path(doc.id, stage), doc.model_dump_json(indent=1, exclude_defaults=True), "utf-8")

    def load_doc(self, doc_id: str, stage: str) -> Optional[Document]:
        p = self.doc_path(doc_id, stage)
        return Document.model_validate_json(p.read_text("utf-8")) if p.exists() else None

    def glossary(self) -> list[GlossaryEntry]:
        p = self.dir / "glossary.json"
        return [GlossaryEntry.model_validate(g) for g in json.loads(p.read_text("utf-8"))] if p.exists() else []

    def remembered_terms(self, src: str, tgt: str, docs: list[Document]) -> list[GlossaryEntry]:
        """Client glossary memory (``glossary.memory.json``, written when the job was created): the terms for this
        language pair whose source text occurs in the batch, pre-confirmed. The glossary agent adds only new ones."""
        p = self.dir / "glossary.memory.json"
        if not p.exists():
            return []
        texts = []
        for d in docs:
            for b in d.blocks:
                texts.append(b.source_text)
                texts += [c.source_text for r in b.rows for c in r.cells]
        corpus = "\n".join(texts).casefold()
        out, seen = [], set()
        for m in json.loads(p.read_text("utf-8")):
            if (m.get("source_language"), m.get("target_language")) != (src, tgt) or m["source"] in seen:
                continue
            if m["source"].casefold() in corpus:
                seen.add(m["source"])
                out.append(GlossaryEntry(source=m["source"], target=m["target"], kind=m.get("kind", "term"),
                                         confirmed=True))
        if out:
            self.event("glossary_memory", items=len(out))
        return out

    def ctx(self, src: str, tgt: str, doc_id: str = "") -> AgentContext:
        pair = resolve_pair(src if src != "auto" else "en", tgt)
        return AgentContext(pair=pair, settings=self.settings, client=self.client, audit=self.audit,
                            glossary=self.glossary(), job_id=self.dir.name, document_id=doc_id)

    def event(self, kind: str, **kw) -> None:
        self.audit.record({"kind": kind, "at": _now(), "job": self.dir.name, **kw})

    # ----------------------------------------------------------------- nodes

    def n_intake_all(self, state: JobState) -> dict:
        def one(d: dict):
            if self.load_doc(d["id"], "intake"):
                return
            ctx = self.ctx(d["source_language"], d["target_language"], d["id"])
            doc = steps.intake(ctx, Path(d["source"]), d["id"], d["title"], d["source_language"], d["target_language"])
            self.save_doc(doc, "intake")
            self.event("stage_done", stage="intake", document=d["id"], blocks=len(doc.blocks))
        self._parallel(one)
        return {"stage": "intake_done"}

    def n_glossary(self, state: JobState) -> dict:
        if not (self.dir / "glossary.proposed.json").exists():
            docs = [self.load_doc(d["id"], "intake") for d in self.meta["documents"]]
            d0 = docs[0]
            ctx = self.ctx(d0.source_language, d0.target_language)
            ctx.glossary = self.remembered_terms(d0.source_language, d0.target_language, docs)
            proposed = steps.glossary(ctx, docs)
            _write((self.dir / "glossary.proposed.json"), 
                json.dumps([g.model_dump() for g in proposed], indent=1, ensure_ascii=False), "utf-8")
        return {"stage": "glossary_proposed"}

    def n_confirm_glossary(self, state: JobState) -> dict:
        if not (self.dir / "glossary.json").exists():
            proposed = json.loads((self.dir / "glossary.proposed.json").read_text("utf-8"))
            answer = interrupt({"waiting_for": "glossary_confirmation", "proposed": len(proposed),
                                "file": str(self.dir / "glossary.proposed.json")})
            items = answer.get("glossary") if isinstance(answer, dict) and answer.get("glossary") is not None else proposed
            for g in items:
                g["confirmed"] = True
            _write((self.dir / "glossary.json"), json.dumps(items, indent=1, ensure_ascii=False), "utf-8")
            self.event("glossary_confirmed", by=(answer or {}).get("by") if isinstance(answer, dict) else None,
                       items=len(items))
        return {"stage": "glossary_confirmed"}

    def n_process_all(self, state: JobState) -> dict:
        loops: dict = {}

        def one(d: dict):
            loops[d["id"]] = self.process_document(d["id"])
        self._parallel(one)
        return {"stage": "ready_for_review", "loops": loops}

    def process_document(self, doc_id: str) -> int:
        """translate -> proofread -> QA -> fix loop -> format; each stage checkpointed on disk."""
        if self.load_doc(doc_id, "formatted"):
            return 0
        doc = self.load_doc(doc_id, "proofread") or self.load_doc(doc_id, "translated")
        ctx = None
        if doc is None:
            doc = self.load_doc(doc_id, "intake")
            ctx = self.ctx(doc.source_language, doc.target_language, doc_id)
            steps.translate(ctx, doc)
            self.save_doc(doc, "translated")
        ctx = ctx or self.ctx(doc.source_language, doc.target_language, doc_id)
        if not self.doc_path(doc_id, "proofread").exists():
            changes = steps.proofread(ctx, doc)
            self.save_doc(doc, "proofread")
            self.event("stage_done", stage="proofread", document=doc_id, changes=len(changes))
        issues = steps.qa(ctx, doc)
        loops = 0
        while loops < self.settings.pipeline.qa_max_loops:
            blockers = [i for i in issues if i.severity == "blocker" and i.id]
            if not blockers:
                break
            loops += 1
            fixes: dict[str, list[str]] = {}
            for i in blockers:
                fixes.setdefault(i.id, []).append(f"{i.code}: {i.message}" + (f" (fix: {i.suggested_fix})" if i.suggested_fix else ""))
            self.event("qa_loop", document=doc_id, loop=loops, blocks=sorted(fixes))
            steps.translate(ctx, doc, only=set(fixes), fix_requests=fixes)
            steps.proofread(ctx, doc, only=set(fixes))
            issues = steps.qa(ctx, doc, only=set(fixes)) + [i for i in issues if i.id not in fixes]
        open_blockers = [b.id for b in doc.blocks if any(f.severity == Severity.blocker and not f.resolved for f in b.flags)]
        for b in doc.blocks:
            if b.id in open_blockers:
                b.status = BlockStatus.needs_review
        self.save_doc(doc, "qa")
        _write((self.dir / "docs" / f"{doc_id}.qa_report.json"), 
            json.dumps([i.model_dump() for i in issues], indent=1, ensure_ascii=False), "utf-8")
        steps.format_document(ctx, doc)
        self.save_doc(doc, "formatted")
        self.event("stage_done", stage="qa_format", document=doc_id, qa_loops=loops, open_blockers=open_blockers)
        return loops

    def n_review(self, state: JobState) -> dict:
        answer = interrupt({"waiting_for": "final_review",
                            "documents": {d["id"]: str(self.doc_path(d["id"], "formatted")) for d in self.meta["documents"]}})
        if not isinstance(answer, dict) or not answer.get("approved_by"):
            raise ReleaseBlocked("release needs an approval by a certified translator")
        self.event("approved", by=answer["approved_by"], note=answer.get("note"))
        _write((self.dir / "approval.json"), json.dumps({"approved_by": answer["approved_by"], "at": _now()}), "utf-8")
        return {"stage": "approved"}

    def n_release(self, state: JobState) -> dict:
        approval = json.loads((self.dir / "approval.json").read_text("utf-8"))
        lib = AssetLibrary(Path(self.meta["library"]))
        approver = lib.user(approval["approved_by"])
        if approver.role not in ("certified_translator", "admin"):
            raise ReleaseBlocked(f"{approver.id} is not a certified translator")
        out = self.dir / "release"
        results = []
        for i, d in enumerate(self.meta["documents"]):
            doc = self.load_doc(d["id"], "reviewed") or self.load_doc(d["id"], "formatted")
            open_blockers = [b.id for b in doc.blocks if any(f.severity == Severity.blocker and not f.resolved
                                                             for f in b.flags)]
            if open_blockers:
                raise ReleaseBlocked(f"{d['id']}: open QA blockers on blocks {open_blockers}; resolve them in review")
            res = build_package(doc, Path(d["source"]), self.spec, lib, out, index=i + 1)
            results.append((doc.title, res))
            self.event("released", document=d["id"], docx=res.docx.name, pdf=res.pdf.name, **res.audit)
        from ..builder.package import write_disclosures
        write_disclosures(results, out / "disclosures.txt")
        z = zip_batch(results, out, self.dir.name) if len(results) > 1 else None
        return {"stage": "released", "released": [str(r.pdf) for _, r in results] + ([str(z)] if z else [])}

    # ----------------------------------------------------------------- review (Phase 4)

    def review_doc(self, doc_id: str) -> Document:
        """The document as the reviewer sees it: the reviewed stage if any, else the formatted one."""
        doc = self.load_doc(doc_id, "reviewed") or self.load_doc(doc_id, "formatted")
        if doc is None:
            raise ValueError(f"{doc_id} is not ready for review")
        return doc

    def rerun(self, doc_id: str, agent: str, blocks: list[str], instruction: str = "", by: str = "") -> int:
        """Run one agent again on selected blocks of a document under review. Agent changes are recorded in
        the block history (accept/reject in the editor); the result is saved as the reviewed stage."""
        if agent not in RERUN_AGENTS:
            raise ValueError(f"agent must be one of {sorted(RERUN_AGENTS)}")
        doc = self.review_doc(doc_id)
        known = {b.id for b in steps.translatable(doc)}
        only = {b for b in blocks if b in known}
        if not only:
            raise ValueError("no translatable blocks selected")
        ctx = self.ctx(doc.source_language, doc.target_language, doc_id)
        self.event("rerun_started", document=doc_id, agent=agent, blocks=sorted(only), by=by)
        before = sum(len(b.history) for b in doc.blocks)
        if agent == "translator":
            steps.translate(ctx, doc, only=only,
                            fix_requests={b: [instruction.strip()] for b in only} if instruction.strip() else None)
        elif agent == "proofreader":
            steps.proofread(ctx, doc, only=only, instruction=instruction)
        else:
            steps.qa(ctx, doc, only=only, instruction=instruction)
        changes = sum(len(b.history) for b in doc.blocks) - before
        self.save_doc(doc, "reviewed")
        self.event("rerun_done", document=doc_id, agent=agent, blocks=sorted(only), changes=changes, by=by)
        return changes

    def build_preview(self, doc_id: str) -> Path:
        """A watermarked PDF of the document as it would be released, with the chosen stamp.

        Built in a temporary folder; only the watermarked PDF is kept, so no valid stamped copy
        exists before approval. Rebuilt only when the document changed since the last preview."""
        import shutil
        import tempfile

        from ..builder.pdf_builder import add_watermark
        d = next((x for x in self.meta["documents"] if x["id"] == doc_id), None)
        if d is None:
            raise ValueError(f"no document {doc_id}")
        src = self.doc_path(doc_id, "reviewed")
        src = src if src.exists() else self.doc_path(doc_id, "formatted")
        out = self.dir / "preview" / f"{doc_id}.preview.pdf"
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            return out
        doc = self.review_doc(doc_id)
        lib = AssetLibrary(Path(self.meta["library"]))
        out.parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cf_preview_") as td:
            res = build_package(doc, Path(d["source"]), self.spec, lib, Path(td))
            add_watermark(res.pdf, PREVIEW_WATERMARK)
            tmp = out.with_suffix(".tmp")
            shutil.copy(res.pdf, tmp)
            tmp.replace(out)
        self.event("preview_built", document=doc_id)
        return out

    # ----------------------------------------------------------------- graph

    def _parallel(self, fn) -> None:
        docs = self.meta["documents"]
        with ThreadPoolExecutor(max_workers=max(1, min(len(docs), self.settings.pipeline.max_parallel_documents))) as ex:
            list(ex.map(fn, docs))

    def graph(self, checkpointer):
        g = StateGraph(JobState)
        g.add_node("intake_all", self.n_intake_all)
        g.add_node("glossary", self.n_glossary)
        g.add_node("confirm_glossary", self.n_confirm_glossary)
        g.add_node("process_all", self.n_process_all)
        g.add_node("review", self.n_review)
        g.add_node("release", self.n_release)
        g.add_edge(START, "intake_all")
        g.add_edge("intake_all", "glossary")
        g.add_edge("glossary", "confirm_glossary")
        g.add_edge("confirm_glossary", "process_all")
        g.add_edge("process_all", "review")
        g.add_edge("review", "release")
        g.add_edge("release", END)
        return g.compile(checkpointer=checkpointer)

    def run(self, resume: Any = None, checkpoint_dsn: str | None = None) -> dict:
        """Run until the next human gate (or the end). ``resume`` answers the pending gate.
        Checkpoints go to PostgreSQL when ``checkpoint_dsn`` is given, else to a SQLite file in the job dir."""
        if checkpoint_dsn:
            from langgraph.checkpoint.postgres import PostgresSaver
            with PostgresSaver.from_conn_string(checkpoint_dsn) as saver:
                saver.setup()
                return self._run(self.graph(saver), resume)
        conn = sqlite3.connect(str(self.dir / "checkpoints.sqlite"), check_same_thread=False)
        try:
            return self._run(self.graph(SqliteSaver(conn)), resume)
        finally:
            conn.close()

    def _run(self, graph, resume: Any) -> dict:
        cfg = {"configurable": {"thread_id": self.dir.name}}
        inp = Command(resume=resume) if resume is not None else (
            None if graph.get_state(cfg).next else {"job_dir": str(self.dir), "stage": "created"})
        result = graph.invoke(inp, cfg)
        snap = graph.get_state(cfg)
        waiting = [i.value for t in snap.tasks for i in (t.interrupts or [])]
        return {"stage": result.get("stage"), "waiting": waiting, "next": list(snap.next),
                "released": result.get("released")}

    def status(self) -> dict:
        docs = {}
        for d in self.meta["documents"]:
            stages = [s for s in ("intake", "translated", "proofread", "qa", "formatted", "reviewed")
                      if self.doc_path(d["id"], s).exists()]
            doc = self.load_doc(d["id"], stages[-1]) if stages else None
            flags = {}
            if doc:
                for b in doc.blocks:
                    for f in b.flags:
                        if not f.resolved:
                            flags[f.severity.value] = flags.get(f.severity.value, 0) + 1
            docs[d["id"]] = {"title": d["title"], "stage": stages[-1] if stages else "queued",
                             "blocks": len(doc.blocks) if doc else 0, "open_flags": flags}
        return {"job": self.dir.name, "documents": docs, "cost": self.audit_totals()}

    def audit_totals(self) -> dict:
        tot: dict = {}
        p = self.dir / "audit.jsonl"
        if not p.exists():
            return tot
        for line in p.read_text("utf-8").splitlines():
            r = json.loads(line)
            if r.get("kind") != "llm_call":
                continue
            a = tot.setdefault(r["agent"], {"calls": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0})
            a["calls"] += 1
            a["cost_usd"] = round(a["cost_usd"] + r["cost_usd"], 6)
            a["input_tokens"] += r["usage"].get("input_tokens", 0)
            a["output_tokens"] += r["usage"].get("output_tokens", 0)
        return tot
