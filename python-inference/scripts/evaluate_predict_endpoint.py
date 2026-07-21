"""Evaluate the real /predict endpoint (clause split + MIXED, as wired in main.py) against
the 40-item sentiment_eval_reviews.jsonl dataset.

Unlike evaluate_sentiment_baseline.py / evaluate_clause_sentiment.py / evaluate_clause_normalization.py,
this hits the actual FastAPI endpoint end-to-end (real model, real lifespan) instead of calling the
underlying pipeline or experimental modules directly, so the numbers reflect production behavior.

Usage: python scripts/evaluate_predict_endpoint.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evaluate_sentiment_baseline import DEFAULT_DATASET_PATH, LABELS, load_dataset  # noqa: E402

LOW_CONFIDENCE_THRESHOLD = 0.7
DEFAULT_OUTPUT_PATH = ROOT_DIR / "evaluation" / "predict_endpoint_full40_report.json"
DISCLAIMER = "This dataset is pending manual review and must not be treated as final ground truth."


def evaluate_via_predict_endpoint(records: list[dict[str, Any]], client: TestClient) -> list[dict[str, Any]]:
    predictions = []
    for record in records:
        response = client.post("/predict", json={"text": record["text"]})
        body = response.json()
        gold_label = record["overall_label"]
        predicted_label = body["label"]
        predictions.append(
            {
                "id": record["id"],
                "text": record["text"],
                "gold_label": gold_label,
                "predicted_label": predicted_label,
                "confidence": float(body["score"]),
                "is_correct": predicted_label == gold_label,
                "is_low_confidence": float(body["score"]) < LOW_CONFIDENCE_THRESHOLD,
                "category": record["category"],
            }
        )
    return predictions


def confusion_matrix(predictions: list[dict[str, Any]], labels: tuple[str, ...]) -> dict[str, dict[str, int]]:
    matrix = {gold: {predicted: 0 for predicted in labels} for gold in labels}
    for row in predictions:
        gold = row["gold_label"]
        predicted = row["predicted_label"]
        if gold in labels and predicted in labels:
            matrix[gold][predicted] += 1
    return matrix


def per_label_metrics(
    predictions: list[dict[str, Any]], labels: tuple[str, ...]
) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    matrix = confusion_matrix(predictions, labels)
    per_label = {}
    for label in labels:
        true_positive = matrix[label][label]
        predicted_as_label = sum(matrix[gold][label] for gold in labels)
        actual_label = sum(matrix[label][predicted] for predicted in labels)
        precision = safe_divide(true_positive, predicted_as_label)
        recall = safe_divide(true_positive, actual_label)
        f1 = safe_divide(2 * precision * recall, precision + recall)
        per_label[label] = {
            "support": actual_label,
            "predicted_count": predicted_as_label,
            "true_positive": true_positive,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return per_label, matrix


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def average(values) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def main_run() -> None:
    records = load_dataset(DEFAULT_DATASET_PATH)

    with TestClient(main.app) as client:
        predictions = evaluate_via_predict_endpoint(records, client)

    per_label, matrix = per_label_metrics(predictions, LABELS)
    overall_accuracy_4class = safe_divide(
        sum(1 for row in predictions if row["is_correct"]), len(predictions)
    )

    binary_rows = [row for row in predictions if row["gold_label"] in ("POSITIVE", "NEGATIVE")]
    binary_accuracy = safe_divide(sum(1 for row in binary_rows if row["is_correct"]), len(binary_rows))

    report = {
        "metadata": {
            "evaluation_method": "REAL_PREDICT_ENDPOINT",
            "model_name": main.MODEL_NAME,
            "model_revision": main.MODEL_REVISION,
            "dataset_path": str(DEFAULT_DATASET_PATH),
            "dataset_total": len(records),
            "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
            "labels": list(LABELS),
            "disclaimer": DISCLAIMER,
        },
        "overall_accuracy_4class": overall_accuracy_4class,
        "positive_negative_accuracy": binary_accuracy,
        "macro_precision": average(m["precision"] for m in per_label.values()),
        "macro_recall": average(m["recall"] for m in per_label.values()),
        "macro_f1": average(m["f1"] for m in per_label.values()),
        "per_label": per_label,
        "confusion_matrix": matrix,
        "predictions": predictions,
    }

    print(json.dumps({k: v for k, v in report.items() if k != "predictions"}, ensure_ascii=False, indent=2))
    DEFAULT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {DEFAULT_OUTPUT_PATH}")


if __name__ == "__main__":
    main_run()
