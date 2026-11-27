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
