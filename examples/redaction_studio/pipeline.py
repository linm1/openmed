from __future__ import annotations

import logging
import re

from openmed import deidentify as _deidentify

from .pattern_loader import PatternPack
from .types import RawEntity, RedactionContext, UploadedDoc

log = logging.getLogger(__name__)

_LABEL_VALIDATORS: dict[str, re.Pattern[str]] = {
    "health_plan_beneficiary_number": re.compile(r"^\d{9,11}$"),
    "social_security_number": re.compile(r"^\d{3}-\d{2}-\d{4}$"),
    "phone_number": re.compile(r"^[\d\s\-\(\)\+]{7,}$"),
    "date": re.compile(r"\d"),
    "age": re.compile(r"^\d{1,3}$"),
    "zip_code": re.compile(r"^\d{5}(?:-\d{4})?$")
}


def _result_entities(result: object) -> object:
    entities = getattr(result, "pii_entities", None)
    if entities is not None:
        return entities

    entities = getattr(result, "entities", None)
    if entities is not None:
        return entities

    raise AttributeError("deidentify result is missing `pii_entities` and `entities`.")


def _entity_score(entity: object) -> float:
    confidence = getattr(entity, "confidence", None)
    if confidence is not None:
        return float(confidence)

    score = getattr(entity, "score", None)
    if score is not None:
        return float(score)

    raise AttributeError("deidentify entity is missing `confidence` and `score`.")


def _regex_pass(doc: UploadedDoc, pack: PatternPack, ctx: RedactionContext) -> list[RawEntity]:
    allowed = set(ctx.enabled_pattern_ids)
    entities: list[RawEntity] = []
    for page in doc.pages:
        for pattern in pack:
            if allowed and pattern.id not in allowed:
                continue
            for match in pattern.regex.finditer(page.text):
                text = match.group(0)
                if pattern.post_validate is not None and not pattern.post_validate.search(text):
                    continue
                entities.append(
                    RawEntity(
                        page=page.page_number,
                        start=match.start(),
                        end=match.end(),
                        surface_text=text,
                        label=pattern.label,
                        source="regex",
                        score=1.0,
                    )
                )
    return entities


def _user_term_pass(doc: UploadedDoc, ctx: RedactionContext) -> list[RawEntity]:
    entities: list[RawEntity] = []
    for term in ctx.custom_terms:
        if not term:
            continue
        pattern = re.compile(re.escape(term))
        for page in doc.pages:
            for match in pattern.finditer(page.text):
                entities.append(
                    RawEntity(
                        page=page.page_number,
                        start=match.start(),
                        end=match.end(),
                        surface_text=match.group(0),
                        label="CUSTOM",
                        source="user",
                        score=1.0,
                    )
                )
    return entities


def _ner_pass(doc: UploadedDoc, ctx: RedactionContext) -> list[RawEntity]:
    entities: list[RawEntity] = []
    for page in doc.pages:
        stripped_text = page.text.lstrip()
        leading_whitespace = len(page.text) - len(stripped_text)
        result = _deidentify(
            stripped_text,
            confidence_threshold=ctx.confidence_threshold,
        )
        for entity in _result_entities(result):
            entities.append(
                RawEntity(
                    page=page.page_number,
                    start=entity.start + leading_whitespace,
                    end=entity.end + leading_whitespace,
                    surface_text=entity.text,
                    label=entity.label,
                    source="ner",
                    score=_entity_score(entity),
                )
            )
    return entities


def _post_validate_ner(entities: list[RawEntity]) -> list[RawEntity]:
    kept: list[RawEntity] = []
    for entity in entities:
        validator = _LABEL_VALIDATORS.get(entity.label)
        if validator is None:
            kept.append(entity)
            continue
        if validator.search(entity.surface_text):
            kept.append(entity)
            continue
        log.debug("post-validate drop: label=%s text=%r", entity.label, entity.surface_text)
    return kept