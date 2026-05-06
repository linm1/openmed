from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from examples.redaction_studio import pipeline
from examples.redaction_studio.pattern_loader import load_pack
from examples.redaction_studio.types import CanonicalEntity, PageSlice, RawEntity, RedactionContext, UploadedDoc
from openmed.core.pii import DeidentificationResult, PIIEntity


def _make_doc(pages: list[str]) -> UploadedDoc:
    return UploadedDoc(
        doc_id="doc-1",
        filename="sample.pdf",
        pages=[
            PageSlice(page_number=i, text=text, original_bytes=text.encode())
            for i, text in enumerate(pages)
        ],
        uploaded_at=datetime.datetime.now(datetime.timezone.utc),
    )


def _make_raw_entity(label: str, surface_text: str, *, page: int = 0, start: int = 0, score: float = 0.95) -> RawEntity:
    return RawEntity(
        page=page,
        start=start,
        end=start + len(surface_text),
        surface_text=surface_text,
        label=label,
        source="ner",
        score=score,
    )


def _make_deidentify_result(original_text: str, pii_entities: list[PIIEntity]) -> DeidentificationResult:
    return DeidentificationResult(
        original_text=original_text,
        deidentified_text=original_text,
        pii_entities=pii_entities,
        method="mask",
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )


def test_ner_pass_returns_raw_entities(monkeypatch):
    doc = _make_doc(["John Smith"])
    ctx = RedactionContext(confidence_threshold=0.85)
    fake_result = SimpleNamespace(
        entities=[
            SimpleNamespace(
            text="John Smith",
            label="name",
            score=0.92,
            start=0,
            end=10,
        )
        ]
    )

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


def test_ner_pass_reads_real_deidentify_result_shape(monkeypatch):
    doc = _make_doc(["John Smith"])
    ctx = RedactionContext(confidence_threshold=0.85)
    fake_result = _make_deidentify_result(
        "John Smith",
        [
            PIIEntity(
                text="John Smith",
                label="name",
                confidence=0.92,
                start=0,
                end=10,
            )
        ],
    )

    monkeypatch.setattr(pipeline, "_deidentify", MagicMock(return_value=fake_result))

    entities = pipeline._ner_pass(doc, ctx)

    assert entities == [
        RawEntity(
            page=0,
            start=0,
            end=10,
            surface_text="John Smith",
            label="name",
            source="ner",
            score=0.92,
        )
    ]


def test_ner_pass_restores_offsets_after_leading_whitespace(monkeypatch):
    doc = _make_doc(["  John Smith"])
    ctx = RedactionContext(confidence_threshold=0.85)
    fake_result = _make_deidentify_result(
        "John Smith",
        [
            PIIEntity(
                text="John Smith",
                label="name",
                confidence=0.92,
                start=0,
                end=10,
            )
        ],
    )

    deidentify_mock = MagicMock(return_value=fake_result)
    monkeypatch.setattr(pipeline, "_deidentify", deidentify_mock)

    entities = pipeline._ner_pass(doc, ctx)

    deidentify_mock.assert_called_once_with(
        "John Smith",
        confidence_threshold=ctx.confidence_threshold,
    )

    assert entities == [
        RawEntity(
            page=0,
            start=2,
            end=12,
            surface_text="John Smith",
            label="name",
            source="ner",
            score=0.92,
        )
    ]


def test_ner_pass_maps_entities_to_their_source_pages(monkeypatch):
    doc = _make_doc(["John Smith", "Call 555-123-4567"])
    ctx = RedactionContext(confidence_threshold=0.85)
    fake_results = [
        _make_deidentify_result(
            "John Smith",
            [
                PIIEntity(
                    text="John Smith",
                    label="name",
                    confidence=0.92,
                    start=0,
                    end=10,
                )
            ],
        ),
        _make_deidentify_result(
            "Call 555-123-4567",
            [
                PIIEntity(
                    text="555-123-4567",
                    label="phone_number",
                    confidence=0.9,
                    start=5,
                    end=17,
                )
            ],
        ),
    ]

    monkeypatch.setattr(pipeline, "_deidentify", MagicMock(side_effect=fake_results))

    entities = pipeline._ner_pass(doc, ctx)

    assert entities == [
        RawEntity(
            page=0,
            start=0,
            end=10,
            surface_text="John Smith",
            label="name",
            source="ner",
            score=0.92,
        ),
        RawEntity(
            page=1,
            start=5,
            end=17,
            surface_text="555-123-4567",
            label="phone_number",
            source="ner",
            score=0.9,
        ),
    ]


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


@pytest.mark.parametrize(
    ("label", "invalid_text", "valid_text"),
    [
        ("social_security_number", "123456789", "123-45-6789"),
        ("phone_number", "call me", "+1 (555) 123-4567"),
        ("date", "tomorrow", "01/15/1970"),
        ("age", "age forty-two", "42"),
        ("zip_code", "1234", "12345-6789"),
    ],
)
def test_post_validate_applies_supported_label_validators(label, invalid_text, valid_text):
    bad_entity = _make_raw_entity(label, invalid_text)
    good_entity = _make_raw_entity(label, valid_text, start=len(invalid_text) + 1)

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


