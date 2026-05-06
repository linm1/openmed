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


from examples.redaction_studio.document_writer import write as write_doc


def test_write_pdf_emits_redacted_text_per_page():
    doc = _doc(("Original A.", "Original B."), fmt="pdf")
    redacted = {0: RedactedPage(0, "Original A.", "[REDACTED A]", ())}

    out = write_pdf(doc, redacted)

    with pdfplumber.open(io.BytesIO(out)) as pdf:
        assert len(pdf.pages) == 2
        page0 = pdf.pages[0].extract_text() or ""
        page1 = pdf.pages[1].extract_text() or ""
    assert "[REDACTED A]" in page0
    assert "Original B" in page1


def test_write_dispatches_by_fmt():
    doc_docx = _doc(("a", "b"), fmt="docx")
    body, mime = write_doc(doc_docx, {})
    assert mime.startswith("application/vnd.openxmlformats")
    assert isinstance(body, bytes) and len(body) > 0

    doc_pdf = _doc(("a",), fmt="pdf")
    body_p, mime_p = write_doc(doc_pdf, {})
    assert mime_p == "application/pdf"

    bad = _doc(("a",), fmt="txt")
    with pytest.raises(ValueError):
        write_doc(bad, {})
