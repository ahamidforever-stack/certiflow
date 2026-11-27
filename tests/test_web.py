"""Phase 3 web API: auth, stamp rules, job lifecycle through the human gates, SSE, downloads, isolation."""
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from certiflow import samples
from certiflow.web.auth import hash_password
from certiflow.web.config import WebConfig
from certiflow.web.db import Base, User, engine_for, session_factory

needs_tools = pytest.mark.skipif(shutil.which("tesseract") is None or shutil.which("soffice") is None,
                                 reason="tesseract and LibreOffice required")
H = {"X-CertiFlow": "1"}
PW = "correct-horse-battery"


@pytest.fixture()
def web(tmp_path, lib_dir, monkeypatch):
    cfg = WebConfig(data_dir=tmp_path / "data", library=lib_dir / "library.json", llm="mock", queue="thread",
                    static_dir=tmp_path / "nostatic")
    Base.metadata.create_all(engine_for(cfg.database_url))
    with session_factory(cfg.database_url)() as s:
        for name, role in (("translator1", "certified_translator"), ("reviewer1", "reviewer"),
                           ("admin", "admin"), ("translator2", "certified_translator")):
            s.add(User(username=name, name=name.title(), role=role, password_hash=hash_password(PW)))
        s.commit()
    from certiflow.web import runner
    monkeypatch.setattr(runner, "_pool", None)
    from certiflow.web.app import create_app
    return cfg, create_app(cfg)


def client(app, user=None) -> TestClient:
    c = TestClient(app)
    if user:
        r = c.post("/api/auth/login", json={"username": user, "password": PW}, headers=H)
        assert r.status_code == 200, r.text
    return c


