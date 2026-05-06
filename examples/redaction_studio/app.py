from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import pipeline
from .document_parser import detect_format, parse
from .document_writer import write as _write_doc
from .pattern_loader import DEFAULT_PACK_PATH, load_pack
from .store import DocStore
from .types import UploadedDoc

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

store = DocStore()
STORE = store
_pack = load_pack()
MAX_PATTERN_PREVIEW_CHARS = 120


def _load_pattern_enabled_by_default(path: Path = DEFAULT_PACK_PATH) -> dict[str, bool]:
    with path.open("rb") as handle:
        pack_data = tomllib.load(handle)

    raw_patterns = pack_data.get("patterns", [])
    if not isinstance(raw_patterns, list):
        return {}

    enabled_by_default: dict[str, bool] = {}
    for raw_pattern in raw_patterns:
        if not isinstance(raw_pattern, dict):
            continue
        pattern_id = raw_pattern.get("id")
        if isinstance(pattern_id, str) and pattern_id.strip():
            enabled_value = raw_pattern.get("enabled", True)
            enabled_by_default[pattern_id.strip()] = enabled_value if isinstance(enabled_value, bool) else True
    return enabled_by_default


_pattern_enabled_by_default = _load_pattern_enabled_by_default()
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB

app = FastAPI(
    title="OpenMed Redaction Studio",
    description="Upload DOCX/PDF, redact per-page or batch, download cleaned file.",
)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _get_doc_or_404(doc_id: str) -> UploadedDoc:
    try:
        return store.get(doc_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown doc_id") from exc


def _serialize_context(context) -> dict[str, Any]:
    return {
        "customTerms": list(context.custom_terms),
        "confidenceThreshold": context.confidence_threshold,
        "enabledPatternIds": list(context.enabled_pattern_ids),
    }


class PatternResponse(BaseModel):
    id: str
    label: str
    regex_preview: str
    enabled_by_default: bool


def _serialize_pattern(pattern) -> PatternResponse:
    regex_text = pattern.regex.pattern
    regex_preview = (
        regex_text
        if len(regex_text) <= MAX_PATTERN_PREVIEW_CHARS
        else f"{regex_text[:MAX_PATTERN_PREVIEW_CHARS - 3]}..."
    )
    return PatternResponse(
        id=pattern.id,
        label=pattern.label,
        regex_preview=regex_preview,
        enabled_by_default=_pattern_enabled_by_default.get(pattern.id, True),
    )


def _run_pipeline(doc: UploadedDoc) -> tuple[list[Any], dict[str, dict]]:
    pages, summary = pipeline.run(doc, _pack, doc.context)
    doc.redacted_pages.clear()
    for page in pages:
        doc.redacted_pages[page.index] = page
    doc.canonical_summary.clear()
    doc.canonical_summary.update(summary)
    return pages, doc.canonical_summary


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")
    try:
        fmt = detect_format(file.filename or "")
        pages = tuple(parse(file.filename or "", raw))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc = UploadedDoc(
        doc_id=uuid.uuid4().hex,
        filename=file.filename or f"upload.{fmt}",
        fmt=fmt,
        pages=pages,
        created_at=time.time(),
    )
    store.put(doc)
    return {"docId": doc.doc_id, "filename": doc.filename, "pageCount": len(pages), "fmt": fmt}


@app.get("/api/patterns", response_model=list[PatternResponse])
def list_patterns() -> list[PatternResponse]:
    return [_serialize_pattern(pattern) for pattern in _pack]


@app.get("/api/documents/{doc_id}")
def list_pages(doc_id: str) -> dict[str, Any]:
    doc = _get_doc_or_404(doc_id)
    return {
        "docId": doc.doc_id,
        "filename": doc.filename,
        "fmt": doc.fmt,
        "pageCount": len(doc.pages),
        "pages": [{"index": p.index, "text": p.text} for p in doc.pages],
        "redactedIndexes": sorted(doc.redacted_pages.keys()),
        "context": _serialize_context(doc.context),
    }


class LegacyCompatibleRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RedactPageRequest(LegacyCompatibleRequest):
    docId: str
    pageIndex: int = Field(ge=0)


class RedactBatchRequest(LegacyCompatibleRequest):
    docId: str


class UpdateContextRequest(BaseModel):
    customTerms: list[str] | None = None
    confidenceThreshold: float | None = Field(default=None, ge=0.0, le=1.0)
    enabledPatternIds: list[str] | None = None


class DocumentRedactPageRequest(BaseModel):
    page: int = Field(ge=0)


def _serialize_page(page) -> dict[str, Any]:
    return {
        "index": page.index,
        "original": page.original,
        "redacted": page.redacted,
        "entities": list(page.entities),
    }


@app.patch("/api/documents/{doc_id}/context")
def update_context(doc_id: str, payload: UpdateContextRequest) -> dict[str, Any]:
    try:
        doc = store.update_context(
            doc_id,
            custom_terms=payload.customTerms,
            confidence_threshold=payload.confidenceThreshold,
            enabled_pattern_ids=payload.enabledPatternIds,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown doc_id") from exc
    return {"docId": doc.doc_id, "context": _serialize_context(doc.context)}


@app.post("/api/documents/{doc_id}/redact-page")
def redact_document_page(doc_id: str, payload: DocumentRedactPageRequest) -> dict[str, Any]:
    doc = _get_doc_or_404(doc_id)
    if payload.page >= len(doc.pages):
        raise HTTPException(status_code=400, detail="page out of range")
    _run_pipeline(doc)
    page = doc.redacted_pages[payload.page]
    return {
        "pageNumber": page.index,
        "redactedText": page.redacted,
        "canonical": dict(doc.canonical_summary),
    }


@app.post("/api/redact/page")
def redact_page_endpoint(payload: RedactPageRequest) -> dict[str, Any]:
    doc = _get_doc_or_404(payload.docId)
    if payload.pageIndex >= len(doc.pages):
        raise HTTPException(status_code=400, detail="pageIndex out of range")
    _run_pipeline(doc)
    page = doc.redacted_pages[payload.pageIndex]
    return {"page": _serialize_page(page)}


@app.post("/api/redact/batch")
def redact_batch_endpoint(payload: RedactBatchRequest) -> dict[str, Any]:
    doc = _get_doc_or_404(payload.docId)
    _run_pipeline(doc)
    pages_out = [_serialize_page(doc.redacted_pages[slice_.index]) for slice_ in doc.pages]
    return {"redactedCount": len(pages_out), "pages": pages_out}


@app.get("/api/download/{doc_id}")
def download(doc_id: str) -> Response:
    doc = _get_doc_or_404(doc_id)
    body, media_type = _write_doc(doc, doc.redacted_pages)
    out_name = f"{Path(doc.filename).stem}.redacted.{doc.fmt}"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )


@app.delete("/api/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str) -> Response:
    _get_doc_or_404(doc_id)
    store.delete(doc_id)
    return Response(status_code=204)
