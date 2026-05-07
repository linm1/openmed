"""Download the OpenMed PII model for fully offline use.

Run once before starting the app:

    python scripts/download_model.py

The model is saved to models/pii-superclinical-small/ at the repo root.
After this, the app will use the local copy automatically (no network needed).
Set HF_HUB_OFFLINE=1 or TRANSFORMERS_OFFLINE=1 to enforce offline-only mode.
"""
from __future__ import annotations

import sys
from pathlib import Path

MODEL_ID = "OpenMed/OpenMed-PII-SuperClinical-Small-44M-v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "models" / "pii-superclinical-small"


def main() -> None:
    try:
        from transformers import AutoModelForTokenClassification, AutoTokenizer
    except ImportError:
        print(
            "ERROR: transformers is not installed. "
            "Install with:  pip install 'openmed[hf]'",
            file=sys.stderr,
        )
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {MODEL_ID} → {OUT_DIR}")

    print("  tokenizer...")
    AutoTokenizer.from_pretrained(MODEL_ID).save_pretrained(str(OUT_DIR))

    print("  model weights...")
    AutoModelForTokenClassification.from_pretrained(MODEL_ID).save_pretrained(str(OUT_DIR))

    print(f"\nDone. Model saved to {OUT_DIR}")
    print("To enforce offline mode set:  HF_HUB_OFFLINE=1")


if __name__ == "__main__":
    main()
