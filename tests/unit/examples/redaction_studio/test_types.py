import dataclasses
from datetime import UTC, datetime

import pytest

from examples.redaction_studio.types import (
    CanonicalEntity,
    PageSlice,
    RawEntity,
    RedactionContext,
    UploadedDoc,
)


def test_raw_entity_frozen():
    e = RawEntity(
        page=0,
        start=5,
        end=10,
        surface_text="ACME Inc.",
        label="ORG",
        source="ner",
        score=0.9,
    )
    assert e.surface_text == "ACME Inc."
    try:
        e.score = 0.5
        assert False, "should be frozen"
    except dataclasses.FrozenInstanceError:
        pass


def test_canonical_entity_fields():
    c = CanonicalEntity(token="[ORG_1]", label="ORG", occurrences=3)
    assert c.token == "[ORG_1]"


def test_redaction_context_defaults():
    ctx = RedactionContext()
    assert ctx.confidence_threshold == 0.85
    assert ctx.custom_terms == ()
    assert ctx.enabled_pattern_ids == ()


def test_uploaded_doc_has_context_field():
    doc = UploadedDoc(
        doc_id="abc",
        filename="test.txt",
        content=b"hello",
        pages=[PageSlice(page_number=0, text="hello", original_bytes=b"hello")],
        uploaded_at=datetime.now(UTC),
    )
    assert isinstance(doc.context, RedactionContext)
    assert doc.canonical_summary == {}


def test_uploaded_doc_treats_naive_uploaded_at_as_utc_for_created_at():
    class NaiveUtcDateTime(datetime):
        def timestamp(self) -> float:
            if self.tzinfo is None:
                return -1.0
            return super().timestamp()

    uploaded_at = NaiveUtcDateTime(2026, 5, 6, 12, 0, 0)
    doc = UploadedDoc(
        doc_id="abc",
        filename="test.txt",
        content=b"hello",
        pages=[PageSlice(page_number=0, text="hello", original_bytes=b"hello")],
        uploaded_at=uploaded_at,
    )

    assert doc.created_at == datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC).timestamp()


def test_page_slice_rejects_conflicting_page_number_and_index():
    with pytest.raises(TypeError, match="conflicting values"):
        PageSlice(page_number=1, index=2, text="hello")