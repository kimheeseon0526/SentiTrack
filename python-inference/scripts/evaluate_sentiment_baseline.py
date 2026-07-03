from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

from transformers import pipeline

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

import main  # noqa: E402


LABELS = ("POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL")
SUPPORTED_MODEL_LABELS = ("POSITIVE", "NEGATIVE")
UNSUPPORTED_EXPECTED_LABELS = ("MIXED", "NEUTRAL")
REQUIRED_FIELDS = (
    "id",
    "text",
    "overall_label",
    "aspects",
    "category",
    "note",
    "review_status",
    "source",
)
DEFAULT_DATASET_PATH = ROOT_DIR / "evaluation" / "sentiment_eval_reviews.jsonl"
LOW_CONFIDENCE_THRESHOLD = 0.7
EXPECTED_REVIEW_STATUS = "PENDING_MANUAL_REVIEW"
EXPECTED_SOURCE = "SYNTHETIC"
DISCLAIMER = "This dataset is pending manual review and must not be treated as final ground truth."

PredictionFn = Callable[[str], dict[str, Any]]


def load_dataset(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc

            validate_record(record, path, line_number)
            record_id = record["id"]
            if record_id in seen_ids:
                raise ValueError(f"{path}:{line_number}: duplicate id {record_id!r}")
            seen_ids.add(record_id)
            records.append(record)

    if not records:
        raise ValueError(f"{path}: dataset is empty")

    return records


def validate_record(record: dict[str, Any], path: Path, line_number: int) -> None:
    prefix = f"{path}:{line_number}"

    for field in REQUIRED_FIELDS:
        if field not in record:
            raise ValueError(f"{prefix}: missing required field {field!r}")

    for field in ("id", "text", "category", "note", "review_status", "source"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise ValueError(f"{prefix}: {field} must be a non-empty string")

    gold_label = record.get("overall_label")
    if gold_label not in LABELS:
        raise ValueError(f"{prefix}: overall_label must be one of {', '.join(LABELS)}")

    if record["review_status"] != EXPECTED_REVIEW_STATUS:
        raise ValueError(f"{prefix}: review_status must be {EXPECTED_REVIEW_STATUS}")
    if record["source"] != EXPECTED_SOURCE:
        raise ValueError(f"{prefix}: source must be {EXPECTED_SOURCE}")

    aspects = record.get("aspects")
    if not isinstance(aspects, list):
        raise ValueError(f"{prefix}: aspects must be a list")

    for aspect_index, aspect in enumerate(aspects):
        if not isinstance(aspect, dict):
            raise ValueError(f"{prefix}: aspect {aspect_index} must be an object")
        if not isinstance(aspect.get("name"), str) or not aspect["name"].strip():
            raise ValueError(f"{prefix}: aspect {aspect_index} name must be a non-empty string")
        if aspect.get("sentiment") not in SUPPORTED_MODEL_LABELS + ("NEUTRAL",):
            raise ValueError(
                f"{prefix}: aspect {aspect_index} sentiment must be POSITIVE, NEGATIVE, or NEUTRAL"
            )


def make_pipeline_predictor() -> tuple[PredictionFn, dict[str, Any]]:
    sentiment_pipeline = pipeline(
        "sentiment-analysis",
        model=main.MODEL_NAME,
        revision=main.MODEL_REVISION,
    )

    model = sentiment_pipeline.model
    config = {
        "model_name": main.MODEL_NAME,
        "model_revision": main.MODEL_REVISION,
        "id2label": getattr(model.config, "id2label", None),
        "label2id": getattr(model.config, "label2id", None),
    }

    def predict(text: str) -> dict[str, Any]:
        raw_result = sentiment_pipeline(text)[0]
        normalized_label = main.normalize_label(raw_result["label"])
        score = float(raw_result["score"])
        return {
            "raw_label": raw_result["label"],
            "score": score,
            "normalized_label": normalized_label,
        }

    return predict, config


def evaluate_records(
    records: list[dict[str, Any]],
    predictor: PredictionFn,
    model_config: dict[str, Any] | None = None,
    dataset_path: Path | None = None,
) -> dict[str, Any]:
    predictions = [evaluate_record(record, predictor) for record in records]
    metadata = build_metadata(records, model_config or {}, dataset_path)
    summary = build_summary(predictions)
    binary_supported_metrics = calculate_supported_metrics(
        [row for row in predictions if row["gold_label"] in SUPPORTED_MODEL_LABELS],
        SUPPORTED_MODEL_LABELS,
    )
    four_class_diagnostic_metrics = calculate_diagnostic_metrics(predictions)

    return {
        "metadata": metadata,
        "model": model_config or {},
        "dataset": summarize_dataset(records),
        "summary": summary,
        "four_class_diagnostic_metrics": four_class_diagnostic_metrics,
        "binary_supported_metrics": binary_supported_metrics,
        "binary_only_metrics": binary_supported_metrics,
        "predictions": predictions,
    }


def evaluate_record(record: dict[str, Any], predictor: PredictionFn) -> dict[str, Any]:
    prediction = predictor(record["text"])
    predicted_label = prediction["normalized_label"]
    if predicted_label not in SUPPORTED_MODEL_LABELS:
        raise ValueError(f"{record['id']}: predicted label {predicted_label!r} is unsupported")

    score = float(prediction["score"])
    gold_label = record["overall_label"]
    result_status = determine_result_status(gold_label, predicted_label)
    is_correct = None if result_status == "UNSUPPORTED_EXPECTED_LABEL" else result_status == "MATCH"
    is_high_confidence_mismatch = (
        result_status == "MISMATCH" and score >= LOW_CONFIDENCE_THRESHOLD
    )
    is_high_confidence_unsupported = (
        result_status == "UNSUPPORTED_EXPECTED_LABEL" and score >= LOW_CONFIDENCE_THRESHOLD
    )

    return {
        "id": record["id"],
        "text": record["text"],
        "gold_label": gold_label,
        "predicted_label": predicted_label,
        "raw_label": prediction.get("raw_label"),
        "confidence": score,
        "result_status": result_status,
        "is_correct": is_correct,
        "is_low_confidence": score < LOW_CONFIDENCE_THRESHOLD,
        "is_high_confidence_mismatch": is_high_confidence_mismatch,
        "is_high_confidence_unsupported": is_high_confidence_unsupported,
        "aspects": record["aspects"],
        "category": record["category"],
        "note": record["note"],
        "review_status": record["review_status"],
        "source": record["source"],
    }


def determine_result_status(gold_label: str, predicted_label: str) -> str:
    if gold_label in UNSUPPORTED_EXPECTED_LABELS:
        return "UNSUPPORTED_EXPECTED_LABEL"
    if predicted_label == gold_label:
        return "MATCH"
    return "MISMATCH"


def build_metadata(
    records: list[dict[str, Any]],
    model_config: dict[str, Any],
    dataset_path: Path | None,
) -> dict[str, Any]:
    return {
        "model_name": model_config.get("model_name", main.MODEL_NAME),
        "model_revision": model_config.get("model_revision", main.MODEL_REVISION),
        "dataset_path": str(dataset_path or DEFAULT_DATASET_PATH),
        "dataset_total": len(records),
        "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
        "supported_model_labels": list(SUPPORTED_MODEL_LABELS),
        "unsupported_expected_labels": list(UNSUPPORTED_EXPECTED_LABELS),
        "disclaimer": DISCLAIMER,
    }


def summarize_dataset(records: list[dict[str, Any]]) -> dict[str, Any]:
    distribution = Counter(record["overall_label"] for record in records)
    category_distribution = Counter(record["category"] for record in records)
    return {
        "total": len(records),
        "label_distribution": {label: distribution.get(label, 0) for label in LABELS},
        "category_distribution": dict(sorted(category_distribution.items())),
    }


def build_summary(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    high_confidence_mismatches = [
        summarize_case(row) for row in predictions if row["is_high_confidence_mismatch"]
    ]
    high_confidence_unsupported_cases = [
        summarize_case(row) for row in predictions if row["is_high_confidence_unsupported"]
    ]

    return {
        "result_status_counts": count_by(predictions, "result_status"),
        "unsupported_label_distribution": unsupported_label_distribution(predictions),
        "confidence_statistics": confidence_statistics(predictions),
        "high_confidence_mismatch_count": len(high_confidence_mismatches),
        "high_confidence_mismatches": high_confidence_mismatches,
        "high_confidence_unsupported_count": len(high_confidence_unsupported_cases),
        "high_confidence_unsupported_cases": high_confidence_unsupported_cases,
    }


def summarize_case(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "text": row["text"],
        "gold_label": row["gold_label"],
        "predicted_label": row["predicted_label"],
        "confidence": row["confidence"],
        "category": row["category"],
    }


def unsupported_label_distribution(predictions: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    distribution = {
        label: {predicted: 0 for predicted in SUPPORTED_MODEL_LABELS}
        for label in UNSUPPORTED_EXPECTED_LABELS
    }

    for row in predictions:
        gold_label = row["gold_label"]
        predicted_label = row["predicted_label"]
        if gold_label in UNSUPPORTED_EXPECTED_LABELS and predicted_label in SUPPORTED_MODEL_LABELS:
            distribution[gold_label][predicted_label] += 1

    return distribution


def confidence_statistics(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall_average_confidence": average_confidence(predictions),
        "average_confidence_by_gold_label": {
            label: average_confidence(row for row in predictions if row["gold_label"] == label)
            for label in LABELS
        },
        "average_confidence_by_predicted_label": {
            label: average_confidence(row for row in predictions if row["predicted_label"] == label)
            for label in SUPPORTED_MODEL_LABELS
        },
        "mismatch_average_confidence": average_confidence(
            row for row in predictions if row["result_status"] == "MISMATCH"
        ),
        "unsupported_expected_label_average_confidence": average_confidence(
            row for row in predictions if row["result_status"] == "UNSUPPORTED_EXPECTED_LABEL"
        ),
    }


def calculate_diagnostic_metrics(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(predictions)
    match_count = sum(1 for row in predictions if row["result_status"] == "MATCH")
    low_confidence_count = sum(1 for row in predictions if row["is_low_confidence"])

    return {
        "description": (
            "Diagnostic metric over POSITIVE, NEGATIVE, MIXED, and NEUTRAL. "
            "MIXED/NEUTRAL are unsupported expected labels for the current binary model."
        ),
        "total": total,
        "match_count": match_count,
        "mismatch_count": sum(1 for row in predictions if row["result_status"] == "MISMATCH"),
        "unsupported_expected_label_count": sum(
            1 for row in predictions if row["result_status"] == "UNSUPPORTED_EXPECTED_LABEL"
        ),
        "diagnostic_exact_match_rate": safe_divide(match_count, total),
        "low_confidence_count": low_confidence_count,
        "low_confidence_rate": safe_divide(low_confidence_count, total),
        "confusion_matrix": confusion_matrix(predictions, LABELS, SUPPORTED_MODEL_LABELS),
    }


def calculate_supported_metrics(
    predictions: list[dict[str, Any]],
    labels: tuple[str, ...],
) -> dict[str, Any]:
    total = len(predictions)
    correct = sum(1 for row in predictions if row["is_correct"] is True)
    low_confidence_count = sum(1 for row in predictions if row["is_low_confidence"])
    matrix = confusion_matrix(predictions, labels, labels)

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
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    return {
        "description": "Evaluation over currently supported expected labels only: POSITIVE and NEGATIVE.",
        "total": total,
        "accuracy": safe_divide(correct, total),
        "low_confidence_count": low_confidence_count,
        "low_confidence_rate": safe_divide(low_confidence_count, total),
        "macro_precision": average(metric["precision"] for metric in per_label.values()),
        "macro_recall": average(metric["recall"] for metric in per_label.values()),
        "macro_f1": average(metric["f1"] for metric in per_label.values()),
        "per_label": per_label,
        "confusion_matrix": matrix,
    }


def confusion_matrix(
    predictions: list[dict[str, Any]],
    gold_labels: tuple[str, ...],
    predicted_labels: tuple[str, ...],
) -> dict[str, dict[str, int]]:
    matrix = {gold: {predicted: 0 for predicted in predicted_labels} for gold in gold_labels}

    for row in predictions:
        gold_label = row["gold_label"]
        predicted_label = row["predicted_label"]
        if gold_label in gold_labels and predicted_label in predicted_labels:
            matrix[gold_label][predicted_label] += 1

    return matrix


def count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(row[field] for row in rows)
    return dict(sorted(counts.items()))


def average_confidence(rows: Iterable[dict[str, Any]]) -> float:
    values = [float(row["confidence"]) for row in rows]
    if not values:
        return 0.0
    return sum(values) / len(values)


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def average(values: Iterable[float]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(items) / len(items)


def format_console_summary(report: dict[str, Any], output_path: Path | None) -> str:
    dataset = report["dataset"]
    summary = report["summary"]
    binary_metrics = report["binary_supported_metrics"]
    confidence = summary["confidence_statistics"]
    unsupported = summary["unsupported_label_distribution"]

    lines = [
        "SentiTrack KoELECTRA baseline evaluation",
        f"- dataset_total: {dataset['total']}",
        f"- label_distribution: {json.dumps(dataset['label_distribution'], ensure_ascii=False)}",
        (
            "- binary_supported_accuracy: "
            f"{binary_metrics['accuracy']:.4f}, "
            f"macro_f1: {binary_metrics['macro_f1']:.4f}"
        ),
        f"- MIXED forced_distribution: {json.dumps(unsupported['MIXED'], ensure_ascii=False)}",
        f"- NEUTRAL forced_distribution: {json.dumps(unsupported['NEUTRAL'], ensure_ascii=False)}",
        f"- overall_average_confidence: {confidence['overall_average_confidence']:.4f}",
        f"- high_confidence_mismatch_count: {summary['high_confidence_mismatch_count']}",
        f"- high_confidence_unsupported_count: {summary['high_confidence_unsupported_count']}",
        f"- output: {output_path if output_path else 'not written'}",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate current KoELECTRA sentiment baseline.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="Path to a JSONL evaluation dataset.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the full JSON evaluation report.",
    )
    return parser.parse_args()


def main_cli() -> int:
    args = parse_args()

    try:
        records = load_dataset(args.dataset)
        predictor, model_config = make_pipeline_predictor()
        report = evaluate_records(records, predictor, model_config, args.dataset)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": "baseline_evaluation_failed",
                    "detail": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(format_console_summary(report, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
