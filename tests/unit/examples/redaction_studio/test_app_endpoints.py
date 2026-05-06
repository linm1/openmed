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
    app_module.STORE._docs.clear()
    yield
    app_module.STORE._docs.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_get_patterns_returns_list(client: TestClient):
    response = client.get("/api/patterns")

    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    assert body
    assert {"id", "label"}.issubset(body[0])


def test_patch_context_updates_confidence(client: TestClient):
    doc = _make_doc()
    app_module.STORE.put(doc)

    response = client.patch(
        f"/api/documents/{doc.doc_id}/context",
        json={"confidenceThreshold": 0.75},
    )

    assert response.status_code == 200, response.text
    assert app_module.STORE.get(doc.doc_id).context.confidence_threshold == 0.75


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
    app_module.STORE.put(doc)

    response = client.patch(
        f"/api/documents/{doc.doc_id}/context",
        json={"customTerms": ["trial"]},
    )

    assert response.status_code == 200, response.text
    updated = app_module.STORE.get(doc.doc_id)
    assert updated.context.custom_terms == ("trial",)
    assert updated.redacted_pages == {}
    assert updated.canonical_summary == {}


def test_redact_page_uses_pipeline(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    doc = _make_doc()
    app_module.STORE.put(doc)
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
