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

_CANONICAL_LABEL_SEPARATOR = "||"


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


def _canonical_key(norm_text: str, label: str) -> str:
    return f"{norm_text}{_CANONICAL_LABEL_SEPARATOR}{label}"


def _canonical_norm(canonical_key: str) -> str:
    norm_text, _, _ = canonical_key.partition(_CANONICAL_LABEL_SEPARATOR)
    return norm_text


def _lookup_canonical(
    canon: dict[str, CanonicalEntity],
    norm_text: str,
    label: str,
) -> CanonicalEntity | None:
    canonical = canon.get(_canonical_key(norm_text, label))
    if canonical is not None:
        return canonical

    canonical = canon.get(norm_text)
    if canonical is not None and canonical.label == label:
        return canonical

    return None


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
    norm_counts: dict[str, int] = {}
    for _, norm_text in grouped:
        norm_counts[norm_text] = norm_counts.get(norm_text, 0) + 1

    canon: dict[str, CanonicalEntity] = {}
    ordered_groups = sorted(
        grouped.values(),
        key=lambda group: (int(group["page"]), int(group["start"])),
    )
    for group in ordered_groups:
        label = str(group["label"])
        label_counters[label] = label_counters.get(label, 0) + 1
        norm = str(group["norm"])
        canonical_key = norm
        if norm_counts[norm] > 1:
            canonical_key = _canonical_key(norm, label)

        canon[canonical_key] = CanonicalEntity(
            token=f"[{label}_{label_counters[label]}]",
            label=label,
            occurrences=int(group["occurrences"]),
        )
    return canon


def _propagation_patterns(
    canon: dict[str, CanonicalEntity],
) -> list[tuple[re.Pattern[str], CanonicalEntity]]:
    patterns: list[tuple[re.Pattern[str], CanonicalEntity]] = []
    for canonical_key, canonical in canon.items():
        norm_text = _canonical_norm(canonical_key)
        parts = [re.escape(part) for part in norm_text.split(" ") if part]
        if not parts:
            continue
        pattern_text = rf"(?<!\w){r'\s+'.join(parts)}(?!\w)"
        patterns.append((re.compile(pattern_text, re.IGNORECASE), canonical))

    return patterns


def _propagate(
    doc: UploadedDoc,
    canon: dict[str, CanonicalEntity],
    existing_entities: list[RawEntity] | None = None,
) -> list[RawEntity]:
    score_by_token: dict[str, float] = {}
    earliest_source_by_token: dict[str, tuple[int, int, int]] = {}
    for entity in existing_entities or []:
        canonical = _lookup_canonical(canon, _norm(entity.surface_text), entity.label)
        if canonical is None:
            continue

        span = (entity.page, entity.start, entity.end)
        earliest_span = earliest_source_by_token.get(canonical.token)
        if earliest_span is not None and earliest_span <= span:
            continue

        earliest_source_by_token[canonical.token] = span
        score_by_token[canonical.token] = entity.score

    return _propagate_matches(doc, _propagation_patterns(canon), existing_entities, score_by_token)


def _propagate_matches(
    doc: UploadedDoc,
    patterns: list[tuple[re.Pattern[str], CanonicalEntity]],
    existing_entities: list[RawEntity] | None = None,
    score_by_token: dict[str, float] | None = None,
) -> list[RawEntity]:
    propagated: list[RawEntity] = []
    existing_spans = {
        (entity.page, entity.start, entity.end, entity.label)
        for entity in (existing_entities or [])
    }
    existing_ranges_by_page: dict[int, list[tuple[int, int]]] = {}
    for entity in existing_entities or []:
        existing_ranges_by_page.setdefault(entity.page, []).append((entity.start, entity.end))

    for page in doc.pages:
        candidate_matches: list[tuple[int, int, str, CanonicalEntity]] = []
        for pattern, canonical in patterns:
            for match in pattern.finditer(page.text):
                span_key = (page.page_number, match.start(), match.end(), canonical.label)
                if span_key in existing_spans:
                    continue
                candidate_matches.append((match.start(), match.end(), match.group(0), canonical))

        blocked_ranges = list(existing_ranges_by_page.get(page.page_number, []))
        accepted_matches: list[RawEntity] = []
        for start, end, surface_text, canonical in sorted(
            candidate_matches,
            key=lambda item: (-(item[1] - item[0]), item[0], item[1], item[3].token, item[3].label),
        ):
            overlaps_existing = any(
                start < blocked_end and blocked_start < end
                for blocked_start, blocked_end in blocked_ranges
            )
            if overlaps_existing:
                continue

            accepted_matches.append(
                RawEntity(
                    page=page.page_number,
                    start=start,
                    end=end,
                    surface_text=surface_text,
                    label=canonical.label,
                    source="propagate",
                    score=(score_by_token or {}).get(canonical.token, 1.0),
                )
            )
            blocked_ranges.append((start, end))
            existing_spans.add((page.page_number, start, end, canonical.label))

        accepted_matches.sort(key=lambda entity: (entity.start, entity.end))
        propagated.extend(accepted_matches)
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
            token = f"[{entity.label}]"
            canonical = _lookup_canonical(canon, _norm(entity.surface_text), entity.label)
            if canonical is not None:
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
            token = f"[{entity.label}]"
            canonical = _lookup_canonical(canon, _norm(entity.surface_text), entity.label)
            if canonical is not None:
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
    def _summary_key(canonical_key: str, canonical: CanonicalEntity) -> str:
        if _CANONICAL_LABEL_SEPARATOR not in canonical_key:
            return canonical_key

        return f"{_canonical_norm(canonical_key)} ({canonical.label})"

    return {
        _summary_key(canonical_key, canonical): {
            "token": canonical.token,
            "label": canonical.label,
            "occurrences": canonical.occurrences,
        }
        for canonical_key, canonical in canon.items()
    }


def run(
    doc: UploadedDoc,
    pack: PatternPack,
    ctx: RedactionContext,
) -> tuple[list[RedactedPage], dict[str, dict]]:
    raw = _post_validate_ner(_ner_pass(doc, ctx))
    raw += _regex_pass(doc, pack, ctx) + _user_term_pass(doc, ctx)
    canon = _build_canonical(raw)
    raw = raw + _propagate(doc, canon, raw)
    canon = _build_canonical(raw)
    raw = _resolve_overlaps(raw)
    pages = _render(doc, raw, canon)
    summary = _build_summary(canon)
    return pages, summary