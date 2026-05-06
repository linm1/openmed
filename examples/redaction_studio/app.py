from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .document_parser import detect_format, parse
from .store import DocStore
from .types import UploadedDoc

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

STORE = DocStore()
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
    STORE.put(doc)
    return {"docId": doc.doc_id, "filename": doc.filename, "pageCount": len(pages), "fmt": fmt}


@app.get("/api/documents/{doc_id}")
def list_pages(doc_id: str) -> dict[str, Any]:
    try:
        doc = STORE.get(doc_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown doc_id") from exc
    return {
        "docId": doc.doc_id,
        "filename": doc.filename,
        "fmt": doc.fmt,
        "pageCount": len(doc.pages),
        "pages": [{"index": p.index, "text": p.text} for p in doc.pages],
        "redactedIndexes": sorted(doc.redacted_pages.keys()),
    }


from pydantic import BaseModel, Field

from .redactor import redact_page as _redact_page


class RedactPageRequest(BaseModel):
    docId: str
    pageIndex: int = Field(ge=0)
    method: str = "mask"


class RedactBatchRequest(BaseModel):
    docId: str
    method: str = "mask"


def _serialize_page(page) -> dict[str, Any]:
    return {
        "index": page.index,
        "original": page.original,
        "redacted": page.redacted,
        "entities": list(page.entities),
    }


@app.post("/api/redact/page")
def redact_page_endpoint(payload: RedactPageRequest) -> dict[str, Any]:
    try:
        doc = STORE.get(payload.docId)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown doc_id") from exc
    if payload.pageIndex >= len(doc.pages):
        raise HTTPException(status_code=400, detail="pageIndex out of range")
    try:
        page = _redact_page(
            index=payload.pageIndex,
            text=doc.pages[payload.pageIndex].text,
            method=payload.method,  # type: ignore[arg-type]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    STORE.set_redacted_page(payload.docId, page)
    return {"page": _serialize_page(page)}


@app.post("/api/redact/batch")
def redact_batch_endpoint(payload: RedactBatchRequest) -> dict[str, Any]:
    try:
        doc = STORE.get(payload.docId)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown doc_id") from exc
    pages_out: list[dict[str, Any]] = []
    for slice_ in doc.pages:
        try:
            page = _redact_page(index=slice_.index, text=slice_.text, method=payload.method)  # type: ignore[arg-type]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        STORE.set_redacted_page(payload.docId, page)
        pages_out.append(_serialize_page(page))
    return {"redactedCount": len(pages_out), "pages": pages_out}


from .document_writer import write as _write_doc


@app.get("/api/download/{doc_id}")
def download(doc_id: str) -> Response:
    try:
        doc = STORE.get(doc_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown doc_id") from exc
    body, media_type = _write_doc(doc, doc.redacted_pages)
    out_name = f"{Path(doc.filename).stem}.redacted.{doc.fmt}"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )


@app.delete("/api/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str) -> Response:
    try:
        STORE.get(doc_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown doc_id") from exc
    STORE.delete(doc_id)
    return Response(status_code=204)
