"""Reproduce the 'negative review labeled POSITIVE' bug locally against the live model.

Loads the exact model/revision main.py uses in production and re-runs prediction on:
- the real production review row (id=2) pulled read-only from the OCI DB
- a handful of synthetic contrastive sentences with the same pattern

Usage: python scripts/reproduce_prod_mismatch.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from transformers import pipeline  # noqa: E402

from main import MODEL_NAME, MODEL_REVISION, normalize_label  # noqa: E402

CASES = [
    {
        "id": "prod-2",
        "text": "제일 좋아하는 꽃향인데 조금 인공적인거 같아요ㅠㅠㅠ",
        "stored_label": "POSITIVE",
        "stored_confidence": 0.6702,
        "stored_model_version": "jaehyeong/koelectra-base-v3-generalized-sentiment-analysis",
        "source": "OCI prod sentitrack_reviews.id=2 (created_at 2026-06-30 09:32:04)",
    },
    {
        "id": "synthetic-1",
        "text": "향은 정말 좋은데 지속력이 별로예요.",
        "source": "synthetic",
    },
    {
        "id": "synthetic-2",
        "text": "디자인은 예쁘지만 향이 너무 약해요.",
        "source": "synthetic",
    },
    {
        "id": "synthetic-3",
        "text": "포장은 마음에 드는데 배송이 너무 느렸어요.",
        "source": "synthetic",
    },
    {
        "id": "synthetic-4",
        "text": "가격은 비싸지만 향은 정말 좋아요.",
        "source": "synthetic",
    },
]


def main() -> None:
    print(f"model: {MODEL_NAME}")
    print(f"revision: {MODEL_REVISION}")
    sentiment_pipeline = pipeline("sentiment-analysis", model=MODEL_NAME, revision=MODEL_REVISION)

    results = []
    for case in CASES:
        raw = sentiment_pipeline(case["text"])[0]
        reproduced_label = normalize_label(raw["label"])
        reproduced_confidence = float(raw["score"])
        result = {
            **case,
            "reproduced_label": reproduced_label,
            "reproduced_confidence": round(reproduced_confidence, 4),
        }
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    output_path = ROOT_DIR / "evaluation" / "prod_mismatch_reproduction.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {output_path}")


if __name__ == "__main__":
    main()
