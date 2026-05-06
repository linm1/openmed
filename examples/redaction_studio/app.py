from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
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
