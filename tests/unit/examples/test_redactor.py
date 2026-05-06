from __future__ import annotations

from types import SimpleNamespace

import pytest

from examples.redaction_studio import redactor as redactor_module
from examples.redaction_studio.redactor import redact_page
from examples.redaction_studio.types import RedactedPage


class _FakeEntity:
    def __init__(self, label, start, end, text, score):
        self.label = label
        self.start = start
        self.end = end
        self.text = text
        self.confidence = score


def _fake_deid(text, method="mask", **kwargs):
    ents = [_FakeEntity("NAME", 8, 18, "John Smith", 0.97)]
    return SimpleNamespace(
        deidentified_text="Patient [NAME] called.",
        entities=ents,
    )


def test_redact_page_returns_serializable_payload(monkeypatch):
    monkeypatch.setattr(redactor_module, "_deidentify", _fake_deid)

    page = redact_page(index=0, text="Patient John Smith called.", method="mask")

    assert isinstance(page, RedactedPage)
    assert page.index == 0
    assert page.original == "Patient John Smith called."
    assert page.redacted == "Patient [NAME] called."
    assert page.entities == (
        {"label": "NAME", "start": 8, "end": 18, "text": "John Smith", "score": 0.97},
    )


def test_redact_page_passes_method_through(monkeypatch):
    captured = {}

    def spy(text, method="mask", **kwargs):
        captured["method"] = method
        return SimpleNamespace(deidentified_text=text, entities=[])

    monkeypatch.setattr(redactor_module, "_deidentify", spy)
    redact_page(index=3, text="x", method="hash")
    assert captured["method"] == "hash"


def test_redact_page_rejects_unknown_method():
    with pytest.raises(ValueError, match="method"):
        redact_page(index=0, text="x", method="bogus")


def test_redact_page_skips_empty_text(monkeypatch):
    called = {"hit": False}

    def spy(*a, **k):
        called["hit"] = True
        return SimpleNamespace(deidentified_text="", entities=[])

    monkeypatch.setattr(redactor_module, "_deidentify", spy)
    page = redact_page(index=2, text="   ", method="mask")
    assert called["hit"] is False
    assert page.redacted == "   "
    assert page.entities == ()
