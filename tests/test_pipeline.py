"""Phase 2: agents + LangGraph pipeline, offline on the mock client (real OCR, real Builder)."""
import json
import shutil
from pathlib import Path

import pytest

from certiflow import samples
from certiflow.agents.contracts import (FormatterOut, GlossaryOut, IntakePageOut, ProofreaderOut, QAOut, TranslatorOut,
                                        ZoomOut)
from certiflow.builder.package import ReleaseBlocked
from certiflow.llm.client import LLMError, strict_schema
from certiflow.llm.mock_agents import make_mock
from certiflow.model import Document, JobSpec, Severity
from certiflow.pipeline.job import Job

from .conftest import requires_soffice

needs_tools = pytest.mark.skipif(shutil.which("tesseract") is None or shutil.which("soffice") is None,
                                 reason="tesseract and LibreOffice required")

FR_PAGES = [["CERTIFICAT DE RÉSIDENCE (EXEMPLE)",
             "Nom : Claire Dubois",
             "Numéro : FR-2026-00873",
             "Date : 12/09/2026",
             "",
             "Nous certifions que la personne susnommée réside à Lyon depuis 2019.",
             "Le maire"]]


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    d = tmp_path_factory.mktemp("srcs")
    return {"en": samples.make_source_pdf(d / "en.pdf"),
            "ar": samples.make_rtl_source_pdf(d / "ar.pdf"),
            "fr": samples.make_source_pdf(d / "fr.pdf", pages=FR_PAGES, landscape_pages=())}


def _run_job(tmp_path, lib_dir, src, s, t, client, stamp="certified", user="translator1"):
    jd = Job.create(tmp_path / "job", [src], s, t, JobSpec(stamp=stamp, user_id=user), lib_dir / "library.json")
    job = Job(jd, client)
    r1 = job.run()
    assert [w["waiting_for"] for w in r1["waiting"]] == ["glossary_confirmation"]
    r2 = job.run(resume={"by": user})
    assert [w["waiting_for"] for w in r2["waiting"]] == ["final_review"]
    return job, r2


def test_contract_schemas_are_strict():
    for m in (IntakePageOut, ZoomOut, GlossaryOut, TranslatorOut, ProofreaderOut, QAOut, FormatterOut):
        s = json.dumps(strict_schema(m))
        assert '"additionalProperties": false' in s
        for node in _objects(strict_schema(m)):
            assert set(node["required"]) == set(node.get("properties", {}))


def _objects(n):
    if isinstance(n, dict):
        if "properties" in n:
            yield n
        for v in n.values():
            yield from _objects(v)
    elif isinstance(n, list):
        for v in n:
            yield from _objects(v)


@needs_tools
@pytest.mark.parametrize("src,tgt", [("en", "ar"), ("ar", "en"), ("fr", "en")])
def test_pipeline_end_to_end_pairs(src, tgt, sources, lib_dir, tmp_path):
    job, _ = _run_job(tmp_path, lib_dir, sources[src], src, tgt, make_mock(tgt))
    doc = job.load_doc("d01", "formatted")
    assert doc.source_language == src and doc.target_language == tgt
    assert doc.blocks and all(b.translated_text or b.rows for b in doc.blocks if b.type.value != "page_break")
    r = job.run(resume={"approved_by": "translator1"})
    assert r["stage"] == "released"
    pdf = Path(r["released"][0])
    assert pdf.exists() and pdf.name.endswith(f"_{tgt.upper()}.pdf")
    agents = {json.loads(l).get("agent") for l in (job.dir / "audit.jsonl").read_text("utf-8").splitlines()}
    assert {"intake", "glossary", "translator", "proofreader", "qa", "formatter"} <= agents
    rec = [json.loads(l) for l in (job.dir / "audit.jsonl").read_text("utf-8").splitlines()]
    calls = [x for x in rec if x["kind"] == "llm_call"]
    assert all({"model", "prompt_version", "usage", "cost_usd", "latency_s", "retries"} <= set(c) for c in calls)
    assert any(x["kind"] == "approved" and x["by"] == "translator1" for x in rec)
    assert any(x["kind"] == "released" and x["stamp_choice"] == "certified" for x in rec)


