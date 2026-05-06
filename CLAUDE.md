# CLAUDE.md — OpenMed Agent Guide

> **Think Before Coding · Simplicity First · Surgical Changes · Goal-Driven Execution**

---

## 1. What This Project Is

**OpenMed v1.2.0** — Apache 2.0 medical NLP toolkit.  
Single public entry point: `from openmed import analyze_text, extract_pii, deidentify`.  
Models live on HuggingFace Hub under the `OpenMed/` org.  
Optional Swift/CoreML/MLX paths for Apple platforms.

---

## 2. Architecture (layers, bottom-up)

```
openmed/
├── core/          # Config, model loading, registry, backends protocol,
│                  # PII extraction/de-id, entity merging, i18n, quality gates
├── processing/    # Text pre/post, medical tokenizer, output types,
│                  # sentence splitting, batch orchestration, advanced NER filter
├── ner/           # Zero-shot NER: inference, model families (GLiNER, GLiNER2),
│                  # model index, label registry
├── mlx/           # Apple MLX inference backend (Apple Silicon)
├── coreml/        # CoreML conversion for iOS 16+ / macOS 13+
├── zero_shot/     # Zero-shot assets — active development, not public API yet
├── service/       # FastAPI REST service (app, runtime, schemas)
└── utils/         # Logging, profiling, input validation
swift/OpenMedKit   # Native Swift package (MLX + CoreML paths)
```

### Core contracts to know before touching anything

| Symbol | File | Role |
|--------|------|------|
| `OpenMedConfig` | `core/config.py` | Single config object; env vars `OPENMED_CONFIG`, `OPENMED_PROFILE` |
| `ModelLoader` | `core/models.py` | HF pipeline factory + in-process cache; gated by `HF_AVAILABLE` |
| `InferenceBackend` (Protocol) | `core/backends.py` | Pluggable backend; auto-detects HF → MLX |
| `ModelInfo` / `OPENMED_MODELS` | `core/model_registry.py` | Flat dict keyed by short alias (e.g. `"disease_detection_superclinical"`) |
| `EntityPrediction` / `PredictionResult` | `processing/outputs.py` | Canonical result types used everywhere |
| `PIIEntity` / `DeidentificationResult` | `core/pii.py` | PII-specific extensions of the above |
| `merge_entities_with_semantic_units` | `core/pii_entity_merger.py` | BIO-aware + regex merge; runs after model output |
| `validate_entity_spans` | `core/quality_gates.py` | **Warn-only** span guard — never silently drops entities |
| `medical_tokenize` | `processing/tokenization.py` | Output-remapping tokenizer; does NOT change model input |
| `NerRequest` / `infer` | `ner/infer.py` | Zero-shot NER entry point (GLiNER/GLiNER2 families) |

---

## 3. Optional Dependencies — Know Before Installing

All heavy deps are opt-in extras. Import guards follow the pattern:

```python
try:
    from transformers import ...
    HF_AVAILABLE = True
except (ImportError, OSError):
    HF_AVAILABLE = False
```

| Extra | Key packages | When needed |
|-------|-------------|-------------|
| `[hf]` | transformers, huggingface-hub, accelerate, tokenizers | Standard NER / PII |
| `[gliner]` | gliner, torch | Zero-shot NER (GLiNER family) |
| `[mlx]` | mlx, safetensors, tiktoken | Apple Silicon inference |
| `[coreml]` | coremltools, torch | iOS/macOS model conversion |
| `[service]` | fastapi, uvicorn | REST API |
| `[dev]` | pytest, flake8, httpx | Development / CI |

Install for development: `uv pip install -e ".[hf,dev]"`

---

## 4. Configuration System

```
~/.config/openmed/config.toml        ← user config (XDG-aware)
~/.config/openmed/profiles/<name>.toml ← named profiles
$OPENMED_CONFIG                      ← override config path
$OPENMED_PROFILE                     ← override active profile
```

Built-in profile presets: `dev`, `prod`, `test`, `fast`.  
`use_medical_tokenizer` controls output remapping only — it does not change how the model tokenizes input.

---

## 5. PII / De-identification Pipeline

1. `extract_pii(text, model_name, language)` → `DeidentificationResult` with `PIIEntity` list
2. Entity merging: `merge_entities_with_semantic_units` resolves fragmented BIO predictions using `PII_PATTERNS` (regex semantic units — dates, SSN, phone, email, etc.)
3. De-identification methods: `mask` | `remove` | `replace` | `hash` | `shift_dates`
4. Re-identification: `reidentify(deid_result, mapping)` — reversible when `return_mapping=True`
5. HIPAA Safe Harbor: all 18 identifier types covered

