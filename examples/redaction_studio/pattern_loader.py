from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

DEFAULT_PACK_PATH = Path(__file__).resolve().parent / "patterns" / "clinical_trial.toml"


@dataclass(frozen=True)
class CompiledPattern:
    id: str
    label: str
    regex: re.Pattern[str]
    post_validate: re.Pattern[str] | None


PatternPack = list[CompiledPattern]


def _require_string(value: object, *, field_name: str, normalize: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"pattern field '{field_name}' must be a non-empty string")
    return value.strip() if normalize else value


def _compile_regex(value: object, *, field_name: str, pattern_id: str) -> re.Pattern[str]:
    regex_text = _require_string(value, field_name=field_name, normalize=True)
    try:
        return re.compile(regex_text)
    except re.error as exc:
        raise ValueError(
            f"pattern '{pattern_id}' has invalid {field_name}: {regex_text!r}"
        ) from exc


def _compile_pattern(raw_pattern: object) -> CompiledPattern | None:
    if not isinstance(raw_pattern, dict):
        raise ValueError("each pattern entry must be a TOML table")

    enabled_value = raw_pattern.get("enabled", True)
    if not isinstance(enabled_value, bool):
        pattern_id_value = raw_pattern.get("id")
        pattern_id = (
            pattern_id_value.strip()
            if isinstance(pattern_id_value, str) and pattern_id_value.strip()
            else "<unknown>"
        )
        raise ValueError(f"pattern '{pattern_id}' field 'enabled' must be a bool")
    if not enabled_value:
        return None

    pattern_id = _require_string(raw_pattern.get("id"), field_name="id", normalize=True)
    label = _require_string(raw_pattern.get("label"), field_name="label", normalize=True)

    post_validate_value = raw_pattern.get("post_validate")
    post_validate = (
        None
        if post_validate_value is None
        else _compile_regex(
            post_validate_value,
            field_name="post_validate",
            pattern_id=pattern_id,
        )
    )

    return CompiledPattern(
        id=pattern_id,
        label=label,
        regex=_compile_regex(raw_pattern.get("regex"), field_name="regex", pattern_id=pattern_id),
        post_validate=post_validate,
    )


def load_pack(path: Path | None = None) -> PatternPack:
    pack_path = DEFAULT_PACK_PATH if path is None else path
    with pack_path.open("rb") as handle:
        pack_data = tomllib.load(handle)

    raw_patterns = pack_data.get("patterns", [])
    if not isinstance(raw_patterns, list):
        raise ValueError("pattern pack must define [[patterns]] entries")

    compiled_patterns: PatternPack = []
    for raw_pattern in raw_patterns:
        compiled_pattern = _compile_pattern(raw_pattern)
        if compiled_pattern is not None:
            compiled_patterns.append(compiled_pattern)
    return compiled_patterns