def wait_status(c, job_id, wanted, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in wanted:
            return j
        if j["status"] == "failed":
            raise AssertionError(j["error"])
        time.sleep(0.5)
    raise AssertionError(f"timeout waiting for {wanted}; last {j['status']}")


@pytest.fixture(scope="module")
def src_pdf(tmp_path_factory):
    return samples.make_source_pdf(tmp_path_factory.mktemp("w") / "certificate.pdf")


def test_auth_and_csrf(web):
    cfg, app = web
    c = TestClient(app)
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/auth/login", json={"username": "translator1", "password": PW}).status_code == 403  # no header
    assert c.post("/api/auth/login", json={"username": "translator1", "password": "nope"}, headers=H).status_code == 401
    c = client(app, "translator1")
    me = c.get("/api/me").json()
    assert me["role"] == "certified_translator"
    cookie = c.cookies.get("cf_session")
    assert cookie and "." in cookie
    assert c.post("/api/auth/logout", headers=H).status_code == 200


def test_reference_endpoints(web):
    cfg, app = web
    c = client(app, "translator1")
    langs = c.get("/api/languages").json()
    assert {"ar", "en", "fr", "zh", "he"} <= {l["code"] for l in langs}
    assert next(l for l in langs if l["code"] == "ar")["direction"] == "rtl"
    st = {s["choice"]: s for s in c.get("/api/stamps").json()}
    assert st["certified"]["available"] and st["office"]["available"]
    assert c.get("/api/stamps/certified/image").headers["content-type"] == "image/png"
    r = client(app, "reviewer1").get("/api/stamps").json()
    assert not any(s["available"] for s in r)          # a reviewer owns no stamp/signature


@needs_tools
def test_stamp_is_required_and_checked(web, src_pdf):
    cfg, app = web
    c = client(app, "translator1")
    files = {"files": ("certificate.pdf", src_pdf.read_bytes(), "application/pdf")}
    r = c.post("/api/jobs", data={"source_language": "en", "target_language": "ar"}, files=files, headers=H)
    assert r.status_code == 422 and "stamp" in r.text
    r = client(app, "reviewer1").post("/api/jobs", data={"source_language": "en", "target_language": "ar",
                                                         "stamp": "certified"}, files=files, headers=H)
    assert r.status_code == 403
    r = c.post("/api/jobs", data={"source_language": "en", "target_language": "en", "stamp": "office"},
               files=files, headers=H)
    assert r.status_code == 422
    r = c.post("/api/jobs", data={"source_language": "en", "target_language": "ar", "stamp": "office"},
               files={"files": ("x.exe", b"MZ", "application/octet-stream")}, headers=H)
    assert r.status_code == 422


@needs_tools
def test_full_job_lifecycle(web, src_pdf):
    cfg, app = web
    c = client(app, "translator1")
    r = c.post("/api/jobs", data={"source_language": "en", "target_language": "ar", "stamp": "certified",
                                  "document_type": "certificate"},
               files={"files": ("certificate.pdf", src_pdf.read_bytes(), "application/pdf")}, headers=H)
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    j = wait_status(c, jid, {"waiting_glossary"})
    assert j["documents"][0]["stage"] == "intake"
    g = c.get(f"/api/jobs/{jid}/glossary").json()
    assert g["confirmed"] is False
    items = [{"source": "Blue Harbour Trading LLC", "target": "بلو هاربر للتجارة ش.ذ.م.م", "kind": "organisation"}]
    assert c.post(f"/api/jobs/{jid}/glossary/confirm", json={"items": items}, headers=H).status_code == 200
    j = wait_status(c, jid, {"waiting_review"})
    assert j["documents"][0]["stage"] == "formatted"
    assert c.get(f"/api/jobs/{jid}/glossary").json()["confirmed"] is True
    assert j["files"] == []                                       # nothing downloadable before release
    assert c.get(f"/api/jobs/{jid}/files/anything.pdf").status_code == 409
    model = c.get(f"/api/jobs/{jid}/documents/d01").json()
    assert model["stage"] == "formatted" and model["model"]["blocks"]
    # a different certified translator cannot see or approve this job
    other = client(app, "translator2")
    assert other.get(f"/api/jobs/{jid}").status_code == 404
    assert other.post(f"/api/jobs/{jid}/approve", json={}, headers=H).status_code == 404
    assert c.post(f"/api/jobs/{jid}/approve", json={"note": "checked"}, headers=H).status_code == 200
    j = wait_status(c, jid, {"released"})
    names = {f["name"] for f in j["files"]}
    assert any(n.endswith("_AR.pdf") for n in names) and any(n.endswith("_AR.docx") for n in names)
    assert "disclosures.txt" in names
    pdf = next(n for n in names if n.endswith(".pdf"))
    d = c.get(f"/api/jobs/{jid}/files/{pdf}")
    assert d.status_code == 200 and d.content[:4] == b"%PDF"
    assert c.get(f"/api/jobs/{jid}/files/..%2F..%2Fjob.json").status_code == 404
    assert j["approved_at"] and j["cost_usd"] == 0.0           # mock client costs nothing
    # admin sees every job; the list shows it
    assert any(x["id"] == jid for x in client(app, "admin").get("/api/jobs").json())
    # SSE: replays progress and ends with the final status; never carries document text
    with c.stream("GET", f"/api/jobs/{jid}/events") as s:
        body = "".join(s.iter_text())
    assert "event: progress" in body and '"status": "released"' in body and "event: end" in body
    assert "Blue Harbour" not in body and '"prompt"' not in body and '"response"' not in body


@needs_tools
def test_word_source_and_per_document_languages(web, tmp_path):
    from docx import Document as D
    cfg, app = web
    d = D()
    d.add_paragraph("CERTIFICAT (EXEMPLE)")
    d.add_paragraph("Nom : Claire Dubois")
    d.add_paragraph("Numéro : FR-2026-00873")
    p = tmp_path / "attestation.docx"
    d.save(str(p))
    en = samples.make_source_pdf(tmp_path / "en.pdf", landscape_pages=())
    c = client(app, "translator1")
    r = c.post("/api/jobs", data={"source_language": "en", "target_language": "ar", "stamp": "office",
                                  "overrides": '{"1": {"source_language": "fr", "target_language": "en"}}'},
               files=[("files", ("en.pdf", en.read_bytes(), "application/pdf")),
                      ("files", ("attestation.docx", p.read_bytes(),
                                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
               headers=H)
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    j = wait_status(c, jid, {"waiting_glossary"})
    pairs = [(x["source_language"], x["target_language"]) for x in j["documents"]]
    assert pairs == [("en", "ar"), ("fr", "en")]
    c.post(f"/api/jobs/{jid}/glossary/confirm", json={"items": []}, headers=H)
    wait_status(c, jid, {"waiting_review"})
    c.post(f"/api/jobs/{jid}/approve", json={}, headers=H)
    j = wait_status(c, jid, {"released"})
    names = {f["name"] for f in j["files"]}
    assert any(n.endswith("_AR.pdf") for n in names) and any(n.endswith("_EN.pdf") for n in names)
    assert any(n.endswith(".zip") for n in names)


def _to_review(c, src_pdf):
    r = c.post("/api/jobs", data={"source_language": "en", "target_language": "ar", "stamp": "certified"},
               files={"files": ("certificate.pdf", src_pdf.read_bytes(), "application/pdf")}, headers=H)
    jid = r.json()["id"]
    wait_status(c, jid, {"waiting_glossary"})
    c.post(f"/api/jobs/{jid}/glossary/confirm", json={"items": []}, headers=H)
    wait_status(c, jid, {"waiting_review"})
    return jid


def test_review_edit_flags_changes_and_gate(web, src_pdf):
    """Phase 4: edits write <doc>.reviewed.json with history; blockers stop approval until resolved."""
    import json as _json

    from certiflow.model import Document, Flag, HistoryEntry, Severity
    from certiflow.web import runner
    cfg, app = web
    c = client(app, "translator1")
    jid = _to_review(c, src_pdf)
    base = f"/api/jobs/{jid}/documents/d01"
    model = c.get(base).json()["model"]
    text_block = next(b for b in model["blocks"] if not b.get("rows") and b.get("translated_text"))
    table = next((b for b in model["blocks"] if b.get("rows")), None)

    # edit a paragraph: needs the CSRF header, records history, writes the reviewed stage
    assert c.put(f"{base}/blocks/{text_block['id']}", json={"text": "نص مراجع"}).status_code == 403
    r = c.put(f"{base}/blocks/{text_block['id']}", json={"text": "نص مراجع", "reason": "style"}, headers=H)
    assert r.status_code == 200, r.text
    b = next(x for x in r.json()["model"]["blocks"] if x["id"] == text_block["id"])
    assert b["translated_text"] == "نص مراجع" and b["history"][-1]["actor"] == "translator1"
    assert c.get(base).json()["stage"] == "reviewed"
    assert all(len(x["bbox"]) == 4 for x in model["blocks"] if x["source_page"])      # positions from intake
    assert c.put(f"{base}/blocks/nope", json={"text": "x"}, headers=H).status_code == 422
    if table:
        r = c.put(f"{base}/blocks/{table['id']}", json={"cells": [{"row": 0, "col": 0, "text": "خلية"}]}, headers=H)
        assert r.status_code == 200, r.text
        assert c.put(f"{base}/blocks/{table['id']}", json={"text": "x"}, headers=H).status_code == 422

    # plant an agent change and a blocker in the reviewed file (the mock agents produce neither reliably)
    p = runner.job_dir(cfg, jid) / "docs" / "d01.reviewed.json"
    doc = Document.model_validate_json(p.read_text("utf-8"))
    blk = next(x for x in doc.blocks if x.id == text_block["id"])
    blk.history.append(HistoryEntry(actor="proofreader", old="نص مراجع", new="نص مصحح", reason="grammar: x"))
    blk.translated_text = "نص مصحح"
    blk.flags.append(Flag(code="number_mismatch", severity=Severity.blocker, message="m", agent="qa"))
    p.write_text(doc.model_dump_json(exclude_defaults=True), "utf-8")
    ci, fi = len(blk.history) - 1, len(blk.flags) - 1

    # reject restores the old text; a second decision conflicts
    r = c.post(f"{base}/blocks/{blk.id}/changes/{ci}/reject", headers=H)
    assert r.status_code == 200, r.text
    b = next(x for x in r.json()["model"]["blocks"] if x["id"] == blk.id)
    assert b["translated_text"] == "نص مراجع" and b["history"][ci]["review"] == "rejected"
    assert c.post(f"{base}/blocks/{blk.id}/changes/{ci}/accept", headers=H).status_code == 409
    assert c.post(f"{base}/blocks/{blk.id}/changes/0/maybe", headers=H).status_code == 404

    # approval is refused while the blocker is open; resolving needs a comment
    r = c.post(f"/api/jobs/{jid}/approve", json={}, headers=H)
    assert r.status_code == 409 and blk.id in r.json()["detail"]
    assert c.post(f"{base}/blocks/{blk.id}/flags/{fi}/resolve", json={"comment": " "}, headers=H).status_code == 422
    r = c.post(f"{base}/blocks/{blk.id}/flags/{fi}/resolve", json={"comment": "figure checked"}, headers=H)
    assert r.status_code == 200 and r.json()["open_blockers"] == []
    f = next(x for x in r.json()["model"]["blocks"] if x["id"] == blk.id)["flags"][fi]
    assert f["resolved"] and f["resolved_by"] == "translator1" and f["resolution"] == "figure checked"

    # audit: review records carry ids only, never the text
    audit = [_json.loads(x) for x in (runner.job_dir(cfg, jid) / "audit.jsonl").read_text("utf-8").splitlines()]
    rec = [a for a in audit if a.get("kind", "").startswith("review_")]
    assert {a["kind"] for a in rec} >= {"review_edit", "review_change", "review_flag"}
    assert not any("نص" in _json.dumps(a, ensure_ascii=False) for a in rec)

    # another translator cannot edit; after approval, editing is closed and the release uses the reviewed text
    assert client(app, "translator2").put(f"{base}/blocks/{blk.id}", json={"text": "x"}, headers=H).status_code == 404
    assert c.post(f"/api/jobs/{jid}/approve", json={}, headers=H).status_code == 200
    wait_status(c, jid, {"released"})
    assert c.put(f"{base}/blocks/{blk.id}", json={"text": "x"}, headers=H).status_code == 409


def test_source_page_image(web, src_pdf):
    cfg, app = web
    c = client(app, "translator1")
    r = c.post("/api/jobs", data={"source_language": "en", "target_language": "ar", "stamp": "certified"},
               files={"files": ("certificate.pdf", src_pdf.read_bytes(), "application/pdf")}, headers=H)
    jid = r.json()["id"]
    wait_status(c, jid, {"waiting_glossary"})
    r = c.get(f"/api/jobs/{jid}/documents/d01/pages/1.png")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert c.get(f"/api/jobs/{jid}/documents/d01/pages/1.png").content == r.content   # cached copy
    assert c.get(f"/api/jobs/{jid}/documents/d01/pages/99.png").status_code == 404
    assert c.get(f"/api/jobs/{jid}/documents/d09/pages/1.png").status_code == 404
    assert client(app, "translator2").get(f"/api/jobs/{jid}/documents/d01/pages/1.png").status_code == 404


def test_intake_bbox_is_kept_and_checked():
    from certiflow.agents.contracts import SourceBlockOut
    from certiflow.agents.steps import _bbox, _to_block
    assert _bbox([10, 20, 500, 60]) == [10.0, 20.0, 500.0, 60.0]
    assert _bbox([-5, 20, 1200, 60]) == [0.0, 20.0, 1000.0, 60.0]           # clamped to the grid
    assert _bbox([500, 20, 10, 60]) is None and _bbox([1, 2, 3]) is None and _bbox(None) is None
    sb = SourceBlockOut(type="paragraph", level=None, label=None, text="x", rows=None, header_row=False,
                        note_kind=None, note_description=None, unreadable_reason=None, confidence=0.9,
                        continues_previous_page=False, multilingual_duplicate=False, repeated_on_every_page=False,
                        bbox=[100, 200, 900, 260])
    assert _to_block(sb, "p1b01", 1).bbox == [100.0, 200.0, 900.0, 260.0]
    assert SourceBlockOut.model_validate({**sb.model_dump(), "bbox": None}).bbox is None   # v1 output still valid


def test_rerun_agent_on_selected_blocks(web, src_pdf):
    """Phase 4: re-run one agent on chosen blocks; the job pauses edits (reworking) and returns to review."""
    import json as _json

    from certiflow.web import runner
    cfg, app = web
    c = client(app, "translator1")
    jid = _to_review(c, src_pdf)
    base = f"/api/jobs/{jid}/documents/d01"
    blocks = [b for b in c.get(base).json()["model"]["blocks"] if not b.get("rows") and b.get("translated_text")]
    target = blocks[1]["id"]
    # a reviewer edit, then the translator again on that block: its change is tracked for accept/reject
    c.put(f"{base}/blocks/{target}", json={"text": "نص المراجع"}, headers=H)
    assert c.post(f"{base}/rerun", json={"agent": "formatter", "blocks": [target]}, headers=H).status_code == 422
    assert c.post(f"{base}/rerun", json={"agent": "translator", "blocks": []}, headers=H).status_code == 422
    r = c.post(f"{base}/rerun", json={"agent": "translator", "blocks": [target], "instruction": "use formal register"},
               headers=H)
    assert r.status_code == 202, r.text
    wait_status(c, jid, {"waiting_review"})
    j = c.get(f"/api/jobs/{jid}").json()
    assert j["error"] is None
    b = next(x for x in c.get(base).json()["model"]["blocks"] if x["id"] == target)
    last = b["history"][-1]
    assert last["actor"] == "translator" and last["old"] == "نص المراجع" and b["translated_text"] != "نص المراجع"
    idx = len(b["history"]) - 1
    r = c.post(f"{base}/blocks/{target}/changes/{idx}/reject", headers=H)
    assert next(x for x in r.json()["model"]["blocks"] if x["id"] == target)["translated_text"] == "نص المراجع"
    # QA re-run keeps a resolution the reviewer already recorded
    assert c.post(f"{base}/rerun", json={"agent": "qa", "blocks": [target]}, headers=H).status_code == 202
    wait_status(c, jid, {"waiting_review"})
    assert c.post(f"{base}/rerun", json={"agent": "proofreader", "blocks": [target]}, headers=H).status_code == 202
    wait_status(c, jid, {"waiting_review"})
    # audit has the re-run with ids only; SSE never carries the instruction
    audit = [_json.loads(x) for x in (runner.job_dir(cfg, jid) / "audit.jsonl").read_text("utf-8").splitlines()]
    assert any(a.get("kind") == "rerun_done" and a["blocks"] == [target] for a in audit)
    with c.stream("GET", f"/api/jobs/{jid}/events") as s:
        for line in s.iter_lines():
            assert "formal register" not in line
            if "rerun_done" in line:
                break


def test_rerun_refused_outside_review(web, src_pdf):
    cfg, app = web
    c = client(app, "translator1")
    r = c.post("/api/jobs", data={"source_language": "en", "target_language": "ar", "stamp": "certified"},
               files={"files": ("certificate.pdf", src_pdf.read_bytes(), "application/pdf")}, headers=H)
    jid = r.json()["id"]
    wait_status(c, jid, {"waiting_glossary"})
    r = c.post(f"/api/jobs/{jid}/documents/d01/rerun", json={"agent": "qa", "blocks": ["p1b01"]}, headers=H)
    assert r.status_code == 409
    assert c.get(f"/api/jobs/{jid}/documents/d01/preview.pdf").status_code == 409


@needs_tools
def test_preview_is_watermarked_and_not_a_release(web, src_pdf):
    from pypdf import PdfReader
    cfg, app = web
    c = client(app, "translator1")
    jid = _to_review(c, src_pdf)
    r = c.get(f"/api/jobs/{jid}/documents/d01/preview.pdf")
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF" and "inline" in r.headers["content-disposition"]
    from certiflow.web import runner
    jd = runner.job_dir(cfg, jid)
    pdf = jd / "preview" / "d01.preview.pdf"
    assert all("PREVIEW" in (p.extract_text() or "") for p in PdfReader(str(pdf)).pages)
    assert not (jd / "release").exists()                                   # nothing released
    assert sorted(x.name for x in (jd / "preview").iterdir()) == ["d01.preview.pdf"]   # no unwatermarked copy
    m1 = pdf.stat().st_mtime
    assert c.get(f"/api/jobs/{jid}/documents/d01/preview.pdf").status_code == 200
    assert pdf.stat().st_mtime == m1                                       # cached until the next edit
    assert client(app, "translator2").get(f"/api/jobs/{jid}/documents/d01/preview.pdf").status_code == 404


def test_audit_log_has_actions_but_no_document_text(web, src_pdf):
    cfg, app = web
    c = client(app, "translator1")
    jid = _to_review(c, src_pdf)
    base = f"/api/jobs/{jid}/documents/d01"
    bid = next(b["id"] for b in c.get(base).json()["model"]["blocks"] if not b.get("rows") and b.get("translated_text"))
    c.put(f"{base}/blocks/{bid}", json={"text": "نص سري للمراجعة"}, headers=H)
    r = c.get(f"/api/jobs/{jid}/audit")
    assert r.status_code == 200
    recs = r.json()["records"]
    kinds = [x["kind"] for x in recs]
    assert kinds[0] == "created" and recs[0]["by"] == "translator1"
    assert {"llm_call", "stage_done", "glossary_confirmed", "status", "review_edit"} <= set(kinds)
    call = next(x for x in recs if x["kind"] == "llm_call")
    assert call["model"] and call["prompt_version"] and "usage" in call
    assert [x["at"] for x in recs] == sorted(x["at"] for x in recs)
    body = r.text
    assert "prompt" not in {k for x in recs for k in x if k != "prompt_version"} and '"response"' not in body
    assert "Blue Harbour" not in body and "نص سري" not in body
    assert client(app, "translator2").get(f"/api/jobs/{jid}/audit").status_code == 404
    assert client(app, "admin").get(f"/api/jobs/{jid}/audit").status_code == 200
