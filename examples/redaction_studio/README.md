# Redaction Studio

Upload DOCX/PDF, redact via `openmed.deidentify`, download cleaned file.

## Run

```bash
uv pip install -e ".[hf,dev,redaction,service]"
uvicorn examples.redaction_studio.app:app --reload --port 8770
```

Open http://127.0.0.1:8770/

## API

| Method | Path | Body |
|--------|------|------|
| POST | /api/upload | multipart `file` (.docx or .pdf) |
| GET | /api/documents/{doc_id} | — |
| POST | /api/redact/page | `{docId, pageIndex, method}` |
| POST | /api/redact/batch | `{docId, method}` |
| GET | /api/download/{doc_id} | — |
| DELETE | /api/documents/{doc_id} | — |

`method` ∈ `mask | remove | replace | hash | shift_dates`.

## Limits

- 25 MB upload cap.
- Documents live in-process — no disk persistence; restart clears state.
- DOCX page detection follows hard page breaks; flowing DOCX without breaks → single page.
- PDF text extraction is layout-best-effort (pdfplumber); scanned PDFs need OCR (out of scope).
- PDF output re-renders text-only (loses original visual layout). For visual-fidelity redaction overlays, post-process with pypdf annotations — out of MVP scope.
