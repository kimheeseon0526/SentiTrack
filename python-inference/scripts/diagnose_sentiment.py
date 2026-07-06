from __future__ import annotations

import json
import sys
from pathlib import Path

from transformers import pipeline

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

import main  # noqa: E402


REVIEWS = [
    ("향은 너무 좋지만 지속력이 별로예요.", "mixed: 향 positive, 지속력 negative", ["MIXED"]),
    ("향이 은은하고 오래가서 만족해요.", "positive", ["POSITIVE"]),
    ("냄새가 독하고 머리가 아파요.", "negative", ["NEGATIVE"]),
    ("배송은 빨랐지만 포장이 아쉬워요.", "mixed: 배송 positive, 포장 negative", ["MIXED"]),
    ("그냥 무난한 향이에요.", "neutral-like", ["NEUTRAL"]),
    ("향이 나쁘지 않아요.", "positive by negation", ["POSITIVE"]),
    ("가격은 비싸지만 그만큼 만족스러워요.", "mixed/positive", ["MIXED", "POSITIVE"]),
    ("지속력은 별로지만 향 하나는 정말 최고예요.", "mixed: 지속력 negative, 향 positive", ["MIXED"]),
]


def main_cli() -> int:
    try:
        sentiment_pipeline = pipeline(
            "sentiment-analysis",
            model=main.MODEL_NAME,
            revision=main.MODEL_REVISION,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": "failed_to_load_model",
                    "model": main.MODEL_NAME,
                    "revision": main.MODEL_REVISION,
                    "detail": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    model = sentiment_pipeline.model
    config = {
        "model_name": main.MODEL_NAME,
        "model_revision": main.MODEL_REVISION,
        "id2label": getattr(model.config, "id2label", None),
        "label2id": getattr(model.config, "label2id", None),
    }

    rows = []
    for text, expected_semantic_label, expected_normalized_labels in REVIEWS:
        try:
            raw_result = sentiment_pipeline(text)[0]
            normalized_label = main.normalize_label(raw_result["label"])
            rows.append(
                {
                    "text": text,
                    "raw_label": raw_result["label"],
                    "raw_score": float(raw_result["score"]),
                    "normalized_label": normalized_label,
                    "fastapi_response": {
                        "label": normalized_label,
                        "score": float(raw_result["score"]),
                        "model_version": main.MODEL_NAME,
                    },
                    "warning": float(raw_result["score"]) < 0.7,
                    "expected_semantic_label": expected_semantic_label,
                    "expected_normalized_labels": expected_normalized_labels,
                    "matches_expected": normalized_label in expected_normalized_labels,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "text": text,
                    "error": str(exc),
                    "expected_semantic_label": expected_semantic_label,
                }
            )

    print(json.dumps({"config": config, "results": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
