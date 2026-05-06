from __future__ import annotations

import time
from threading import RLock

from .types import RedactedPage, UploadedDoc


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

    def set_redacted_page(self, doc_id: str, page: RedactedPage) -> None:
        with self._lock:
            doc = self.get(doc_id)
            doc.redacted_pages[page.index] = page