def test_regex_pass_finds_nct():
    doc = _make_doc(["Study NCT12345678 ongoing"])
    ctx = RedactionContext()
    pack = load_pack()

    entities = pipeline._regex_pass(doc, pack, ctx)
    study_id_hits = [entity for entity in entities if entity.label == "STUDY_ID"]

    assert len(study_id_hits) == 1
    assert study_id_hits[0].surface_text == "NCT12345678"
    assert study_id_hits[0].source == "regex"


def test_regex_pass_respects_enabled_pattern_ids():
    doc = _make_doc(["Study NCT12345678 and SOP-123 ongoing"])
    ctx = RedactionContext(enabled_pattern_ids=("nct_study_id",))
    pack = load_pack()

    entities = pipeline._regex_pass(doc, pack, ctx)

    assert {(entity.label, entity.surface_text) for entity in entities} == {
        ("STUDY_ID", "NCT12345678")
    }


def test_regex_pass_with_unknown_allowed_pattern_id_returns_empty():
    doc = _make_doc(["Study NCT12345678 ongoing"])
    ctx = RedactionContext(enabled_pattern_ids=("missing-pattern",))
    pack = load_pack()

    entities = pipeline._regex_pass(doc, pack, ctx)

    assert entities == []


def test_user_term_pass_finds_exact_match():
    doc = _make_doc(["Sponsor: Acme Pharma. Contact: Acme Pharma team."])
    ctx = RedactionContext(custom_terms=("Acme Pharma",))

    entities = pipeline._user_term_pass(doc, ctx)

    assert len(entities) == 2
    assert all(entity.label == "CUSTOM" for entity in entities)
    assert all(entity.source == "user" for entity in entities)


def test_user_term_pass_skips_empty_term():
    doc = _make_doc(["Sponsor: Acme Pharma"])
    ctx = RedactionContext(custom_terms=("", "Acme Pharma"))

    entities = pipeline._user_term_pass(doc, ctx)

    assert [(entity.surface_text, entity.source) for entity in entities] == [
        ("Acme Pharma", "user")
    ]


def test_user_term_pass_is_case_sensitive():
    doc = _make_doc(["Sponsor: Acme Pharma"])
    ctx = RedactionContext(custom_terms=("acme pharma",))

    entities = pipeline._user_term_pass(doc, ctx)

    assert entities == []


def test_build_canonical_assigns_stable_tokens():
    entities = [
        _make_raw_entity("ORG", "Acme Inc.", page=0, start=10),
        _make_raw_entity("ORG", "Beta Corp.", page=0, start=30),
        _make_raw_entity("ORG", "Acme Inc.", page=1, start=5),
    ]

    canon = pipeline._build_canonical(entities)

    assert canon["acme inc."].token == "[ORG_1]"
    assert canon["beta corp."].token == "[ORG_2]"
    assert canon["acme inc."].occurrences == 2


def test_build_canonical_groups_by_label():
    entities = [
        _make_raw_entity("STUDY_ID", "NCT12345678", page=0, start=0),
        _make_raw_entity("ORG", "Acme Inc.", page=0, start=25),
    ]

    canon = pipeline._build_canonical(entities)

    assert canon["nct12345678"].token == "[STUDY_ID_1]"
    assert canon["acme inc."].token == "[ORG_1]"


def test_propagate_finds_unlabelled_occurrence():
    doc = _make_doc([
        "Acme Inc. sponsored the study.",
        "Later, Acme Inc. appeared again.",
    ])
    canon = {
        "acme inc.": CanonicalEntity(token="[ORG_1]", label="ORG", occurrences=1)
    }

    new_entities = pipeline._propagate(doc, canon)

    pages_hit = {entity.page for entity in new_entities}
    assert 1 in pages_hit
    assert new_entities
    assert all(entity.source == "propagate" for entity in new_entities)


def test_resolve_overlaps_keeps_longest():
    entities = [
        _make_raw_entity("ORG", "Acme Inc.", start=0),
        _make_raw_entity("ORG", "Acme", start=0),
    ]

    resolved = pipeline._resolve_overlaps(entities)

    assert resolved == [_make_raw_entity("ORG", "Acme Inc.", start=0)]


def test_run_returns_redacted_pages_and_summary(monkeypatch):
    doc = _make_doc(["NCT12345678 sponsored by Acme Inc."])
    ctx = RedactionContext()
    pack = load_pack()

    monkeypatch.setattr(pipeline, "_deidentify", MagicMock(return_value=SimpleNamespace(pii_entities=[])))

    pages, summary = pipeline.run(doc, pack, ctx)

    assert isinstance(pages, list)
    assert len(pages) == 1
    assert isinstance(summary, dict)
    assert any(entry["token"].find("STUDY_ID") >= 0 for entry in summary.values())