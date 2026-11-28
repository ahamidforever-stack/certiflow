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


# ------------------------------------------------------------------ Phase 5: login limits and sessions


def test_login_lockout_after_repeated_failures(web):
    cfg, app = web
    c = TestClient(app)
    for _ in range(cfg.login_max_failures):
        assert c.post("/api/auth/login", json={"username": "reviewer1", "password": "wrong"}, headers=H).status_code == 401
    # locked: even the right password is refused, with a hint when to retry
    r = c.post("/api/auth/login", json={"username": "reviewer1", "password": PW}, headers=H)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    # other users are not affected
    client(app, "translator1")
    # unknown usernames are limited the same way (no hint that the user does not exist)
    for _ in range(cfg.login_max_failures):
        assert c.post("/api/auth/login", json={"username": "nobody", "password": "x"}, headers=H).status_code == 401
    assert c.post("/api/auth/login", json={"username": "nobody", "password": "x"}, headers=H).status_code == 429


def test_success_resets_the_failure_count(web):
    cfg, app = web
    c = TestClient(app)
    for _ in range(cfg.login_max_failures - 1):
        c.post("/api/auth/login", json={"username": "reviewer1", "password": "wrong"}, headers=H)
    assert c.post("/api/auth/login", json={"username": "reviewer1", "password": PW}, headers=H).status_code == 200
    for _ in range(cfg.login_max_failures - 1):
        c.post("/api/auth/login", json={"username": "reviewer1", "password": "wrong"}, headers=H)
    assert c.post("/api/auth/login", json={"username": "reviewer1", "password": PW}, headers=H).status_code == 200


def test_logout_revokes_the_session_server_side(web):
    _, app = web
    c = client(app, "reviewer1")
    stolen = c.cookies.get("cf_session")
    assert c.post("/api/auth/logout", headers=H).status_code == 200
    other = TestClient(app)
    other.cookies.set("cf_session", stolen)
    assert other.get("/api/me").status_code == 401        # the copied cookie is dead too


def test_sign_out_other_devices(web):
    cfg, app = web
    laptop, phone = client(app, "translator1"), client(app, "translator1")
    sessions = laptop.get("/api/me/sessions").json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    assert all(len(s["id"]) == 8 for s in sessions)        # never the full session id
    assert laptop.post("/api/me/sessions/revoke-others", headers=H).json() == {"revoked": 1}
    assert phone.get("/api/me").status_code == 401
    assert laptop.get("/api/me").status_code == 200


def test_deactivated_user_and_old_tokens_are_refused(web):
    cfg, app = web
    from certiflow.web.auth import make_token
    from certiflow.web.db import user_by_username
    c = client(app, "reviewer1")
    with session_factory(cfg.database_url)() as s:
        u = user_by_username(s, "reviewer1")
        u.active = False
        s.commit()
        uid = u.id
    assert c.get("/api/me").status_code == 401
    forged = TestClient(app)                                  # validly signed but no session row
    forged.cookies.set("cf_session", make_token(uid, "made-up", cfg.secret_key, 1))
    assert forged.get("/api/me").status_code == 401


# ------------------------------------------------------------------ Phase 5: admin user management


def _uid(c, username):
    return next(u["id"] for u in c.get("/api/admin/users").json() if u["username"] == username)


def test_admin_only(web):
    _, app = web
    c = client(app, "translator1")
    assert c.get("/api/admin/users").status_code == 403
    assert c.post("/api/admin/users", json={"username": "x1", "name": "X", "role": "admin", "password": PW},
                  headers=H).status_code == 403


def test_admin_creates_edits_and_deactivates_a_user(web):
    _, app = web
    a = client(app, "admin")
    r = a.post("/api/admin/users", json={"username": "New.User", "name": "New User", "role": "reviewer",
                                         "password": "short"}, headers=H)
    assert r.status_code == 422                                   # password too short
    r = a.post("/api/admin/users", json={"username": "New.User", "name": "New User", "role": "reviewer",
                                         "password": PW}, headers=H)
    assert r.status_code == 201 and r.json()["username"] == "new.user" and "password_hash" not in r.json()
    assert a.post("/api/admin/users", json={"username": "new.user", "name": "Again", "role": "reviewer",
                                            "password": PW}, headers=H).status_code == 409
    assert a.post("/api/admin/users", json={"username": "bad name!", "name": "X", "role": "reviewer",
                                            "password": PW}, headers=H).status_code == 422
    nu = client(app, "new.user")
    uid = r.json()["id"]
    r = a.patch(f"/api/admin/users/{uid}", json={"role": "certified_translator", "name": "Renamed"}, headers=H)
    assert r.json()["role"] == "certified_translator" and r.json()["name"] == "Renamed"
    assert r.json()["devices"] == 1 and r.json()["certified_stamp"] is False
    r = a.patch(f"/api/admin/users/{uid}", json={"active": False}, headers=H)
    assert r.json()["active"] is False and r.json()["devices"] == 0
    assert nu.get("/api/me").status_code == 401                   # deactivation signs out at once
    actions = [e["action"] for e in a.get("/api/admin/events").json()]
    assert actions[:3] == ["user_updated", "user_updated", "user_created"]
    assert "password" not in str(a.get("/api/admin/events").json()).lower().replace("password_reset", "")


