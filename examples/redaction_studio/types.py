from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, init=False)
class PageSlice:
    page_number: int
    text: str
    original_bytes: bytes = b""

    def __init__(
        self,
        page_number: int | None = None,
        text: str = "",
        original_bytes: bytes = b"",
        *,
        index: int | None = None,
    ) -> None:
        if (
            page_number is not None
            and index is not None
            and page_number != index
        ):
            raise TypeError(
                "PageSlice received conflicting values for `page_number` and `index`."
            )
        resolved_page_number = page_number if page_number is not None else index
        if resolved_page_number is None:
            raise TypeError("PageSlice requires `page_number` or `index`.")
        object.__setattr__(self, "page_number", resolved_page_number)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "original_bytes", original_bytes)

    @property
    def index(self) -> int:
        return self.page_number


@dataclass(frozen=True)
class RedactedPage:
    index: int
    original: str
    redacted: str
    entities: tuple[dict, ...]


@dataclass(frozen=True)
class RawEntity:
    page: int
    start: int
    end: int
    surface_text: str
    label: str
    source: str
    score: float


@dataclass(frozen=True)
class CanonicalEntity:
    token: str
    label: str
    occurrences: int


@dataclass(frozen=True)
class RedactionContext:
    custom_terms: tuple[str, ...] = ()
    confidence_threshold: float = 0.85
    enabled_pattern_ids: tuple[str, ...] = ()


@dataclass
class UploadedDoc:
    doc_id: str
    filename: str
    pages: tuple[PageSlice, ...] | list[PageSlice]
    fmt: str = ""
    redacted_pages: dict[int, RedactedPage] = field(default_factory=dict)
    context: RedactionContext = field(default_factory=RedactionContext)
    canonical_summary: dict[str, dict] = field(default_factory=dict)
    created_at: float = 0.0
    content: bytes = b""
    uploaded_at: datetime | None = None

    def __post_init__(self) -> None:
        self.pages = tuple(self.pages)
        self.redacted_pages = dict(self.redacted_pages)
        self.canonical_summary = dict(self.canonical_summary)
        if not self.fmt:
            self.fmt = _infer_format(self.filename)
        if self.created_at == 0.0 and self.uploaded_at is not None:
            uploaded_at = self.uploaded_at
            if uploaded_at.tzinfo is None:
                uploaded_at = uploaded_at.replace(tzinfo=UTC)
            self.created_at = uploaded_at.timestamp()


def _infer_format(filename: str) -> str:
    parts = filename.rsplit(".", maxsplit=1)
    if len(parts) == 2:
        return parts[1].lower()
    return ""