@needs_tools
def test_qa_loop_fixes_corrupted_figure(sources, lib_dir, tmp_path):
    mock = make_mock("ar", corrupt_once={"p1b03"})
    job, r = _run_job(tmp_path, lib_dir, sources["en"], "en", "ar", mock)
    rec = [json.loads(l) for l in (job.dir / "audit.jsonl").read_text("utf-8").splitlines()]
    loops = [x for x in rec if x["kind"] == "qa_loop"]
    assert loops and "p1b03" in loops[0]["blocks"]
    doc = job.load_doc("d01", "formatted")
    b = next(b for b in doc.blocks if b.id == "p1b03")
    assert "999" not in b.translated_text
    assert not any(f.severity == Severity.blocker and not f.resolved for f in b.flags)
    assert any(h.reason == "fix" for h in b.history)


@needs_tools
def test_unresolved_blocker_blocks_release(sources, lib_dir, tmp_path):
    always = [{"id": "p1b01", "severity": "blocker", "code": "wrong_meaning", "message": "title mistranslated",
               "suggested_fix": None}]
    job, _ = _run_job(tmp_path, lib_dir, sources["en"], "en", "ar", make_mock("ar", qa_issues=always))
    loops = [json.loads(l) for l in (job.dir / "audit.jsonl").read_text("utf-8").splitlines()
             if json.loads(l)["kind"] == "qa_loop"]
    assert len(loops) == 2                               # max 2 loops, then flagged for the human
    doc = job.load_doc("d01", "formatted")
    assert next(b for b in doc.blocks if b.id == "p1b01").status.value == "needs_review"
    with pytest.raises(ReleaseBlocked):
        job.run(resume={"approved_by": "translator1"})
    # the reviewer resolves the flag in review; release then goes through
    for b in doc.blocks:
        for f in b.flags:
            f.resolved = True
    job.save_doc(doc, "reviewed")
    r = job.run(resume={"approved_by": "translator1"})
    assert r["stage"] == "released"


@needs_tools
def test_only_certified_translator_can_approve(sources, lib_dir, tmp_path):
    job, _ = _run_job(tmp_path, lib_dir, sources["en"], "en", "ar", make_mock("ar"))
    with pytest.raises(ReleaseBlocked):
        job.run(resume={"approved_by": "reviewer1"})


@needs_tools
def test_crash_resumes_at_failed_stage(sources, lib_dir, tmp_path):
    mock = make_mock("ar")
    good = mock.handlers["translator"]
    state = {"fail": True}

    def flaky(req):
        if state["fail"]:
            state["fail"] = False
            raise LLMError("simulated outage")
        return good(req)
    mock.handlers["translator"] = flaky
    jd = Job.create(tmp_path / "job", [sources["en"]], "en", "ar", JobSpec(stamp="office", user_id="translator1"),
                    lib_dir / "library.json")
    job = Job(jd, mock)
    job.run()
    with pytest.raises(LLMError):
        job.run(resume={"by": "translator1"})
    intake_calls = sum(1 for c in mock.calls if c.agent == "intake")
    r = Job(jd, mock).run()                               # resume after the crash
    assert [w["waiting_for"] for w in r["waiting"]] == ["final_review"]
    assert sum(1 for c in mock.calls if c.agent == "intake") == intake_calls   # intake not redone


