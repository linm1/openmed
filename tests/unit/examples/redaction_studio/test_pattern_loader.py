import re
from pathlib import Path

from examples.redaction_studio.pattern_loader import (
    DEFAULT_PACK_PATH,
    CompiledPattern,
    load_pack,
)


def test_load_default_pack_returns_list():
    pack = load_pack()
    assert len(pack) > 0
    assert all(isinstance(p, CompiledPattern) for p in pack)


def test_disabled_patterns_excluded():
    pack = load_pack()
    ids = [p.id for p in pack]
    assert "version_string" not in ids


def test_nct_pattern_matches():
    pack = load_pack()
    nct = next(p for p in pack if p.id == "nct_study_id")
    assert nct.regex.search("NCT12345678") is not None
    assert nct.regex.search("NCT1234567") is None


def test_drug_compound_post_validate():
    pack = load_pack()
    drug = next(p for p in pack if p.id == "drug_compound_code")
    assert drug.post_validate is not None
    assert drug.post_validate.search("ISIS-12345") is not None


def test_load_custom_path(tmp_path):
    toml_text = '''
[meta]
id = "test_pack"
name = "Test"
version = "0.1.0"

[[patterns]]
id = "foo"
label = "FOO"
regex = "\\\\bfoo\\\\b"
enabled = true
'''
    p = tmp_path / "test.toml"
    p.write_text(toml_text)
    pack = load_pack(p)
    assert len(pack) == 1
    assert pack[0].id == "foo"
    assert pack[0].label == "FOO"
    assert pack[0].regex.search("foo bar") is not None