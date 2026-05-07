from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from examples.redaction_studio import app as app_module
from examples.redaction_studio.app import app
from examples.redaction_studio.types import PageSlice, RedactedPage, RedactionContext, UploadedDoc


def _make_doc(*, doc_id: str = "doc-1") -> UploadedDoc:
    return UploadedDoc(
        doc_id=doc_id,
        filename="sample.pdf",
        pages=(
            PageSlice(page_number=0, text="Patient Jane Doe joined trial CT-42."),
            PageSlice(page_number=1, text="Follow up with Jane Doe next week."),
        ),
        uploaded_at=datetime.now(timezone.utc),
    )


@pytest.fixture(autouse=True)
def _clear_store():
    app_module.store._docs.clear()
    yield
    app_module.store._docs.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_get_patterns_includes_disabled_default_pattern(client: TestClient):
    response = client.get("/api/patterns")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body
    assert all("regex_preview" in pattern for pattern in body)
    assert all("enabled_by_default" in pattern for pattern in body)

    version_pattern = next(
        pattern for pattern in body if pattern["id"] == "version_string"
    )
    assert version_pattern == {
        "id": "version_string",
        "label": "VERSION",
        "regex_preview": r"\b(?:Version\s*)?\d+(?:\.\d+){1,3}\b",
        "enabled_by_default": False,
    }


