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
