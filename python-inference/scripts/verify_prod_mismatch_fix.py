"""Re-run the reproduction cases through the real /predict endpoint after the clause-split fix.

Boots the actual FastAPI app (real model, real lifespan) and posts each case from
evaluation/prod_mismatch_reproduction.json to /predict, comparing the pre-fix
reproduced_label against the post-fix response.

Usage: python scripts/verify_prod_mismatch_fix.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

INPUT_PATH = ROOT_DIR / "evaluation" / "prod_mismatch_reproduction.json"
OUTPUT_PATH = ROOT_DIR / "evaluation" / "prod_mismatch_fix_verification.json"


def main_run() -> None:
    cases = json.loads(INPUT_PATH.read_text(encoding="utf-8"))

    results = []
    with TestClient(main.app) as client:
        for case in cases:
            response = client.post("/predict", json={"text": case["text"]})
            body = response.json()
            results.append(
                {
                    "id": case["id"],
                    "text": case["text"],
                    "pre_fix_label": case["reproduced_label"],
                    "pre_fix_confidence": case["reproduced_confidence"],
                    "post_fix_label": body["label"],
                    "post_fix_confidence": round(body["score"], 4),
                    "post_fix_model_version": body["model_version"],
                }
            )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    OUTPUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main_run()
