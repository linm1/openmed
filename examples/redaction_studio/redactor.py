from __future__ import annotations

from typing import Literal

from openmed import deidentify as _deidentify

from .types import RedactedPage

Method = Literal["mask", "remove", "replace", "hash", "shift_dates"]
_VALID = {"mask", "remove", "replace", "hash", "shift_dates"}


def redact_page(*, index: int, text: str, method: Method = "mask") -> RedactedPage:
    if method not in _VALID:
        raise ValueError(f"Unknown method: {method!r}. Allowed: {sorted(_VALID)}")
    if not text.strip():
        return RedactedPage(index=index, original=text, redacted=text, entities=())

    result = _deidentify(text, method=method)
    entities = tuple(
        {
            "label": getattr(e, "label", "PII"),
            "start": int(getattr(e, "start", 0)),
            "end": int(getattr(e, "end", 0)),
            "text": getattr(e, "text", ""),
            "score": float(getattr(e, "confidence", getattr(e, "score", 0.0))),
        }
        for e in (result.entities or [])
    )
    return RedactedPage(
        index=index,
        original=text,
        redacted=result.deidentified_text,
        entities=entities,
    )