def test_password_reset_unlock_and_sign_out(web):
    cfg, app = web
    a = client(app, "admin")
    rv_ = client(app, "reviewer1")
    uid = _uid(a, "reviewer1")
    anon = TestClient(app)
    for _ in range(cfg.login_max_failures):
        anon.post("/api/auth/login", json={"username": "reviewer1", "password": "wrong"}, headers=H)
    assert next(u for u in a.get("/api/admin/users").json() if u["id"] == uid)["locked"] is True
    assert a.post(f"/api/admin/users/{uid}/unlock", headers=H).json()["locked"] is False
    assert anon.post("/api/auth/login", json={"username": "reviewer1", "password": PW}, headers=H).status_code == 200
    r = a.post(f"/api/admin/users/{uid}/password", json={"password": "a-brand-new-password"}, headers=H)
    assert r.status_code == 200 and r.json()["devices"] == 0
    assert rv_.get("/api/me").status_code == 401 and anon.get("/api/me").status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"username": "reviewer1", "password": "a-brand-new-password"},
                                headers=H).status_code == 200
    a.post(f"/api/admin/users/{_uid(a, 'translator1')}/sessions/revoke", headers=H)
    # signing out yourself everywhere keeps the browser you are using
    assert a.post(f"/api/admin/users/{_uid(a, 'admin')}/sessions/revoke", headers=H).status_code == 200
    assert a.get("/api/me").status_code == 200


def test_cannot_lock_out_the_last_admin(web):
    _, app = web
    a = client(app, "admin")
    me = _uid(a, "admin")
    assert a.patch(f"/api/admin/users/{me}", json={"active": False}, headers=H).status_code == 409
    assert a.patch(f"/api/admin/users/{me}", json={"role": "reviewer"}, headers=H).status_code == 409
    a.post("/api/admin/users", json={"username": "admin2", "name": "Admin Two", "role": "admin", "password": PW},
           headers=H)
    a2 = client(app, "admin2")
    assert a2.patch(f"/api/admin/users/{me}", json={"role": "reviewer"}, headers=H).status_code == 200
    # admin2 is now the only admin and cannot be demoted by anyone
    assert a2.patch(f"/api/admin/users/{_uid(a2, 'admin2')}", json={"active": False}, headers=H).status_code == 409


# ------------------------------------------------------------------ Phase 5: usage and cost dashboard


def test_usage_rows_follow_the_job_and_dashboard_is_admin_only(web, src_pdf):
    cfg, app = web
    from certiflow.web.db import Job as JobRow
    from certiflow.web.db import LlmUsage
    c = client(app, "translator1")
    jid = _to_review(c, src_pdf)
    with session_factory(cfg.database_url)() as s:
        calls = s.query(LlmUsage).filter_by(job_id=jid).count()
        assert calls > 0 and s.get(JobRow, jid).pages >= 1
    assert c.get("/api/admin/usage").status_code == 403
    a = client(app, "admin")
    r = a.get("/api/admin/usage?days=7").json()
    assert r["total"]["calls"] == calls and r["total"]["jobs"] == 1
    assert len(r["by_day"]) == 7 and sum(d["calls"] for d in r["by_day"]) == calls
    assert {x["agent"] for x in r["by_agent"]} >= {"intake", "translator"}
    assert r["by_user"][0]["username"] == "translator1" and r["top_jobs"][0]["id"] == jid
    assert a.get("/api/admin/usage?days=12").status_code == 422
    assert "text" not in str(r).lower().replace("context", "")       # numbers only


