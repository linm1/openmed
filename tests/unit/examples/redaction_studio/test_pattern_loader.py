import builtins
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from examples.redaction_studio.pattern_loader import (
    DEFAULT_PACK_PATH,
    CompiledPattern,
    load_pack,
)


def test_load_default_pack_returns_list():
    pack = load_pack()
    assert len(pack) > 0
    assert all(isinstance(p, CompiledPattern) for p in pack)
    assert all(not hasattr(p, "enabled") for p in pack)


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


def test_project_number_post_validate_removed_when_regex_is_sufficient():
    pack = load_pack()
    project_number = next(p for p in pack if p.id == "project_number_6digit")
    assert project_number.post_validate is None


def test_company_suffix_matches_organization_names():
    pack = load_pack()
    company = next(p for p in pack if p.id == "company_suffix")
    assert company.regex.search("Acme Research LLC") is not None
    assert company.regex.search("Acme Research") is None


def test_company_suffix_regex_avoids_ambiguous_whitespace_tail():
    pack = load_pack()
    company = next(p for p in pack if p.id == "company_suffix")
    assert r"(?:\s+[A-Z][A-Za-z0-9&.,'/-]*)*\s(?:" not in company.regex.pattern


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
    p.write_text(toml_text, encoding="utf-8")
    pack = load_pack(p)
    assert len(pack) == 1
    assert pack[0].id == "foo"
    assert pack[0].label == "FOO"
    assert pack[0].regex.search("foo bar") is not None


def test_load_pack_rejects_whitespace_only_required_string_fields(tmp_path):
    toml_text = '''
[meta]
id = "test_pack"
name = "Test"
version = "0.1.0"

[[patterns]]
id = "   "
label = "FOO"
regex = "\\\\bfoo\\\\b"
enabled = true
'''
    pack_path = tmp_path / "invalid.toml"
    pack_path.write_text(toml_text, encoding="utf-8")

    with pytest.raises(ValueError, match="pattern field 'id' must be a non-empty string"):
        load_pack(pack_path)


def test_pattern_loader_uses_tomli_fallback(monkeypatch):
    module_path = (
        Path(__file__).resolve().parents[4]
        / "examples"
        / "redaction_studio"
        / "pattern_loader.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pattern_loader_tomli_fallback",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    fake_tomli = types.ModuleType("tomli")
    fake_tomli.load = lambda handle: {"patterns": []}
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tomllib":
            raise ModuleNotFoundError("No module named 'tomllib'")
        if name == "tomli":
            return fake_tomli
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "tomllib", raising=False)
    monkeypatch.setitem(sys.modules, spec.name, module)

    spec.loader.exec_module(module)

    assert module.tomllib is fake_tomli