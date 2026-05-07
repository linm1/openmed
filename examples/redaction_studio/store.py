from __future__ import annotations

import time
from threading import RLock

from .types import RedactedPage, RedactionContext, UploadedDoc


class DocStore:
    def __init__(self) -> None:
        self._docs: dict[str, UploadedDoc] = {}
        self._lock = RLock()

    def put(self, doc: UploadedDoc) -> None:
        with self._lock:
            self._docs[doc.doc_id] = doc

    def get(self, doc_id: str) -> UploadedDoc:
        with self._lock:
            if doc_id not in self._docs:
                raise KeyError(doc_id)
            return self._docs[doc_id]

    def delete(self, doc_id: str) -> None:
        with self._lock:
            self._docs.pop(doc_id, None)

    def evict_older_than(self, max_age_seconds: float) -> list[str]:
        cutoff = time.time() - max_age_seconds
        with self._lock:
            stale = [k for k, v in self._docs.items() if v.created_at < cutoff]
            for k in stale:
                self._docs.pop(k, None)
            return stale

    def replace_pipeline_output(
        self,
        doc_id: str,
        *,
        pages: list[RedactedPage],
        summary: dict[str, dict],
    ) -> UploadedDoc:
        next_redacted_pages = {page.index: page for page in pages}
        next_canonical_summary = {
            key: dict(value) for key, value in summary.items()
        }
        with self._lock:
            doc = self.get(doc_id)
            doc.redacted_pages = next_redacted_pages
            doc.canonical_summary = next_canonical_summary
            return doc

    def update_context(
        self,
        doc_id: str,
        *,
        custom_terms: tuple[str, ...] | list[str] | None = None,
        confidence_threshold: float | None = None,
        enabled_pattern_ids: tuple[str, ...] | list[str] | None = None,
    ) -> UploadedDoc:
        with self._lock:
            doc = self.get(doc_id)
            next_context = RedactionContext(
                custom_terms=(
                    doc.context.custom_terms
                    if custom_terms is None
                    else tuple(custom_terms)
                ),
                confidence_threshold=(
                    doc.context.confidence_threshold
                    if confidence_threshold is None
                    else confidence_threshold
                ),
                enabled_pattern_ids=(
                    doc.context.enabled_pattern_ids
                    if enabled_pattern_ids is None
                    else tuple(enabled_pattern_ids)
                ),
            )
            if next_context != doc.context:
                doc.context = next_context
                doc.redacted_pages.clear()
                doc.canonical_summary.clear()
            return doc
