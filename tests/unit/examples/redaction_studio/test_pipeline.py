from __future__ import annotations

import datetime
from unittest.mock import MagicMock

from examples.redaction_studio import pipeline
from examples.redaction_studio.types import PageSlice, RawEntity, RedactionContext, UploadedDoc


def _make_doc(pages: list[str]) -> UploadedDoc:
    return UploadedDoc(
        doc_id="doc-1",
        filename="sample.pdf",
        pages=[
            PageSlice(page_number=i, text=text, original_bytes=text.encode())
            for i, text in enumerate(pages)
        ],
        uploaded_at=datetime.datetime.utcnow(),
    )


def test_ner_pass_returns_raw_entities(monkeypatch):
    doc = _make_doc(["John Smith"])
    ctx = RedactionContext(confidence_threshold=0.85)
    fake_result = MagicMock()
    fake_result.entities = [
        MagicMock(
            text="John Smith",
            label="name",
            score=0.92,
            start=0,
            end=10,
        )
    ]

    monkeypatch.setattr(pipeline, "_deidentify", MagicMock(return_value=fake_result))

    entities = pipeline._ner_pass(doc, ctx)

    assert len(entities) == 1
    assert entities[0] == RawEntity(
        page=0,
        start=0,
        end=10,
        surface_text="John Smith",
        label="name",
        source="ner",
        score=0.92,
    )


def test_post_validate_drops_spurious_health_plan_tag():
    bad_entity = RawEntity(
        page=0,
        start=0,
        end=4,
        surface_text="ACME",
        label="health_plan_beneficiary_number",
        source="ner",
        score=0.95,
    )
    good_entity = RawEntity(
        page=0,
        start=5,
        end=15,
        surface_text="1234567890",
        label="health_plan_beneficiary_number",
        source="ner",
        score=0.95,
    )

    entities = pipeline._post_validate_ner([bad_entity, good_entity])

    assert entities == [good_entity]


def test_post_validate_passes_unknown_labels():
    entity = RawEntity(
        page=0,
        start=0,
        end=4,
        surface_text="ACME",
        label="mystery_label",
        source="ner",
        score=0.8,
    )

    entities = pipeline._post_validate_ner([entity])

    assert entities == [entity]