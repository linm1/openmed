from __future__ import annotations

import io

import pytest

docx = pytest.importorskip("docx")
pdfplumber = pytest.importorskip("pdfplumber")

from examples.redaction_studio.document_writer import write_docx, write_pdf
from examples.redaction_studio.types import PageSlice, RedactedPage, UploadedDoc


def _doc(pages_text: tuple[str, ...], fmt: str = "docx") -> UploadedDoc:
    pages = tuple(PageSlice(i, t) for i, t in enumerate(pages_text))
    return UploadedDoc(
        doc_id="abc",
        filename=f"x.{fmt}",
        fmt=fmt,
        pages=pages,
    )


def test_write_docx_emits_redacted_text_per_page():
    doc = _doc(("Page 1 original.", "Page 2 original."))
    redacted = {
        0: RedactedPage(0, "Page 1 original.", "[REDACTED 1].", ()),
        1: RedactedPage(1, "Page 2 original.", "[REDACTED 2].", ()),
    }

    out = write_docx(doc, redacted)

    parsed = docx.Document(io.BytesIO(out))
    text = "\n".join(p.text for p in parsed.paragraphs)
    assert "[REDACTED 1]" in text
    assert "[REDACTED 2]" in text
    assert "Page 1 original" not in text


def test_write_docx_falls_back_to_original_when_page_not_redacted():
    doc = _doc(("Original A.", "Original B."))
    redacted = {0: RedactedPage(0, "Original A.", "[A].", ())}
    out = write_docx(doc, redacted)
    text = "\n".join(p.text for p in docx.Document(io.BytesIO(out)).paragraphs)
    assert "[A]" in text
    assert "Original B" in text
