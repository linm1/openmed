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
from .types import RedactedPage, RedactionContext
from .types import UploadedDoc

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

store = DocStore()
MAX_PATTERN_PREVIEW_CHARS = 120
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


class PatternResponse(BaseModel):
    id: str
    label: str
    regex_preview: str
    enabled_by_default: bool


def _build_regex_preview(regex_text: str) -> str:
    return (
        regex_text
        if len(regex_text) <= MAX_PATTERN_PREVIEW_CHARS
        else f"{regex_text[:MAX_PATTERN_PREVIEW_CHARS - 3]}..."
    )


def _load_pattern_catalog(path: Path = DEFAULT_PACK_PATH) -> list[PatternResponse]:
    with path.open("rb") as handle:
        pack_data = tomllib.load(handle)

    raw_patterns = pack_data.get("patterns", [])
    if not isinstance(raw_patterns, list):
        return []

    pattern_catalog: list[PatternResponse] = []
    for raw_pattern in raw_patterns:
        if not isinstance(raw_pattern, dict):
            continue
        pattern_id = raw_pattern.get("id")
        label = raw_pattern.get("label")
        regex_text = raw_pattern.get("regex")
        if not isinstance(pattern_id, str) or not pattern_id.strip():
            continue
        if not isinstance(label, str) or not label.strip():
            continue
        if not isinstance(regex_text, str) or not regex_text.strip():
            continue
        enabled_value = raw_pattern.get("enabled", True)
        pattern_catalog.append(
            PatternResponse(
                id=pattern_id.strip(),
                label=label.strip(),
                regex_preview=_build_regex_preview(regex_text.strip()),
                enabled_by_default=(enabled_value if isinstance(enabled_value, bool) else True),
            )
        )
    return pattern_catalog


_pack = load_pack()
_pattern_catalog = _load_pattern_catalog()

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


def _serialize_context(context: RedactionContext) -> dict[str, Any]:
    return {
        "customTerms": list(context.custom_terms),
        "confidenceThreshold": context.confidence_threshold,
        "enabledPatternIds": list(context.enabled_pattern_ids),
    }


def _run_pipeline(doc: UploadedDoc) -> UploadedDoc:
    pages, summary = pipeline.run(doc, _pack, doc.context)
    try:
        return store.replace_pipeline_output(doc.doc_id, pages=pages, summary=summary)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown doc_id") from exc


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
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
    return list(_pattern_catalog)


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


def _serialize_page(page: RedactedPage) -> dict[str, Any]:
    return {
        "index": page.index,
        "original": page.original,
        "redacted": page.redacted,
        "entities": list(page.entities),
    }


def _uploaded_filename_stem(filename: str) -> str:
    leaf_name = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    stem, has_suffix, _suffix = leaf_name.rpartition(".")
    return stem if has_suffix else leaf_name


def _sanitize_download_filename_stem(filename: str) -> str:
    safe_stem = _uploaded_filename_stem(filename)
    for unsafe_char in ('"', "\\", "\r", "\n"):
        safe_stem = safe_stem.replace(unsafe_char, "_")
    safe_stem = safe_stem.strip(" .")
    return safe_stem or "document"


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
    doc = _run_pipeline(doc)
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
    doc = _run_pipeline(doc)
    page = doc.redacted_pages[payload.pageIndex]
    return {"page": _serialize_page(page)}


@app.post("/api/redact/batch")
def redact_batch_endpoint(payload: RedactBatchRequest) -> dict[str, Any]:
    doc = _get_doc_or_404(payload.docId)
    doc = _run_pipeline(doc)
    pages_out = [_serialize_page(doc.redacted_pages[slice_.index]) for slice_ in doc.pages]
    return {"redactedCount": len(pages_out), "pages": pages_out}


@app.get("/api/download/{doc_id}")
def download(doc_id: str) -> Response:
    doc = _get_doc_or_404(doc_id)
    body, media_type = _write_doc(doc, doc.redacted_pages)
    out_name = f"{_sanitize_download_filename_stem(doc.filename)}.redacted.{doc.fmt}"
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