def test_load_pattern_catalog_rejects_reserved_sentinel_id(tmp_path):
    pack_path = tmp_path / "reserved-pattern.toml"
    pack_path.write_text(
        '[[patterns]]\nid = "__none__"\nlabel = "Reserved"\nregex = "reserved"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reserved"):
        app_module._load_pattern_catalog(pack_path)


def test_download_sanitizes_content_disposition_filename(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    doc = _make_doc(doc_id="doc-download")
    doc.filename = 'evil\\danger"\r\nname\x00.pdf'
    app_module.store.put(doc)
    monkeypatch.setattr(
        app_module,
        "_write_doc",
        lambda current_doc, redacted_pages: (b"redacted", "application/pdf"),
        raising=False,
    )

    response = client.get(f"/api/download/{doc.doc_id}")

    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        'attachment; filename="danger___name_.redacted.pdf"'
    )


def test_download_adds_utf8_filename_for_non_ascii_names(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    doc = _make_doc(doc_id="doc-download-utf8")
    doc.filename = "résumé.pdf"
    app_module.store.put(doc)
    monkeypatch.setattr(
        app_module,
        "_write_doc",
        lambda current_doc, redacted_pages: (b"redacted", "application/pdf"),
        raising=False,
    )

    response = client.get(f"/api/download/{doc.doc_id}")

    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        "attachment; filename=\"r_sum_.redacted.pdf\"; "
        "filename*=UTF-8''r%C3%A9sum%C3%A9.redacted.pdf"
    )


def test_patch_context_updates_confidence(client: TestClient):
    doc = _make_doc()
    app_module.store.put(doc)

    response = client.patch(
        f"/api/documents/{doc.doc_id}/context",
        json={"confidenceThreshold": 0.75},
    )

    assert response.status_code == 200, response.text
    assert app_module.store.get(doc.doc_id).context.confidence_threshold == 0.75


def test_patch_context_clears_redacted_pages_cache(client: TestClient):
    doc = _make_doc()
    doc.redacted_pages[0] = RedactedPage(
        index=0,
        original=doc.pages[0].text,
        redacted="[NAME_1] joined trial [TRIAL_ID_1].",
        entities=(),
    )
    doc.canonical_summary["jane doe"] = {
        "token": "[NAME_1]",
        "label": "NAME",
        "occurrences": 2,
    }
    app_module.store.put(doc)

    response = client.patch(
        f"/api/documents/{doc.doc_id}/context",
        json={"customTerms": ["trial"]},
    )

    assert response.status_code == 200, response.text
    updated = app_module.store.get(doc.doc_id)
    assert updated.context.custom_terms == ("trial",)
    assert updated.redacted_pages == {}
    assert updated.canonical_summary == {}


def test_upload_rejects_oversized_payload_before_parsing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    detect_format_mock = MagicMock(return_value="pdf")
    parse_mock = MagicMock()
    monkeypatch.setattr(app_module, "detect_format", detect_format_mock, raising=False)
    monkeypatch.setattr(app_module, "parse", parse_mock, raising=False)

    response = client.post(
        "/api/upload",
        files={
            "file": (
                "large.pdf",
                b"x" * (app_module.MAX_UPLOAD_BYTES + 1),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 413, response.text
    assert response.json() == {"detail": "File exceeds 25 MB limit"}
    detect_format_mock.assert_not_called()
    parse_mock.assert_not_called()


def test_redact_page_uses_pipeline(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    doc = _make_doc()
    app_module.store.put(doc)
    run_mock = MagicMock(
        return_value=(
            [
                RedactedPage(
                    index=0,
                    original=doc.pages[0].text,
                    redacted="Patient [NAME_1] joined trial [TRIAL_ID_1].",
                    entities=(
                        {
                            "label": "NAME",
                            "start": 8,
                            "end": 16,
                            "text": "Jane Doe",
                            "score": 0.99,
                            "source": "ner",
                            "token": "[NAME_1]",
                        },
                    ),
                ),
                RedactedPage(
                    index=1,
                    original=doc.pages[1].text,
                    redacted="Follow up with [NAME_1] next week.",
                    entities=(),
                ),
            ],
            {"jane doe": {"token": "[NAME_1]", "label": "NAME", "occurrences": 2}},
        )
    )
    monkeypatch.setattr(app_module, "pipeline", SimpleNamespace(run=run_mock), raising=False)
    monkeypatch.setattr(app_module, "_pack", [SimpleNamespace(id="demo", label="Demo")], raising=False)

    response = client.post(
        f"/api/documents/{doc.doc_id}/redact-page",
        json={"page": 0},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pageNumber"] == 0
    assert body["redactedText"] == "Patient [NAME_1] joined trial [TRIAL_ID_1]."
    assert body["canonical"]["jane doe"]["token"] == "[NAME_1]"
    run_mock.assert_called_once_with(doc, app_module._pack, doc.context)


def test_redact_page_returns_400_for_page_out_of_range(client: TestClient):
    doc = _make_doc(doc_id="doc-range")
    app_module.store.put(doc)

    response = client.post(
        f"/api/documents/{doc.doc_id}/redact-page",
        json={"page": 99},
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "page out of range"}


def test_redact_page_returns_404_when_doc_deleted_during_pipeline(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    doc = _make_doc(doc_id="doc-race")
    app_module.store.put(doc)
    run_mock = MagicMock(
        return_value=(
            [
                RedactedPage(
                    index=0,
                    original=doc.pages[0].text,
                    redacted="Patient [NAME_1] joined trial [TRIAL_ID_1].",
                    entities=(),
                ),
                RedactedPage(
                    index=1,
                    original=doc.pages[1].text,
                    redacted="Follow up with [NAME_1] next week.",
                    entities=(),
                ),
            ],
            {"jane doe": {"token": "[NAME_1]", "label": "NAME", "occurrences": 2}},
        )
    )
    replace_mock = MagicMock(side_effect=KeyError(doc.doc_id))
    monkeypatch.setattr(app_module, "pipeline", SimpleNamespace(run=run_mock), raising=False)
    monkeypatch.setattr(app_module.store, "replace_pipeline_output", replace_mock, raising=False)

    response = client.post(
        f"/api/documents/{doc.doc_id}/redact-page",
        json={"page": 0},
    )

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Unknown doc_id"}
    run_mock.assert_called_once_with(doc, app_module._pack, doc.context)
    replace_mock.assert_called_once()


def test_redact_page_returns_500_when_pipeline_omits_requested_page(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    doc = _make_doc(doc_id="doc-missing-page")
    app_module.store.put(doc)
    run_mock = MagicMock(
        return_value=(
            [
                RedactedPage(
                    index=1,
                    original=doc.pages[1].text,
                    redacted="Follow up with [NAME_1] next week.",
                    entities=(),
                ),
            ],
            {"jane doe": {"token": "[NAME_1]", "label": "NAME", "occurrences": 1}},
        )
    )
    monkeypatch.setattr(app_module, "pipeline", SimpleNamespace(run=run_mock), raising=False)
    monkeypatch.setattr(app_module, "_pack", [SimpleNamespace(id="demo", label="Demo")], raising=False)

    response = client.post(
        f"/api/documents/{doc.doc_id}/redact-page",
        json={"page": 0},
    )

    assert response.status_code == 500, response.text
    assert response.json() == {"detail": "Pipeline did not produce output for requested page"}
    run_mock.assert_called_once_with(doc, app_module._pack, doc.context)


def test_legacy_redact_page_returns_500_when_pipeline_omits_requested_page(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    doc = _make_doc(doc_id="doc-legacy-missing-page")
    app_module.store.put(doc)
    run_mock = MagicMock(
        return_value=(
            [
                RedactedPage(
                    index=1,
                    original=doc.pages[1].text,
                    redacted="Follow up with [NAME_1] next week.",
                    entities=(),
                ),
            ],
            {"jane doe": {"token": "[NAME_1]", "label": "NAME", "occurrences": 1}},
        )
    )
    monkeypatch.setattr(app_module, "pipeline", SimpleNamespace(run=run_mock), raising=False)
    monkeypatch.setattr(app_module, "_pack", [SimpleNamespace(id="demo", label="Demo")], raising=False)

    response = client.post(
        "/api/redact/page",
        json={"docId": doc.doc_id, "pageIndex": 0},
    )

    assert response.status_code == 500, response.text
    assert response.json() == {"detail": "Pipeline did not produce output for requested page"}
    run_mock.assert_called_once_with(doc, app_module._pack, doc.context)


def test_redact_batch_returns_canonical_summary(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    doc = _make_doc(doc_id="doc-batch-canonical")
    app_module.store.put(doc)
    run_mock = MagicMock(
        return_value=(
            [
                RedactedPage(
                    index=0,
                    original=doc.pages[0].text,
                    redacted="Patient [NAME_1] joined trial [TRIAL_ID_1].",
                    entities=(),
                ),
                RedactedPage(
                    index=1,
                    original=doc.pages[1].text,
                    redacted="Follow up with [NAME_1] next week.",
                    entities=(),
                ),
            ],
            {"jane doe": {"token": "[NAME_1]", "label": "NAME", "occurrences": 2}},
        )
    )
    monkeypatch.setattr(app_module, "pipeline", SimpleNamespace(run=run_mock), raising=False)
    monkeypatch.setattr(app_module, "_pack", [SimpleNamespace(id="demo", label="Demo")], raising=False)

    response = client.post(
        "/api/redact/batch",
        json={"docId": doc.doc_id},
    )

    assert response.status_code == 200, response.text
    assert response.json()["canonical"]["jane doe"] == {
        "token": "[NAME_1]",
        "label": "NAME",
        "occurrences": 2,
    }
    run_mock.assert_called_once_with(doc, app_module._pack, doc.context)


def test_redact_batch_returns_500_when_pipeline_omits_page(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    doc = _make_doc(doc_id="doc-batch-missing-page")
    app_module.store.put(doc)
    run_mock = MagicMock(
        return_value=(
            [
                RedactedPage(
                    index=0,
                    original=doc.pages[0].text,
                    redacted="Patient [NAME_1] joined trial [TRIAL_ID_1].",
                    entities=(),
                ),
            ],
            {"jane doe": {"token": "[NAME_1]", "label": "NAME", "occurrences": 1}},
        )
    )
    monkeypatch.setattr(app_module, "pipeline", SimpleNamespace(run=run_mock), raising=False)
    monkeypatch.setattr(app_module, "_pack", [SimpleNamespace(id="demo", label="Demo")], raising=False)

    response = client.post(
        "/api/redact/batch",
        json={"docId": doc.doc_id},
    )

    assert response.status_code == 500, response.text
    assert response.json() == {"detail": "Pipeline did not produce output for requested page"}
    run_mock.assert_called_once_with(doc, app_module._pack, doc.context)


def test_legacy_redact_routes_ignore_method_field(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    doc = _make_doc()
    app_module.store.put(doc)
    run_mock = MagicMock(
        return_value=(
            [
                RedactedPage(
                    index=0,
                    original=doc.pages[0].text,
                    redacted="Patient [NAME_1] joined trial [TRIAL_ID_1].",
                    entities=(),
                ),
                RedactedPage(
                    index=1,
                    original=doc.pages[1].text,
                    redacted="Follow up with [NAME_1] next week.",
                    entities=(),
                ),
            ],
            {"jane doe": {"token": "[NAME_1]", "label": "NAME", "occurrences": 2}},
        )
    )
    monkeypatch.setattr(app_module, "pipeline", SimpleNamespace(run=run_mock), raising=False)
    monkeypatch.setattr(app_module, "_pack", [SimpleNamespace(id="demo", label="Demo")], raising=False)

    page_response = client.post(
        "/api/redact/page",
        json={"docId": doc.doc_id, "pageIndex": 0, "method": "remove"},
    )
    batch_response = client.post(
        "/api/redact/batch",
        json={"docId": doc.doc_id, "method": "hash"},
    )

    assert page_response.status_code == 200, page_response.text
    assert page_response.json()["page"]["redacted"] == "Patient [NAME_1] joined trial [TRIAL_ID_1]."
    assert batch_response.status_code == 200, batch_response.text
    assert batch_response.json()["redactedCount"] == 2
    assert batch_response.json()["canonical"]["jane doe"]["token"] == "[NAME_1]"
    assert run_mock.call_count == 2
