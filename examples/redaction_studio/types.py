from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PageSlice:
    index: int
    text: str


@dataclass(frozen=True)
class RedactedPage:
    index: int
    original: str
    redacted: str
    entities: tuple[dict, ...]


@dataclass
class UploadedDoc:
    doc_id: str
    filename: str
    fmt: str
    pages: tuple[PageSlice, ...]
    redacted_pages: dict[int, RedactedPage] = field(default_factory=dict)
    created_at: float = 0.0
