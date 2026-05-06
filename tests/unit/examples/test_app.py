from __future__ import annotations

import io

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("docx")

from fastapi.testclient import TestClient

from examples.redaction_studio import app as app_module
from examples.redaction_studio.app import app


def _make_docx(paragraphs: list[list[str]]) -> bytes:
    import docx
    from docx.enum.text import WD_BREAK

    document = docx.Document()
    for page_idx, lines in enumerate(paragraphs):
        for line_idx, line in enumerate(lines):
            para = document.add_paragraph(line)
            if page_idx < len(paragraphs) - 1 and line_idx == len(lines) - 1:
                para.add_run().add_break(WD_BREAK.PAGE)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _clear_store():
    app_module.STORE._docs.clear()
    yield
    app_module.STORE._docs.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_upload_returns_doc_id_and_page_count(client):
    raw = _make_docx([["alpha"], ["beta"]])
    resp = client.post(
        "/api/upload",
        files={"file": ("sample.docx", raw, "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "sample.docx"
    assert body["pageCount"] == 2
    assert isinstance(body["docId"], str) and len(body["docId"]) >= 8


def test_upload_rejects_unsupported_extension(client):
    resp = client.post(
        "/api/upload",
        files={"file": ("nope.txt", b"hi", "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["detail"]


def test_list_pages_returns_text(client):
    raw = _make_docx([["page one text"], ["page two text"]])
    doc_id = client.post(
        "/api/upload",
        files={"file": ("a.docx", raw, "application/octet-stream")},
    ).json()["docId"]

    resp = client.get(f"/api/documents/{doc_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pageCount"] == 2
    assert body["pages"][0]["text"].startswith("page one")
    assert body["pages"][1]["index"] == 1


def test_list_pages_404_when_unknown(client):
    resp = client.get("/api/documents/missing")
    assert resp.status_code == 404


from types import SimpleNamespace

from examples.redaction_studio import redactor as redactor_module


def _patched_deid(text, method="mask", **kwargs):
    return SimpleNamespace(deidentified_text=f"[REDACTED:{method}]", entities=[])


def test_redact_page_endpoint_stores_result(client, monkeypatch):
    monkeypatch.setattr(redactor_module, "_deidentify", _patched_deid)
    raw = _make_docx([["secret one"], ["secret two"]])
    doc_id = client.post(
        "/api/upload",
        files={"file": ("a.docx", raw, "application/octet-stream")},
    ).json()["docId"]

    resp = client.post(
        "/api/redact/page",
        json={"docId": doc_id, "pageIndex": 0, "method": "mask"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["page"]["redacted"] == "[REDACTED:mask]"
    assert body["page"]["index"] == 0

    listed = client.get(f"/api/documents/{doc_id}").json()
    assert listed["redactedIndexes"] == [0]


def test_redact_page_endpoint_rejects_bad_index(client, monkeypatch):
    monkeypatch.setattr(redactor_module, "_deidentify", _patched_deid)
    raw = _make_docx([["only"]])
    doc_id = client.post(
        "/api/upload",
        files={"file": ("a.docx", raw, "application/octet-stream")},
    ).json()["docId"]

    resp = client.post(
        "/api/redact/page",
        json={"docId": doc_id, "pageIndex": 99, "method": "mask"},
    )
    assert resp.status_code == 400


def test_redact_batch_endpoint_redacts_every_page(client, monkeypatch):
    monkeypatch.setattr(redactor_module, "_deidentify", _patched_deid)
    raw = _make_docx([["a"], ["b"], ["c"]])
    doc_id = client.post(
        "/api/upload",
        files={"file": ("a.docx", raw, "application/octet-stream")},
    ).json()["docId"]

    resp = client.post("/api/redact/batch", json={"docId": doc_id, "method": "hash"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["redactedCount"] == 3
    assert sorted(p["index"] for p in body["pages"]) == [0, 1, 2]
    assert all(p["redacted"] == "[REDACTED:hash]" for p in body["pages"])


def test_download_returns_redacted_docx(client, monkeypatch):
    monkeypatch.setattr(redactor_module, "_deidentify", _patched_deid)
    raw = _make_docx([["alpha"], ["beta"]])
    doc_id = client.post(
        "/api/upload",
        files={"file": ("a.docx", raw, "application/octet-stream")},
    ).json()["docId"]
    client.post("/api/redact/batch", json={"docId": doc_id, "method": "mask"})

    resp = client.get(f"/api/download/{doc_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    import docx as _docx
    parsed = _docx.Document(io.BytesIO(resp.content))
    text = "\n".join(p.text for p in parsed.paragraphs)
    assert "[REDACTED:mask]" in text


def test_download_404_when_unknown(client):
    resp = client.get("/api/download/missing")
    assert resp.status_code == 404


def test_delete_removes_doc(client, monkeypatch):
    monkeypatch.setattr(redactor_module, "_deidentify", _patched_deid)
    raw = _make_docx([["x"]])
    doc_id = client.post(
        "/api/upload",
        files={"file": ("a.docx", raw, "application/octet-stream")},
    ).json()["docId"]

    resp = client.delete(f"/api/documents/{doc_id}")
    assert resp.status_code == 204
    assert client.get(f"/api/documents/{doc_id}").status_code == 404
