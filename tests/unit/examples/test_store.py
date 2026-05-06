from __future__ import annotations

import time

import pytest

from examples.redaction_studio.store import DocStore
from examples.redaction_studio.types import PageSlice, RedactedPage, UploadedDoc


def _make_doc(doc_id: str = "abc", *, age_seconds: float = 0.0) -> UploadedDoc:
    return UploadedDoc(
        doc_id=doc_id,
        filename="test.docx",
        fmt="docx",
        pages=(PageSlice(0, "hello"),),
        created_at=time.time() - age_seconds,
    )


def test_put_and_get_round_trip():
    store = DocStore()
    doc = _make_doc()
    store.put(doc)
    assert store.get("abc") is doc


def test_get_missing_raises_key_error():
    store = DocStore()
    with pytest.raises(KeyError):
        store.get("nope")


def test_delete_removes_doc():
    store = DocStore()
    store.put(_make_doc())
    store.delete("abc")
    with pytest.raises(KeyError):
        store.get("abc")


def test_evict_older_than_drops_stale_entries():
    store = DocStore()
    store.put(_make_doc("fresh", age_seconds=0.0))
    store.put(_make_doc("stale", age_seconds=120.0))
    evicted = store.evict_older_than(60.0)
    assert evicted == ["stale"]
    assert store.get("fresh") is not None
    with pytest.raises(KeyError):
        store.get("stale")


def test_set_redacted_page_attaches_to_doc():
    store = DocStore()
    store.put(_make_doc())
    page = RedactedPage(index=0, original="hello", redacted="[NAME]", entities=())
    store.set_redacted_page("abc", page)
    assert store.get("abc").redacted_pages[0] is page