def test_anthropic_client_request_shape(monkeypatch):
    """The real client, against a fake SDK: settings-driven model, structured output, effort, adaptive
    thinking, cached system prompt, refusal fallback, and a validation retry that echoes the reply."""
    import types
    from certiflow.llm import client as cl

    sent = []

    class FakeMsg:
        def __init__(self, text):
            self.content = [types.SimpleNamespace(type="text", text=text)]
            self.stop_reason = "end_turn"
            self.model = "claude-opus-5-5"
            self.usage = types.SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                               cache_creation_input_tokens=0)
            self._request_id = "req_test"

    replies = iter(['{"changes": "oops"}', '{"changes": []}'])

    class FakeStream:
        def __init__(self, **kw):
            sent.append(kw)
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def get_final_message(self):
            return FakeMsg(next(replies))

    c = cl.AnthropicClient.__new__(cl.AnthropicClient)
    import anthropic
    c._anthropic = anthropic
    c.fallbacks, c.validation_retries, c.max_backoff_retries = "default", 2, 0
    c.client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(stream=FakeStream)),
                                     messages=types.SimpleNamespace(stream=FakeStream))
    req = cl.LLMRequest(agent="proofreader", system=[cl.SystemBlock("rules", cache=True)], user_text="{}",
                        output=ProofreaderOut, model="claude-opus-5-5", effort="high", max_tokens=1000)
    res = c.call(req)
    assert res.data.changes == [] and res.retries == 1
    k = sent[0]
    assert k["model"] == "claude-opus-5-5" and k["thinking"] == {"type": "adaptive"}
    assert k["output_config"]["effort"] == "high" and k["output_config"]["format"]["type"] == "json_schema"
    assert k["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert k["fallbacks"] == "default" and k["betas"] == ["server-side-fallback-2026-07-01"]
    assert sent[1]["messages"][1]["role"] == "assistant" and sent[1]["messages"][1]["content"][0].text.startswith("{")


def test_units_split_long_documents_by_blocks_and_pages():
    """A 300-page document is split into ordered units of at most 40 blocks and 20 pages, covering every block once."""
    from certiflow.agents.steps import units
    from certiflow.model import Block
    blocks = [Block(id=f"b{i}", type="paragraph", source_page=1 + i // 2, source_text="x") for i in range(600)]  # 2 blocks/page
    us = list(units(blocks, max_blocks=40, max_pages=20))
    assert [b.id for u in us for b in u] == [b.id for b in blocks]            # nothing lost, order kept
    assert all(len(u) <= 40 for u in us)
    assert all(u[-1].source_page - u[0].source_page + 1 <= 20 for u in us)
    sparse = [Block(id=f"s{i}", type="paragraph", source_page=1 + i, source_text="x") for i in range(45)]  # 1 block/page
    su = list(units(sparse, max_blocks=40, max_pages=20))
    assert [len(u) for u in su] == [20, 20, 5]                                # page limit wins on sparse documents


@needs_tools
def test_long_document_is_translated_in_units_and_combined(lib_dir, tmp_path):
    """A 24-page scan is translated in several units but released as one Word file and one PDF."""
    pages = [[f"PAGE {p} (SAMPLE)"] + [f"Clause {p}.{k}: The parties agree to section {p}{k}." for k in range(1, 4)]
             for p in range(1, 25)]
    src = samples.make_source_pdf(tmp_path / "long.pdf", pages=pages, landscape_pages=())
    from certiflow.settings import load
    st = load().model_copy(deep=True)
    st.pipeline.chunk_max_pages = 5
    mock = make_mock("ar")
    jd = Job.create(tmp_path / "job", [src], "en", "ar", JobSpec(stamp="certified", user_id="translator1"),
                    lib_dir / "library.json")
    job = Job(jd, mock, settings=st)
    job.run()
    job.run(resume={"by": "translator1"})
    translator_calls = [c for c in mock.calls if c.agent == "translator"]
    assert len(translator_calls) >= 5                                         # 24 pages / 5 pages per unit
    r = job.run(resume={"approved_by": "translator1"})
    assert r["stage"] == "released" and len([p for p in r["released"] if p.endswith(".pdf")]) == 1
    doc = job.load_doc("d01", "formatted")
    assert {b.source_page for b in doc.blocks} >= set(range(1, 25))          # every page made it into the one document
