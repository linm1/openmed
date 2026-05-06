from __future__ import annotations

import io

from .types import RedactedPage, UploadedDoc

try:
    import docx as _docx
    from docx.enum.text import WD_BREAK as _WD_BREAK

    DOCX_AVAILABLE = True
except ImportError:
    _docx = None
    _WD_BREAK = None
    DOCX_AVAILABLE = False

try:
    from reportlab.pdfgen.canvas import Canvas as _Canvas
    from reportlab.lib.pagesizes import LETTER as _LETTER

    PDF_AVAILABLE = True
except ImportError:
    _Canvas = None
    _LETTER = None
    PDF_AVAILABLE = False


def _final_text_for(page_index: int, doc: UploadedDoc, redacted: dict[int, RedactedPage]) -> str:
    if page_index in redacted:
        return redacted[page_index].redacted
    return doc.pages[page_index].text


def write_docx(doc: UploadedDoc, redacted: dict[int, RedactedPage]) -> bytes:
    if not DOCX_AVAILABLE:
        raise RuntimeError("python-docx not installed.")
    out = _docx.Document()
    for i, _page in enumerate(doc.pages):
        body = _final_text_for(i, doc, redacted)
        for line in body.split("\n"):
            out.add_paragraph(line)
        if i < len(doc.pages) - 1:
            out.add_paragraph().add_run().add_break(_WD_BREAK.PAGE)
    buf = io.BytesIO()
    out.save(buf)
    return buf.getvalue()


def write_pdf(doc: UploadedDoc, redacted: dict[int, RedactedPage]) -> bytes:
    if not PDF_AVAILABLE:
        raise RuntimeError("reportlab not installed.")
    buf = io.BytesIO()
    c = _Canvas(buf, pagesize=_LETTER)
    width, height = _LETTER
    margin = 72
    line_height = 14
    max_chars = 90

    for i, _page in enumerate(doc.pages):
        body = _final_text_for(i, doc, redacted)
        y = height - margin
        for raw_line in body.split("\n"):
            chunks = [raw_line[j : j + max_chars] for j in range(0, max(1, len(raw_line)), max_chars)] or [""]
            for chunk in chunks:
                if y < margin:
                    c.showPage()
                    y = height - margin
                c.drawString(margin, y, chunk)
                y -= line_height
        c.showPage()
    c.save()
    return buf.getvalue()


def write(doc: UploadedDoc, redacted: dict[int, RedactedPage]) -> tuple[bytes, str]:
    if doc.fmt == "docx":
        return write_docx(doc, redacted), (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    if doc.fmt == "pdf":
        return write_pdf(doc, redacted), "application/pdf"
    raise ValueError(f"Unsupported fmt: {doc.fmt}")