def test_usage_summary_counts_office_days(web):
    """Costs land on the office's calendar day (Dubai = UTC+4), tiles and per-page price add up."""
    from datetime import datetime, timezone

    from certiflow.web.db import Job as JobRow
    from certiflow.web.db import LlmUsage, user_by_username
    from certiflow.web.usage import backfill, summary
    cfg, _ = web
    utc = timezone.utc
    with session_factory(cfg.database_url)() as s:
        uid = user_by_username(s, "translator1").id
        for jid, pages in (("J1", 2), ("J2", None)):
            s.add(JobRow(id=jid, created_by=uid, title=jid, source_language="en", target_language="ar",
                         stamp="certified", pages=pages))
        s.flush()
        for jid, at, cost in (("J1", datetime(2026, 11, 27, 21, 0, tzinfo=utc), 1.0),   # 28 Nov 01:00 in Dubai
                              ("J1", datetime(2026, 11, 27, 19, 0, tzinfo=utc), 0.5),   # 27 Nov 23:00 in Dubai
                              ("J2", datetime(2026, 11, 2, 8, 0, tzinfo=utc), 2.0),     # this month, not this week
                              ("J2", datetime(2026, 10, 30, 8, 0, tzinfo=utc), 4.0)):   # last month
            s.add(LlmUsage(job_id=jid, at=at, agent="translator", model="m", cost_usd=cost, input_tokens=10))
        s.commit()
        now = datetime(2026, 11, 28, 6, 0, tzinfo=utc)                                  # 28 Nov 10:00 Dubai
        r = summary(s, 30, "Asia/Dubai", now=now)
        assert r["tiles"] == {"today": 1.0, "week": 1.5, "month": 3.5}
        days = {d["day"]: d["cost_usd"] for d in r["by_day"]}
        assert days["2026-11-28"] == 1.0 and days["2026-11-27"] == 0.5 and days["2026-10-30"] == 4.0
        assert r["total"]["cost_usd"] == 7.5 and r["per_page_usd"] == 0.75 and r["pages"] == 2
        assert summary(s, 7, "Asia/Dubai", now=now)["total"]["cost_usd"] == 1.5
        assert backfill(s, cfg.jobs_dir) == 0                    # jobs without a folder are left alone


# ------------------------------------------------------------------ Phase 5: asset library administration


@pytest.fixture()
def web_lib(tmp_path, monkeypatch):
    """Like ``web`` but with a private, writable copy of the sample library."""
    lib = tmp_path / "lib"
    samples.make_library(lib)
    cfg = WebConfig(data_dir=tmp_path / "data", library=lib / "library.json", llm="mock", queue="thread",
                    static_dir=tmp_path / "nostatic")
    Base.metadata.create_all(engine_for(cfg.database_url))
    with session_factory(cfg.database_url)() as s:
        for name, role in (("translator1", "certified_translator"), ("admin", "admin"),
                           ("translator2", "certified_translator")):
            s.add(User(username=name, name=name.title(), role=role, password_hash=hash_password(PW)))
        s.commit()
    from certiflow.web import runner
    monkeypatch.setattr(runner, "_pool", None)
    from certiflow.web.app import create_app
    return cfg, create_app(cfg)


