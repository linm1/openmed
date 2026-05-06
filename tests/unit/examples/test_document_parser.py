from __future__ import annotations

import io

import pytest

docx = pytest.importorskip("docx")

from examples.redaction_studio.document_parser import parse_docx
from examples.redaction_studio.types import PageSlice


def _build_docx(paragraphs_per_page: list[list[str]]) -> bytes:
    """Build a docx where pages are separated by hard page breaks."""
    document = docx.Document()
    for page_idx, paragraphs in enumerate(paragraphs_per_page):
        for para_idx, text in enumerate(paragraphs):
            para = document.add_paragraph(text)
            if page_idx < len(paragraphs_per_page) - 1 and para_idx == len(paragraphs) - 1:
                run = para.add_run()
                run.add_break(docx.enum.text.WD_BREAK.PAGE)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def test_parse_docx_splits_on_page_break():
    raw = _build_docx([
        ["Berlin desk reported.", "Captain Vogel left a note."],
        ["Le message final disait."],
    ])

    pages = parse_docx(raw)

    assert len(pages) == 2
    assert isinstance(pages[0], PageSlice)
    assert pages[0].index == 0
    assert "Berlin" in pages[0].text
    assert "Captain Vogel" in pages[0].text
    assert pages[1].index == 1
    assert "message final" in pages[1].text


def test_parse_docx_single_page_when_no_breaks():
    raw = _build_docx([["Single line of text.", "Another line."]])
    pages = parse_docx(raw)
    assert len(pages) == 1
    assert pages[0].text.count("\n") >= 1


reportlab = pytest.importorskip("reportlab.pdfgen.canvas")

from examples.redaction_studio.document_parser import parse_pdf, parse


def _build_pdf(pages_text: list[str]) -> bytes:
    from reportlab.pdfgen.canvas import Canvas

    buf = io.BytesIO()
    c = Canvas(buf)
    for text in pages_text:
        c.drawString(72, 720, text)
        c.showPage()
    c.save()
    return buf.getvalue()


def test_parse_pdf_yields_one_slice_per_page():
    raw = _build_pdf(["Page one carries Captain Vogel.", "Page two mentions Marseille."])
    pages = parse_pdf(raw)
    assert len(pages) == 2
    assert pages[0].index == 0
    assert "Vogel" in pages[0].text
    assert "Marseille" in pages[1].text


def test_parse_dispatcher_routes_by_filename():
    docx_raw = _build_docx([["alpha"], ["beta"]])
    pdf_raw = _build_pdf(["gamma"])
    assert len(parse("doc.docx", docx_raw)) == 2
    assert len(parse("doc.pdf", pdf_raw)) == 1
    with pytest.raises(ValueError, match="Unsupported"):
        parse("doc.txt", b"")
