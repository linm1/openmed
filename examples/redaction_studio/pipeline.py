from __future__ import annotations

import logging
import re

from openmed import deidentify as _deidentify

from .pattern_loader import PatternPack
from .types import CanonicalEntity, RawEntity, RedactedPage, RedactionContext, UploadedDoc

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


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _build_canonical(entities: list[RawEntity]) -> dict[str, CanonicalEntity]:
    grouped: dict[tuple[str, str], dict[str, int | str]] = {}
    for entity in entities:
        key = (entity.label, _norm(entity.surface_text))
        first_seen = grouped.get(key)
        if first_seen is None:
            grouped[key] = {
                "label": entity.label,
                "norm": key[1],
                "page": entity.page,
                "start": entity.start,
                "occurrences": 1,
            }
            continue

        first_page = int(first_seen["page"])
        first_start = int(first_seen["start"])
        if (entity.page, entity.start) < (first_page, first_start):
            first_seen["page"] = entity.page
            first_seen["start"] = entity.start
        first_seen["occurrences"] = int(first_seen["occurrences"]) + 1

    label_counters: dict[str, int] = {}
    canon: dict[str, CanonicalEntity] = {}
    ordered_groups = sorted(
        grouped.values(),
        key=lambda group: (int(group["page"]), int(group["start"])),
    )
    for group in ordered_groups:
        label = str(group["label"])
        label_counters[label] = label_counters.get(label, 0) + 1
        norm = str(group["norm"])
        canon.setdefault(
            norm,
            CanonicalEntity(
                token=f"[{label}_{label_counters[label]}]",
                label=label,
                occurrences=int(group["occurrences"]),
            ),
        )
    return canon


def _propagate(doc: UploadedDoc, canon: dict[str, CanonicalEntity]) -> list[RawEntity]:
    propagated: list[RawEntity] = []
    patterns = []
    for norm_text, canonical in canon.items():
        parts = [re.escape(part) for part in norm_text.split(" ") if part]
        if not parts:
            continue
        patterns.append((re.compile(r"\s+".join(parts), re.IGNORECASE), canonical))

    for page in doc.pages:
        for pattern, canonical in patterns:
            for match in pattern.finditer(page.text):
                propagated.append(
                    RawEntity(
                        page=page.page_number,
                        start=match.start(),
                        end=match.end(),
                        surface_text=match.group(0),
                        label=canonical.label,
                        source="propagate",
                        score=1.0,
                    )
                )
    return propagated


def _resolve_overlaps(entities: list[RawEntity]) -> list[RawEntity]:
    page_groups: dict[int, list[tuple[int, RawEntity]]] = {}
    for index, entity in enumerate(entities):
        page_groups.setdefault(entity.page, []).append((index, entity))

    resolved: list[RawEntity] = []
    for page in sorted(page_groups):
        ranked = sorted(
            page_groups[page],
            key=lambda item: (-(item[1].end - item[1].start), item[1].start, item[0]),
        )
        kept: list[tuple[int, RawEntity]] = []
        for original_index, entity in ranked:
            overlaps = any(
                entity.start < kept_entity.end and kept_entity.start < entity.end
                for _, kept_entity in kept
            )
            if overlaps:
                continue
            kept.append((original_index, entity))

        kept.sort(key=lambda item: (item[1].start, item[1].end, item[0]))
        resolved.extend(entity for _, entity in kept)
    return resolved


def _render(
    doc: UploadedDoc,
    entities: list[RawEntity],
    canon: dict[str, CanonicalEntity],
) -> list[RedactedPage]:
    page_entities: dict[int, list[RawEntity]] = {}
    for entity in entities:
        page_entities.setdefault(entity.page, []).append(entity)

    rendered_pages: list[RedactedPage] = []
    for page in doc.pages:
        current_entities = sorted(
            page_entities.get(page.page_number, []),
            key=lambda entity: (entity.start, entity.end),
        )
        redacted_text = page.text
        entity_payload: list[dict] = []
        for entity in current_entities:
            canonical = canon.get(_norm(entity.surface_text))
            token = f"[{entity.label}]"
            if canonical is not None and canonical.label == entity.label:
                token = canonical.token
            entity_payload.append(
                {
                    "label": entity.label,
                    "start": entity.start,
                    "end": entity.end,
                    "text": entity.surface_text,
                    "score": entity.score,
                    "source": entity.source,
                    "token": token,
                }
            )

        for entity in sorted(current_entities, key=lambda item: (item.start, item.end), reverse=True):
            canonical = canon.get(_norm(entity.surface_text))
            token = f"[{entity.label}]"
            if canonical is not None and canonical.label == entity.label:
                token = canonical.token
            redacted_text = redacted_text[:entity.start] + token + redacted_text[entity.end:]

        rendered_pages.append(
            RedactedPage(
                index=page.page_number,
                original=page.text,
                redacted=redacted_text,
                entities=tuple(entity_payload),
            )
        )
    return rendered_pages


def _build_summary(canon: dict[str, CanonicalEntity]) -> dict[str, dict]:
    return {
        norm_text: {
            "token": canonical.token,
            "label": canonical.label,
            "occurrences": canonical.occurrences,
        }
        for norm_text, canonical in canon.items()
    }


def run(
    doc: UploadedDoc,
    pack: PatternPack,
    ctx: RedactionContext,
) -> tuple[list[RedactedPage], dict[str, dict]]:
    raw = _post_validate_ner(_ner_pass(doc, ctx))
    raw += _regex_pass(doc, pack, ctx) + _user_term_pass(doc, ctx)
    canon = _build_canonical(raw)
    raw = raw + _propagate(doc, canon)
    canon = _build_canonical(raw)
    raw = _resolve_overlaps(raw)
    pages = _render(doc, raw, canon)
    summary = _build_summary(canon)
    return pages, summary