Multilingual: 9 languages (`en fr de it es nl hi te pt`) via `core/pii_i18n.py`.  
Default models per language live in `DEFAULT_PII_MODELS`.

---

## 6. Testing

```
tests/
├── unit/           ← fast, use mocks; no real model downloads
│   ├── test_core.py, test_pii.py, test_processing.py, ...
│   └── ner/, service/, mlx/, coreml/
└── integration/    ← require real models; marked @pytest.mark.integration
    ├── test_end_to_end.py
    └── test_sentence_detection_real.py
```

Run fast tests only: `pytest tests/unit/`  
Run all: `pytest tests/`  
Skip slow/external: `pytest -m "not integration and not slow"`

Shared fixtures (`conftest.py`): `sample_config`, `sample_text`, `mock_tokenizer`, `mock_model`.  
Never instantiate real `ModelLoader` in unit tests — use the mock fixtures.

---

## 7. Common Commands

```bash
# Development install
uv pip install -e ".[hf,dev]"

# Run unit tests
pytest tests/unit/

# Run the REST service
uvicorn openmed.service.app:app --reload

# Serve docs locally
make docs-serve           # http://127.0.0.1:8008

# Release workflow (bump version + build + publish)
make patch                # 1.2.0 → 1.2.1
make minor                # 1.2.0 → 1.3.0
make major                # 1.2.0 → 2.0.0
```

Version lives in `openmed/__about__.py`. The release script at `scripts/release/release.py` handles bumping.

---

## 8. Think Before Coding — Decision Checklist

Before writing any code, answer:

1. **Which layer does this belong to?** Core contract, processing util, NER family, service schema, or utility?
2. **Does an existing symbol already do this?** Check the table in §3 before adding new types or functions.
3. **Does it need a new optional extra?** If yes, add to `pyproject.toml` and guard imports at module level.
4. **Is the change warn-only or fail-hard?** Follow the quality gates pattern: warn and annotate, never silently drop.
5. **Does the test belong in unit or integration?** If it needs a real model, mark `@pytest.mark.integration`.

---

## 9. Simplicity First — What Not To Do

- Do not add a new `*_utils.py` helper file for a single function — put it in the nearest appropriate module.
- Do not subclass `EntityPrediction` unless you truly need PII-specific fields (like `PIIEntity` does).
- Do not bypass the backend protocol — add a new `Backend` class and register it via `get_backend()`.
- Do not change `medical_tokenize` to affect model input — it is output-remapping only.
- Do not add model weights or large binary files to the repo — all models are fetched from HuggingFace Hub.

---

## 10. Surgical Changes — How This Codebase Changes Safely

- **Adding a new NER model**: add one entry to `OPENMED_MODELS` in `core/model_registry.py`. Nothing else changes.
- **Adding a new PII language**: add to `SUPPORTED_LANGUAGES`, `DEFAULT_PII_MODELS`, and `LANGUAGE_PII_PATTERNS` in `core/pii_i18n.py`.
- **Adding a new de-id method**: add the literal to `DeidentificationMethod` alias and handle it in `deidentify()` in `core/pii.py`.
- **Adding a new model family** (e.g. GLiNER3): add `families/gliner3.py`, export from `families/__init__.py`, add dispatch in `ner/infer.py`.
- **Adding a new regex PII pattern**: add a `PIIPattern` to `PII_PATTERNS` in `core/pii_entity_merger.py`.
- **Adding a REST endpoint**: add schema to `service/schemas.py`, handler in `service/app.py`, wiring in `service/runtime.py`.

Each of these is a targeted, localized change. If your change touches more than 3 files, pause and re-evaluate scope.

---

## 11. Goal-Driven Execution — Minimal Viable Path

| Goal | Minimal path |
|------|-------------|
| Detect diseases in text | `analyze_text(text, model_name="disease_detection_superclinical")` |
| De-identify a clinical note | `deidentify(text, method="mask")` |
| Add a new language for PII | Edit `pii_i18n.py` only (3 dicts) |
| Expose a new endpoint | `schemas.py` → `app.py` → `runtime.py` |
| Run on Apple Silicon | Install `[mlx]` extra; backend auto-detects |
| Convert model for iOS | `python -m openmed.coreml.convert --model <id> --output <path>` |
| Smoke-test an install | `python tests/testInstall.py` |
| Profile inference | `enable_profiling()` + `get_profile_report()` from `openmed.utils` |

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
