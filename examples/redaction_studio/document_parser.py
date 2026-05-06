from __future__ import annotations

import io

from .types import PageSlice

try:
    import docx as _docx
    from docx.enum.text import WD_BREAK as _WD_BREAK

    DOCX_AVAILABLE = True
except ImportError:
    _docx = None
    _WD_BREAK = None
    DOCX_AVAILABLE = False


def parse_docx(raw: bytes) -> list[PageSlice]:
    if not DOCX_AVAILABLE:
        raise RuntimeError("python-docx not installed. Install with `pip install openmed[redaction]`.")

    document = _docx.Document(io.BytesIO(raw))
    pages: list[list[str]] = [[]]
    for paragraph in document.paragraphs:
        text_parts: list[str] = []
        breaks_after = 0
        for run in paragraph.runs:
            text_parts.append(run.text)
            for br in run._element.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br"):
                if br.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type") == "page":
                    breaks_after += 1
        line = "".join(text_parts) or paragraph.text
        if line:
            pages[-1].append(line)
        for _ in range(breaks_after):
            pages.append([])

    pages = [p for p in pages if p]
    return [PageSlice(index=i, text="\n".join(p)) for i, p in enumerate(pages)] or [
        PageSlice(index=0, text="")
    ]


try:
    import pdfplumber as _pdfplumber

    PDF_AVAILABLE = True
except ImportError:
    _pdfplumber = None
    PDF_AVAILABLE = False


def parse_pdf(raw: bytes) -> list[PageSlice]:
    if not PDF_AVAILABLE:
        raise RuntimeError("pdfplumber not installed. Install with `pip install openmed[redaction]`.")
    pages: list[PageSlice] = []
    with _pdfplumber.open(io.BytesIO(raw)) as pdf:
        for i, page in enumerate(pdf.pages):
            pages.append(PageSlice(index=i, text=page.extract_text() or ""))
    return pages or [PageSlice(index=0, text="")]


def parse(filename: str, raw: bytes) -> list[PageSlice]:
    lower = filename.lower()
    if lower.endswith(".docx"):
        return parse_docx(raw)
    if lower.endswith(".pdf"):
        return parse_pdf(raw)
    raise ValueError(f"Unsupported file type: {filename}")


def detect_format(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".docx"):
        return "docx"
    if lower.endswith(".pdf"):
        return "pdf"
    raise ValueError(f"Unsupported file type: {filename}")