def _png_scan(color=(30, 60, 160), alpha=False) -> bytes:
    """A stamp-like test image: coloured ring on white paper (or on a transparent background)."""
    import io

    from PIL import Image, ImageDraw
    im = Image.new("RGBA" if alpha else "RGB", (400, 300), (0, 0, 0, 0) if alpha else (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.ellipse((40, 30, 360, 270), outline=color + ((255,) if alpha else ()), width=14)
    d.text((150, 140), "STAMP", fill=color + ((255,) if alpha else ()))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def test_assets_admin_only_and_sample_library_read_only(web):
    cfg, app = web
    assert client(app, "translator1").get("/api/admin/assets").status_code == 403
    a = client(app, "admin")
    r = a.get("/api/admin/assets").json()
    assert {x["type"] for x in r["assets"]} == {"template", "stamp_certified", "stamp_office", "signature"}
    # the shared test library stands in for the bundled samples: make it look like them
    from certiflow.web import assets_admin as aa
    import pytest as _pt
    with _pt.MonkeyPatch.context() as m:
        m.setattr(aa, "SAMPLES", cfg.library.parent.parent)
        assert a.get("/api/admin/assets").json()["editable"] is False
        r = a.post("/api/admin/assets/image", data={"kind": "stamp_office"},
                   files={"file": ("o.png", _png_scan(), "image/png")}, headers=H)
        assert r.status_code == 409


def test_new_stamp_replaces_old_and_is_used(web_lib):
    from certiflow.assets import AssetLibrary
    from certiflow.model import StampChoice
    cfg, app = web_lib
    a = client(app, "admin")
    # translator2 has no stamp yet
    assert a.post("/api/admin/assets/image", data={"kind": "stamp_certified"},
                  files={"file": ("c.png", _png_scan(), "image/png")}, headers=H).status_code == 422   # no owner
    r = a.post("/api/admin/assets/image", data={"kind": "stamp_certified", "owner": "translator2", "width_mm": "40"},
               files={"file": ("c.png", _png_scan(alpha=True), "image/png")}, headers=H)
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    r = a.post("/api/admin/assets/image", data={"kind": "signature", "owner": "translator2"},
               files={"file": ("s.png", _png_scan((10, 10, 10)), "image/png")}, headers=H)
    assert r.status_code == 201
    lib = AssetLibrary(cfg.library)
    assert any(u.id == "translator2" for u in lib.lib.users)                    # synced from the web account
    st, sig = lib.stamp_for(StampChoice.certified, "translator2")
    assert st.id == new_id and st.width_mm == 40
    from PIL import Image
    with Image.open(lib.path(st)) as im:
        assert im.mode == "RGBA" and im.getpixel((0, 0))[3] == 0                 # transparent background
    # translator2 now sees the stamp as available
    stamps = client(app, "translator2").get("/api/stamps").json()
    assert next(x for x in stamps if x["choice"] == "certified")["available"] is True
    # a replacement switches the previous one off but keeps it
    r2 = a.post("/api/admin/assets/image", data={"kind": "stamp_certified", "owner": "translator2"},
                files={"file": ("c2.png", _png_scan((120, 20, 20)), "image/png")}, headers=H).json()
    assets = {x["id"]: x for x in a.get("/api/admin/assets").json()["assets"]}
    assert assets[new_id]["active"] is False and assets[r2["id"]]["active"] is True
    assert r2["width_mm"] == 40                                                 # print width carried over
    # switching the old one back on switches the newer off
    assert a.patch(f"/api/admin/assets/{new_id}", json={"active": True}, headers=H).json()["active"] is True
    assets = {x["id"]: x for x in a.get("/api/admin/assets").json()["assets"]}
    assert assets[r2["id"]]["active"] is False
    assert a.get(f"/api/admin/assets/{new_id}/file").headers["content-type"] == "image/png"
    assert a.patch("/api/admin/assets/nope", json={"active": True}, headers=H).status_code == 404
    actions = [e["action"] for e in a.get("/api/admin/events").json()]
    assert actions.count("asset_added") == 3 and "asset_updated" in actions


def test_bad_uploads_are_refused(web_lib):
    _, app = web_lib
    a = client(app, "admin")
    r = a.post("/api/admin/assets/image", data={"kind": "stamp_office"},
               files={"file": ("x.png", b"not an image", "image/png")}, headers=H)
    assert r.status_code == 422 and "image" in r.json()["detail"]
    r = a.post("/api/admin/assets/image", data={"kind": "stamp_office", "width_mm": "500"},
               files={"file": ("o.png", _png_scan(), "image/png")}, headers=H)
    assert r.status_code == 422
    r = a.post("/api/admin/assets/template", files={"file": ("t.docx", b"PK not really", "application/zip")}, headers=H)
    assert r.status_code == 422 and "docx" in r.json()["detail"]
    r = a.post("/api/admin/assets/template", data={"pair": "en-ar"},
               files={"file": ("t.docx", b"x", "application/zip")}, headers=H)
    assert r.status_code == 422
    r = a.post("/api/admin/assets/image", data={"kind": "signature", "owner": "admin"},
               files={"file": ("s.png", _png_scan(), "image/png")}, headers=H)
    assert r.status_code == 422                                                 # owner must be a translator


@needs_tools
def test_new_template_is_used_for_the_next_release(web_lib, src_pdf, tmp_path):
    from certiflow.assets import AssetLibrary
    cfg, app = web_lib
    a = client(app, "admin")
    tpl = tmp_path / "t.docx"
    samples.make_template(tpl)
    r = a.post("/api/admin/assets/template", data={"name": "New letterhead", "language": "ar"},
               files={"file": ("t.docx", tpl.read_bytes(), "application/vnd.openxmlformats-officedocument")},
               headers=H)
    assert r.status_code == 201, r.text
    lib = AssetLibrary(cfg.library)
    assert lib.template_for("ar", "en").id == r.json()["id"]
    assert a.get(f"/api/admin/assets/{r.json()['id']}/file").content[:2] == b"PK"


# ------------------------------------------------------------------ Phase 5: glossary memory per client


def _job_for_client(c, src_pdf, client_name):
    r = c.post("/api/jobs", data={"source_language": "en", "target_language": "ar", "stamp": "certified",
                                  "client": client_name},
               files={"files": ("certificate.pdf", src_pdf.read_bytes(), "application/pdf")}, headers=H)
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    wait_status(c, jid, {"waiting_glossary"})
    return jid


def test_glossary_memory_is_reused_for_the_same_client(web, src_pdf):
    _, app = web
    c = client(app, "translator1")
    j1 = _job_for_client(c, src_pdf, "Acme  Corp")
    proposed = c.get(f"/api/jobs/{j1}/glossary").json()["items"]
    assert not any(i["remembered"] for i in proposed)               # the mock proposes nothing: add terms by hand
    model = c.get(f"/api/jobs/{j1}/documents/d01").json()["model"]
    word = next(w for b in model["blocks"] for w in (b.get("source_text") or "").split() if len(w) > 5 and w.isalpha())
    first = {"source": word, "target": "ترجمة المكتب", "kind": "term"}
    items = [first, {"source": "not in the document", "target": "x", "kind": "term"}]
    assert c.post(f"/api/jobs/{j1}/glossary/confirm", json={"items": items}, headers=H).status_code == 200
    assert c.get(f"/api/jobs/{j1}").json()["client"] == "Acme Corp"

    # the same client, typed differently: remembered terms that occur in the document come back confirmed
    j2 = _job_for_client(c, src_pdf, " acme corp ")
    g2 = {i["source"]: i for i in c.get(f"/api/jobs/{j2}/glossary").json()["items"]}
    assert g2[first["source"]]["target"] == "ترجمة المكتب" and g2[first["source"]]["remembered"] is True
    assert g2[first["source"]]["confirmed"] is True
    assert "not in the document" not in g2                         # only terms that occur in this batch
    # another client starts empty
    j3 = _job_for_client(c, src_pdf, "Other Client")
    assert not any(i["remembered"] for i in c.get(f"/api/jobs/{j3}/glossary").json()["items"])

    # the memory screen: overview, edit, delete; reviewers have no access
    assert client(app, "reviewer1").get("/api/glossary-memory").status_code == 403
    ov = c.get("/api/glossary-memory").json()
    acme = next(x for x in ov if x["client"] == "Acme Corp")
    assert acme["pairs"] == [{"source": "en", "target": "ar", "terms": len(items)}]
    terms = c.get("/api/glossary-memory/terms", params={"client": "ACME CORP"}).json()
    t = next(x for x in terms if x["source"] == first["source"])
    assert t["uses"] == 1 and t["job_id"] == j1
    r = c.put(f"/api/glossary-memory/terms/{t['id']}", json={"target": "تصحيح", "kind": "name"}, headers=H)
    assert r.json()["target"] == "تصحيح" and r.json()["kind"] == "name"
    assert c.put(f"/api/glossary-memory/terms/{t['id']}", json={"target": " "}, headers=H).status_code == 422
    junk = next(x for x in terms if x["source"] == "not in the document")
    assert c.delete(f"/api/glossary-memory/terms/{junk['id']}", headers=H).json() == {"ok": True}
    names = c.get("/api/clients").json()
    assert names == ["acme corp", "Other Client"]              # one entry per client, latest spelling


# ------------------------------------------------------------------ Phase 5: model settings


def test_model_settings_overlay_the_defaults(web):
    from certiflow.settings import DEFAULT_PATH, load
    cfg, app = web
    before = DEFAULT_PATH.read_bytes()
    assert client(app, "translator1").get("/api/admin/settings").status_code == 403
    a = client(app, "admin")
    v = a.get("/api/admin/settings").json()
    tr = v["agents"]["translator"]
    assert tr["overridden"] == [] and "v1" in tr["prompt_versions"] and "v2" in v["agents"]["intake"]["prompt_versions"]
    other = next(m["model"] for m in v["models"] if m["model"] != tr["model"])
    body = {"model": other, "effort": "medium", "prompt_version": "v1", "max_tokens": tr["max_tokens"]}
    v = a.put("/api/admin/settings/agents/translator", json=body, headers=H).json()
    assert v["agents"]["translator"]["model"] == other and v["agents"]["translator"]["overridden"] == ["effort", "model"]
    assert load().agent("translator").model == other                 # new pipeline steps use it at once
    assert DEFAULT_PATH.read_bytes() == before                         # the git-tracked defaults are untouched
    assert cfg.settings_override.exists()
    for bad in ({**body, "model": "gpt-4"}, {**body, "effort": "huge"}, {**body, "prompt_version": "v9"},
                {**body, "max_tokens": 10}):
        assert a.put("/api/admin/settings/agents/translator", json=bad, headers=H).status_code == 422
    assert a.put("/api/admin/settings/agents/nobody", json=body, headers=H).status_code == 404
    v = a.put("/api/admin/settings/pipeline", json={"qa_max_loops": 1}, headers=H).json()
    assert v["pipeline"]["qa_max_loops"] == 1 and load().pipeline.qa_max_loops == 1
    assert a.put("/api/admin/settings/pipeline", json={"ocr_dpi": 72}, headers=H).status_code == 422
    v = a.delete("/api/admin/settings/agents/translator", headers=H).json()
    assert v["agents"]["translator"]["model"] == tr["model"] and v["agents"]["translator"]["overridden"] == []
    a.put("/api/admin/settings/pipeline", json={"qa_max_loops": v["pipeline_default"]["qa_max_loops"]}, headers=H)
    assert load().pipeline.qa_max_loops == v["pipeline_default"]["qa_max_loops"]
    actions = [e["action"] for e in a.get("/api/admin/events").json()]
    assert actions.count("settings_changed") == 3 and "settings_reset" in actions


# ------------------------------------------------------------------ Phase 5: languages and pairs


def test_language_and_pair_settings_overlay_the_profiles(web):
    from certiflow.profiles import DATA_DIR, get_profile, resolve_pair
    cfg, app = web
    before = (DATA_DIR / "ar.json").read_bytes(), (DATA_DIR / "pairs.json").read_bytes()
    assert client(app, "translator1").get("/api/admin/languages").status_code == 403
    a = client(app, "admin")
    v = a.get("/api/admin/languages").json()
    ar = next(x for x in v["languages"] if x["code"] == "ar")
    assert ar["overridden"] == [] and "body_size_pt" in ar["values"]
    r = a.put("/api/admin/languages/ar", json={"body_size_pt": 14, "style_guide": ar["values"]["style_guide"] + " X."},
              headers=H)
    assert r.status_code == 200, r.text
    assert get_profile("ar").body_size_pt == 14 and get_profile("ar").style_guide.endswith(" X.")
    for bad in ({"body_size_pt": 50}, {"code": "xx"}, {"direction": "ltr"}, {"quote_marks": ["«"]}, {"word_font": " "}):
        assert a.put("/api/admin/languages/ar", json=bad, headers=H).status_code == 422, bad
    assert a.put("/api/admin/languages/zz", json={"body_size_pt": 12}, headers=H).status_code == 404
    ev = a.get("/api/admin/events").json()[0]
    assert ev["action"] == "language_changed" and ev["data"]["style_guide"] == "changed"   # no prompt text in the log
    # pairs: change a default pair, add a new one, reset both
    tpl = v["templates"][0]["id"]
    assert a.put("/api/admin/pairs/en/ar", json={"conventions": "Passport spelling.", "template_id": tpl},
                 headers=H).status_code == 200
    assert resolve_pair("en", "ar").conventions == "Passport spelling." and resolve_pair("en", "ar").template_id == tpl
    assert a.put("/api/admin/pairs/fr/ar", json={"conventions": "Noms selon le passeport."}, headers=H).status_code == 200
    assert resolve_pair("fr", "ar").conventions == "Noms selon le passeport."
    assert a.put("/api/admin/pairs/en/ar", json={"template_id": "nope"}, headers=H).status_code == 422
    assert a.put("/api/admin/pairs/en/en", json={}, headers=H).status_code == 422
    a.delete("/api/admin/pairs/fr/ar", headers=H)
    a.delete("/api/admin/pairs/en/ar", headers=H)
    a.delete("/api/admin/languages/ar", headers=H)
    assert resolve_pair("fr", "ar").conventions == "" and get_profile("ar").body_size_pt == 13
    assert resolve_pair("en", "ar").conventions.startswith("Follow passport")
    assert ((DATA_DIR / "ar.json").read_bytes(), (DATA_DIR / "pairs.json").read_bytes()) == before
