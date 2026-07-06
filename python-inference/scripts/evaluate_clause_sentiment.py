from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import main  # noqa: E402
from evaluate_sentiment_baseline import DEFAULT_DATASET_PATH, load_dataset, make_pipeline_predictor  # noqa: E402
from experiments.clause_sentiment import (  # noqa: E402
    DEFAULT_CONFIDENCE_THRESHOLD,
    analyze_clause_sentiment,
)


EXPERIMENT_NAME = "CLAUSE_HYBRID_MIXED_DETECTION"
DISCLAIMER = (
    "This experiment uses a synthetic dataset pending manual review and must not be treated "
    "as final production performance."
)
SUPPORTED_BASELINE_LABELS = ("POSITIVE", "NEGATIVE")
EXPERIMENTAL_LABELS = ("POSITIVE", "NEGATIVE", "MIXED")
NOT_TARGETED_STATUS = "NOT_TARGETED_IN_THIS_EXPERIMENT"
POLICY_REVIEW_STATUS = "LABEL_POLICY_REVIEW_REQUIRED"


def evaluate_experiment(
    records: list[dict[str, Any]],
    predictor,
    model_config: dict[str, Any],
    dataset_path: Path,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> dict[str, Any]:
    predictions = []
    for record in records:
        analysis = analyze_clause_sentiment(record["text"], predictor, confidence_threshold)
        predictions.append(build_prediction_row(record, analysis))

    summary = build_summary(predictions)
    return {
        "metadata": {
            "model_name": model_config.get("model_name", main.MODEL_NAME),
            "model_revision": model_config.get("model_revision", main.MODEL_REVISION),
            "dataset_path": str(dataset_path),
            "dataset_total": len(records),
            "experiment_name": EXPERIMENT_NAME,
            "clause_confidence_threshold": confidence_threshold,
            "supported_baseline_labels": list(SUPPORTED_BASELINE_LABELS),
            "experimental_labels": list(EXPERIMENTAL_LABELS),
            "disclaimer": DISCLAIMER,
        },
        "summary": summary,
        "predictions": predictions,
    }


def build_prediction_row(record: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    gold_label = record["overall_label"]
    baseline_label = analysis["baseline_label"]
    experimental_label = analysis["experimental_label"]
    not_targeted = gold_label == "NEUTRAL"
    policy_review_status = (
        POLICY_REVIEW_STATUS if requires_label_policy_review(record) else None
    )

    baseline_match = baseline_label == gold_label
    experimental_match = None if not_targeted else experimental_label == gold_label
    improvement = experimental_match is True and baseline_match is False
    regression = experimental_match is False and baseline_match is True

    return {
        "id": record["id"],
        "text": record["text"],
        "gold_label": gold_label,
        "category": record["category"],
        "review_status": record["review_status"],
        "source": record["source"],
        "baseline_label": baseline_label,
        "baseline_confidence": analysis["baseline_confidence"],
        "contrast_detected": analysis["contrast_detected"],
        "clauses": analysis["clauses"],
        "experimental_label": experimental_label,
        "analysis_method": analysis["analysis_method"],
        "fallback_used": analysis["fallback_used"],
        "fallback_reason": analysis["fallback_reason"],
        "baseline_match": baseline_match,
        "experimental_match": experimental_match,
        "regression": regression,
        "improvement": improvement,
        "false_mixed": experimental_label == "MIXED" and gold_label != "MIXED",
        "neutral_status": NOT_TARGETED_STATUS if not_targeted else None,
        "label_policy_status": policy_review_status,
        "aspects": record["aspects"],
        "note": record["note"],
    }


def requires_label_policy_review(record: dict[str, Any]) -> bool:
    if record["overall_label"] != "MIXED":
        return False
    aspect_sentiments = {aspect.get("sentiment") for aspect in record.get("aspects", [])}
    return "NEUTRAL" in aspect_sentiments and "NEGATIVE" in aspect_sentiments and "POSITIVE" not in aspect_sentiments


def build_summary(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    targeted = [row for row in predictions if row["gold_label"] != "NEUTRAL"]
    binary_rows = [row for row in predictions if row["gold_label"] in SUPPORTED_BASELINE_LABELS]
    mixed_rows = [row for row in predictions if row["gold_label"] == "MIXED"]
    mixed_policy_review_rows = [
        row for row in mixed_rows if row["label_policy_status"] == POLICY_REVIEW_STATUS
    ]
    mixed_without_policy_review = [
        row for row in mixed_rows if row["label_policy_status"] != POLICY_REVIEW_STATUS
    ]
    false_mixed_rows = [row for row in predictions if row["false_mixed"]]
    regressions = [row for row in predictions if row["regression"]]
    improvements = [row for row in predictions if row["improvement"]]
    fallback_rows = [row for row in predictions if row["fallback_used"]]
    confidence_withheld_rows = [
        row for row in fallback_rows if row["fallback_reason"] == "LOW_CONFIDENCE_MIXED_CANDIDATE"
    ]

    mixed_precision = precision_for_mixed(predictions)
    mixed_recall_including_policy_review = recall_for_mixed(mixed_rows)
    mixed_recall_excluding_policy_review = recall_for_mixed(mixed_without_policy_review)
    mixed_f1_including_policy_review = f1(
        mixed_precision,
        mixed_recall_including_policy_review,
    )
    mixed_f1_excluding_policy_review = f1(
        mixed_precision,
        mixed_recall_excluding_policy_review,
    )

    positive_rows = [row for row in predictions if row["gold_label"] == "POSITIVE"]
    negative_rows = [row for row in predictions if row["gold_label"] == "NEGATIVE"]

    pass_criteria = {
        "temporary_synthetic_seed_gate": True,
        "disclaimer": "Temporary experiment gate only; not final production performance.",
        "positive_negative_accuracy_at_least_0_95": accuracy(binary_rows) >= 0.95,
        "positive_negative_regression_at_most_1": len([
            row for row in regressions if row["gold_label"] in SUPPORTED_BASELINE_LABELS
        ]) <= 1,
        "false_mixed_at_most_1": len(false_mixed_rows) <= 1,
        "mixed_contrast_recall_at_least_0_75": recall_for_mixed([
            row for row in predictions if row["category"] == "mixed_contrast"
        ]) >= 0.75,
        "representative_sentence_is_mixed": any(
            row["text"] == "향은 너무 좋지만 지속력이 별로예요."
            and row["experimental_label"] == "MIXED"
            for row in predictions
        ),
        "tests_passed": "SEE_EXECUTION_LOG",
        "production_code_unchanged": "SEE_GIT_DIFF",
    }
    pass_criteria["all_measured_criteria_passed"] = all(
        value is True for key, value in pass_criteria.items() if isinstance(value, bool)
    )

    return {
        "total": len(predictions),
        "positive_retention_rate": retention_rate(positive_rows, "POSITIVE"),
        "negative_retention_rate": retention_rate(negative_rows, "NEGATIVE"),
        "positive_negative_accuracy": accuracy(binary_rows),
        "mixed_precision": mixed_precision,
        "mixed_recall_including_policy_review": mixed_recall_including_policy_review,
        "mixed_recall_excluding_policy_review": mixed_recall_excluding_policy_review,
        "mixed_f1_including_policy_review": mixed_f1_including_policy_review,
        "mixed_f1_excluding_policy_review": mixed_f1_excluding_policy_review,
        "false_mixed_count": len(false_mixed_rows),
        "false_mixed_cases": summarize_cases(false_mixed_rows),
        "regression_count": len(regressions),
        "regressions": summarize_cases(regressions),
        "baseline_exact_match_count": sum(1 for row in predictions if row["baseline_match"]),
        "experimental_exact_match_count": sum(
            1 for row in targeted if row["experimental_match"] is True
        ),
        "improvement_count": len(improvements),
        "improvements": summarize_cases(improvements),
        "worsened_count": len(regressions),
        "worsened": summarize_cases(regressions),
        "clause_split_count": sum(1 for row in predictions if row["contrast_detected"]),
        "fallback_count": len(fallback_rows),
        "fallback_cases": summarize_cases(fallback_rows),
        "confidence_withheld_mixed_count": len(confidence_withheld_rows),
        "confidence_withheld_mixed_cases": summarize_cases(confidence_withheld_rows),
        "neutral": {
            "status": NOT_TARGETED_STATUS,
            "total": sum(1 for row in predictions if row["gold_label"] == "NEUTRAL"),
            "experimental_distribution": label_distribution(
                row["experimental_label"] for row in predictions if row["gold_label"] == "NEUTRAL"
            ),
        },
        "label_policy_review_required": summarize_cases(mixed_policy_review_rows),
        "pass_criteria": pass_criteria,
    }


def retention_rate(rows: list[dict[str, Any]], label: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row["experimental_label"] == label) / len(rows)


def accuracy(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row["experimental_match"] is True) / len(rows)


def precision_for_mixed(rows: list[dict[str, Any]]) -> float:
    predicted_mixed = [row for row in rows if row["experimental_label"] == "MIXED"]
    if not predicted_mixed:
        return 0.0
    return sum(1 for row in predicted_mixed if row["gold_label"] == "MIXED") / len(predicted_mixed)


def recall_for_mixed(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row["experimental_label"] == "MIXED") / len(rows)


def f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return (2 * precision * recall) / (precision + recall)


def label_distribution(labels) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for label in labels:
        distribution[label] = distribution.get(label, 0) + 1
    return dict(sorted(distribution.items()))


def summarize_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "text": row["text"],
            "gold_label": row["gold_label"],
            "baseline_label": row["baseline_label"],
            "experimental_label": row["experimental_label"],
            "fallback_reason": row["fallback_reason"],
            "category": row["category"],
        }
        for row in rows
    ]


def format_console_summary(report: dict[str, Any], output_path: Path | None) -> str:
    summary = report["summary"]
    lines = [
        "SentiTrack clause hybrid experiment",
        f"- dataset_total: {report['metadata']['dataset_total']}",
        f"- positive_negative_accuracy: {summary['positive_negative_accuracy']:.4f}",
        f"- mixed_precision: {summary['mixed_precision']:.4f}",
        f"- mixed_recall_including_policy_review: {summary['mixed_recall_including_policy_review']:.4f}",
        f"- mixed_recall_excluding_policy_review: {summary['mixed_recall_excluding_policy_review']:.4f}",
        f"- mixed_f1_including_policy_review: {summary['mixed_f1_including_policy_review']:.4f}",
        f"- false_mixed_count: {summary['false_mixed_count']}",
        f"- regression_count: {summary['regression_count']}",
        f"- improvement_count: {summary['improvement_count']}",
        f"- fallback_count: {summary['fallback_count']}",
        f"- confidence_withheld_mixed_count: {summary['confidence_withheld_mixed_count']}",
        f"- pass_measured_criteria: {summary['pass_criteria']['all_measured_criteria_passed']}",
        f"- output: {output_path if output_path else 'not written'}",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate clause-level sentiment experiment.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--confidence-threshold", type=float, default=DEFAULT_CONFIDENCE_THRESHOLD)
    return parser.parse_args()


def main_cli() -> int:
    args = parse_args()
    try:
        records = load_dataset(args.dataset)
        predictor, model_config = make_pipeline_predictor()
        report = evaluate_experiment(
            records,
            predictor,
            model_config,
            args.dataset,
            args.confidence_threshold,
        )
    except Exception as exc:
        print(json.dumps({"error": "clause_experiment_failed", "detail": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(format_console_summary(report, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
