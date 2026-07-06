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
from experiments.clause_normalization import STRATEGIES, normalize_clause  # noqa: E402
from experiments.clause_sentiment import (  # noqa: E402
    DEFAULT_CONFIDENCE_THRESHOLD,
    STANDALONE_CONNECTORS,
    combine_clause_predictions,
    split_contrast_clauses,
)


EXPERIMENT_NAME = "CLAUSE_NORMALIZATION_STRATEGY_COMPARISON"
DISCLAIMER = (
    "This experiment uses a synthetic dataset pending manual review and must not be treated "
    "as final production performance."
)
SUPPORTED_BASELINE_LABELS = ("POSITIVE", "NEGATIVE")
TARGETED_EXPERIMENTAL_LABEL = "MIXED"
NOT_TARGETED_STATUS = "NOT_TARGETED_IN_THIS_EXPERIMENT"
POLICY_REVIEW_STATUS = "LABEL_POLICY_REVIEW_REQUIRED"
REPRESENTATIVE_TEXT = "향은 너무 좋지만 지속력이 별로예요."


def make_cached_predictor(predictor):
    cache: dict[str, dict[str, Any]] = {}

    def predict(text: str) -> dict[str, Any]:
        if text not in cache:
            prediction = predictor(text)
            cache[text] = {
                "label": prediction.get("normalized_label", prediction.get("label")),
                "confidence": float(prediction.get("score", prediction.get("confidence"))),
                "raw_label": prediction.get("raw_label"),
            }
        return cache[text]

    return predict


def evaluate_normalization_experiment(
    records: list[dict[str, Any]],
    predictor,
    model_config: dict[str, Any],
    dataset_path: Path,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> dict[str, Any]:
    cached_predict = make_cached_predictor(predictor)
    predictions = [
        evaluate_record(record, cached_predict, confidence_threshold)
        for record in records
    ]
    strategy_summaries = {
        strategy: summarize_strategy(predictions, strategy)
        for strategy in STRATEGIES
    }
    report = {
        "metadata": {
            "experiment_name": EXPERIMENT_NAME,
            "model_name": model_config.get("model_name", main.MODEL_NAME),
            "model_revision": model_config.get("model_revision", main.MODEL_REVISION),
            "dataset_path": str(dataset_path),
            "dataset_total": len(records),
            "strategies": list(STRATEGIES),
            "confidence_threshold": confidence_threshold,
            "supported_baseline_labels": list(SUPPORTED_BASELINE_LABELS),
            "targeted_experimental_label": TARGETED_EXPERIMENTAL_LABEL,
            "disclaimer": DISCLAIMER,
        },
        "baseline_summary": summarize_baseline(predictions),
        "strategy_summaries": strategy_summaries,
        "strategy_comparison": compare_strategies(strategy_summaries, predictions),
        "representative_case": representative_case(predictions),
        "pattern_statistics": pattern_statistics(predictions),
        "improvements": {
            strategy: summarize_cases(
                row for row in predictions if row["strategy_results"][strategy]["improvement"]
            )
            for strategy in STRATEGIES
        },
        "regressions": {
            strategy: summarize_cases(
                row for row in predictions if row["strategy_results"][strategy]["regression"]
            )
            for strategy in STRATEGIES
        },
        "false_mixed_cases": {
            strategy: summarize_cases(
                row for row in predictions if row["strategy_results"][strategy]["false_mixed"]
            )
            for strategy in STRATEGIES
        },
        "fallback_cases": {
            strategy: summarize_cases(
                row
                for row in predictions
                if row["strategy_results"][strategy]["fallback_reason"] is not None
            )
            for strategy in STRATEGIES
        },
        "all_predictions": predictions,
    }
    return report


def evaluate_record(record: dict[str, Any], predictor, confidence_threshold: float) -> dict[str, Any]:
    text = record["text"]
    baseline_prediction = predictor(text)
    baseline_label = baseline_prediction["label"]
    baseline_confidence = baseline_prediction["confidence"]
    original_clauses_text = split_contrast_clauses(text)
    contrast_detected = len(original_clauses_text) >= 2
    original_clauses = [
        {
            "text": clause,
            "connector": detect_connector(clause),
            "connector_type": connector_type(clause),
        }
        for clause in original_clauses_text
    ]
    raw_clause_predictions: dict[str, dict[str, Any]] = {}

    strategy_results = {}
    for strategy in STRATEGIES:
        strategy_results[strategy] = evaluate_strategy_for_record(
            record,
            baseline_label,
            contrast_detected,
            original_clauses_text,
            raw_clause_predictions,
            strategy,
            predictor,
            confidence_threshold,
        )

    return {
        "id": record["id"],
        "text": text,
        "gold_label": record["overall_label"],
        "category": record["category"],
        "review_status": record["review_status"],
        "source": record["source"],
        "baseline_label": baseline_label,
        "baseline_confidence": baseline_confidence,
        "contrast_detected": contrast_detected,
        "original_clauses": original_clauses,
        "strategy_results": strategy_results,
        "policy_review_status": POLICY_REVIEW_STATUS if requires_label_policy_review(record) else None,
        "neutral_status": NOT_TARGETED_STATUS if record["overall_label"] == "NEUTRAL" else None,
        "aspects": record["aspects"],
        "note": record["note"],
    }


def evaluate_strategy_for_record(
    record: dict[str, Any],
    baseline_label: str,
    contrast_detected: bool,
    original_clauses_text: list[str],
    raw_clause_predictions: dict[str, dict[str, Any]],
    strategy: str,
    predictor,
    confidence_threshold: float,
) -> dict[str, Any]:
    if not contrast_detected or len(original_clauses_text) < 2:
        experimental_label = baseline_label
        return result_payload(
            record,
            baseline_label,
            experimental_label,
            [],
            "NO_CONTRAST",
            strategy,
        )

    clause_results = []
    try:
        for original_clause in original_clauses_text:
            raw_prediction = raw_clause_predictions.get(original_clause)
            if raw_prediction is None:
                raw_prediction = predictor(original_clause)
                raw_clause_predictions[original_clause] = raw_prediction
            normalization = normalize_clause(original_clause, strategy)
            normalized_prediction = (
                raw_prediction
                if normalization.normalized_text == original_clause
                else predictor(normalization.normalized_text)
            )
            clause_results.append(
                {
                    "original_clause": original_clause,
                    "connector": detect_connector(original_clause),
                    "connector_type": connector_type(original_clause),
                    "raw_prediction": prediction_payload(raw_prediction),
                    "normalization": normalization.to_dict(),
                    "normalized_prediction": prediction_payload(normalized_prediction),
                    "prediction_changed": raw_prediction["label"] != normalized_prediction["label"],
                    "prediction_change": prediction_change(raw_prediction, normalized_prediction),
                }
            )

        clause_predictions = [
            {
                "text": clause["normalization"]["normalized_text"],
                "label": clause["normalized_prediction"]["label"],
                "confidence": clause["normalized_prediction"]["confidence"],
            }
            for clause in clause_results
        ]
        experimental_label = combine_clause_predictions(
            baseline_label,
            clause_predictions,
            confidence_threshold,
        )
        fallback_reason = fallback_reason_for(
            baseline_label,
            experimental_label,
            clause_predictions,
        )
        return result_payload(
            record,
            baseline_label,
            experimental_label,
            clause_results,
            fallback_reason,
            strategy,
        )
    except Exception as exc:
        return result_payload(
            record,
            baseline_label,
            baseline_label,
            clause_results,
            f"PREDICTOR_ERROR: {exc}",
            strategy,
        )


def result_payload(
    record: dict[str, Any],
    baseline_label: str,
    experimental_label: str,
    clause_results: list[dict[str, Any]],
    fallback_reason: str | None,
    strategy: str,
) -> dict[str, Any]:
    gold_label = record["overall_label"]
    targeted = gold_label != "NEUTRAL"
    experimental_match = None if not targeted else experimental_label == gold_label
    baseline_match = baseline_label == gold_label
    return {
        "strategy": strategy,
        "clause_results": clause_results,
        "experimental_label": experimental_label,
        "fallback_reason": fallback_reason,
        "improvement": experimental_match is True and baseline_match is False,
        "regression": experimental_match is False and baseline_match is True,
        "false_mixed": experimental_label == "MIXED" and gold_label != "MIXED",
        "experimental_match": experimental_match,
    }


def prediction_payload(prediction: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": prediction["label"],
        "confidence": prediction["confidence"],
        "raw_label": prediction.get("raw_label"),
    }


def prediction_change(raw_prediction: dict[str, Any], normalized_prediction: dict[str, Any]) -> str | None:
    raw_label = raw_prediction["label"]
    normalized_label = normalized_prediction["label"]
    if raw_label == normalized_label:
        return None
    return f"{raw_label}_TO_{normalized_label}"


def fallback_reason_for(
    baseline_label: str,
    experimental_label: str,
    clause_predictions: list[dict[str, Any]],
) -> str | None:
    if len(clause_predictions) < 2:
        return "INVALID_CLAUSE_SPLIT"
    if experimental_label != baseline_label:
        return None
    labels = {prediction["label"] for prediction in clause_predictions}
    if labels == {"POSITIVE", "NEGATIVE"}:
        return "LOW_CONFIDENCE_MIXED_CANDIDATE"
    return None


def summarize_baseline(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "exact_match_count": sum(
            1 for row in predictions if row["baseline_label"] == row["gold_label"]
        ),
        "mixed_forced_distribution": label_distribution(
            row["baseline_label"] for row in predictions if row["gold_label"] == "MIXED"
        ),
        "neutral_forced_distribution": label_distribution(
            row["baseline_label"] for row in predictions if row["gold_label"] == "NEUTRAL"
        ),
    }


def summarize_strategy(predictions: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
    binary_rows = [row for row in predictions if row["gold_label"] in SUPPORTED_BASELINE_LABELS]
    positive_rows = [row for row in predictions if row["gold_label"] == "POSITIVE"]
    negative_rows = [row for row in predictions if row["gold_label"] == "NEGATIVE"]
    mixed_rows = [row for row in predictions if row["gold_label"] == "MIXED"]
    mixed_without_policy_review = [
        row for row in mixed_rows if row["policy_review_status"] != POLICY_REVIEW_STATUS
    ]
    mixed_contrast_rows = [row for row in predictions if row["category"] == "mixed_contrast"]
    predicted_mixed_rows = [
        row for row in predictions if row["strategy_results"][strategy]["experimental_label"] == "MIXED"
    ]
    false_mixed_rows = [
        row for row in predictions if row["strategy_results"][strategy]["false_mixed"]
    ]
    regression_rows = [
        row for row in predictions if row["strategy_results"][strategy]["regression"]
    ]
    improvement_rows = [
        row for row in predictions if row["strategy_results"][strategy]["improvement"]
    ]
    fallback_rows = [
        row for row in predictions if row["strategy_results"][strategy]["fallback_reason"] is not None
    ]
    low_confidence_rows = [
        row for row in predictions
        if row["strategy_results"][strategy]["fallback_reason"] == "LOW_CONFIDENCE_MIXED_CANDIDATE"
    ]
    clause_stats = clause_level_stats(predictions, strategy)
    mixed_precision = safe_divide(
        sum(1 for row in predicted_mixed_rows if row["gold_label"] == "MIXED"),
        len(predicted_mixed_rows),
    )
    mixed_recall_including = recall_for_mixed(mixed_rows, strategy)
    mixed_recall_excluding = recall_for_mixed(mixed_without_policy_review, strategy)

    return {
        "exact_match_count": sum(
            1 for row in predictions
            if row["gold_label"] != "NEUTRAL"
            and row["strategy_results"][strategy]["experimental_match"] is True
        ),
        "positive_negative_accuracy": accuracy(binary_rows, strategy),
        "positive_retention_rate": retention_rate(positive_rows, strategy, "POSITIVE"),
        "negative_retention_rate": retention_rate(negative_rows, strategy, "NEGATIVE"),
        "mixed_precision": mixed_precision,
        "mixed_recall_including_policy_review": mixed_recall_including,
        "mixed_recall_excluding_policy_review": mixed_recall_excluding,
        "mixed_f1_including_policy_review": f1(mixed_precision, mixed_recall_including),
        "mixed_f1_excluding_policy_review": f1(mixed_precision, mixed_recall_excluding),
        "mixed_contrast_recall": recall_for_mixed(mixed_contrast_rows, strategy),
        "false_mixed_count": len(false_mixed_rows),
        "regression_count": len(regression_rows),
        "improvement_count": len(improvement_rows),
        "clause_split_count": sum(1 for row in predictions if row["contrast_detected"]),
        "normalization_applied_count": clause_stats["normalization_applied_count"],
        "normalization_no_op_count": clause_stats["normalization_no_op_count"],
        "fallback_count": len(fallback_rows),
        "low_confidence_mixed_candidate_count": len(low_confidence_rows),
        "prediction_changed_count": clause_stats["prediction_changed_count"],
        "negative_to_positive_count": clause_stats["negative_to_positive_count"],
        "positive_to_negative_count": clause_stats["positive_to_negative_count"],
        "negative_to_positive_clauses": clause_stats["negative_to_positive_clauses"],
        "positive_to_negative_clauses": clause_stats["positive_to_negative_clauses"],
        "unnatural_normalizations": clause_stats["unnatural_normalizations"],
    }


def clause_level_stats(predictions: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
    stats = {
        "normalization_applied_count": 0,
        "normalization_no_op_count": 0,
        "prediction_changed_count": 0,
        "negative_to_positive_count": 0,
        "positive_to_negative_count": 0,
        "negative_to_positive_clauses": [],
        "positive_to_negative_clauses": [],
        "unnatural_normalizations": [],
    }
    seen_clauses: set[tuple[str, str, str]] = set()
    for row in predictions:
        for clause in row["strategy_results"][strategy]["clause_results"]:
            key = (row["id"], strategy, clause["original_clause"])
            if key in seen_clauses:
                continue
            seen_clauses.add(key)
            normalization = clause["normalization"]
            if normalization["normalization_applied"]:
                stats["normalization_applied_count"] += 1
            else:
                stats["normalization_no_op_count"] += 1
            if clause["prediction_changed"]:
                stats["prediction_changed_count"] += 1
                change_case = {
                    "id": row["id"],
                    "original_clause": clause["original_clause"],
                    "normalized_text": normalization["normalized_text"],
                    "raw_label": clause["raw_prediction"]["label"],
                    "normalized_label": clause["normalized_prediction"]["label"],
                    "strategy": strategy,
                }
                if clause["prediction_change"] == "NEGATIVE_TO_POSITIVE":
                    stats["negative_to_positive_count"] += 1
                    stats["negative_to_positive_clauses"].append(change_case)
                if clause["prediction_change"] == "POSITIVE_TO_NEGATIVE":
                    stats["positive_to_negative_count"] += 1
                    stats["positive_to_negative_clauses"].append(change_case)
            if normalization["normalization_applied"] and not normalization["normalized_text"].endswith("."):
                stats["unnatural_normalizations"].append(
                    {
                        "id": row["id"],
                        "original_clause": clause["original_clause"],
                        "normalized_text": normalization["normalized_text"],
                        "reason": "MISSING_TERMINAL_PERIOD",
                    }
                )
    return stats


def compare_strategies(
    strategy_summaries: dict[str, dict[str, Any]],
    predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = []
    representative = representative_case(predictions)
    representative_strategies = representative.get("strategies", {})
    for strategy, summary in strategy_summaries.items():
        representative_result = representative_strategies.get(strategy, {})
        pass_criteria = {
            "positive_negative_accuracy_at_least_0_95": summary["positive_negative_accuracy"] >= 0.95,
            "positive_negative_regression_at_most_1": summary["regression_count"] <= 1,
            "false_mixed_at_most_1": summary["false_mixed_count"] <= 1,
            "mixed_contrast_recall_at_least_0_75": summary["mixed_contrast_recall"] >= 0.75,
            "representative_sentence_is_mixed": representative_result.get("final_label") == "MIXED",
            "tests_passed": "SEE_EXECUTION_LOG",
            "production_code_unchanged": "SEE_GIT_DIFF",
        }
        measured_pass = all(value is True for value in pass_criteria.values() if isinstance(value, bool))
        candidates.append(
            {
                "strategy": strategy,
                "status": "PASS_CANDIDATE" if measured_pass else "EXPERIMENTAL_BEST_BUT_BELOW_THRESHOLD",
                "pass_criteria": pass_criteria,
                "measured_pass": measured_pass,
                "regression_count": summary["regression_count"],
                "false_mixed_count": summary["false_mixed_count"],
                "mixed_contrast_recall": summary["mixed_contrast_recall"],
                "mixed_f1": summary["mixed_f1_including_policy_review"],
            }
        )

    ranked = sorted(
        candidates,
        key=lambda item: (
            item["measured_pass"],
            -item["regression_count"],
            -item["false_mixed_count"],
            item["mixed_contrast_recall"],
            item["mixed_f1"],
        ),
        reverse=True,
    )
    selected = ranked[0] if ranked else None
    if selected and not selected["measured_pass"]:
        selected["status"] = "EXPERIMENTAL_BEST_BUT_BELOW_THRESHOLD"

    return {
        "selected_strategy": selected,
        "ranking": ranked,
    }


def pattern_statistics(predictions: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    result: dict[str, dict[str, dict[str, int]]] = {}
    for strategy in STRATEGIES:
        result[strategy] = {}
        for row in predictions:
            for clause in row["strategy_results"][strategy]["clause_results"]:
                pattern = clause["normalization"]["matched_pattern"] or clause["connector"] or "NO_PATTERN"
                stats = result[strategy].setdefault(
                    pattern,
                    {
                        "cases": 0,
                        "normalization_applied": 0,
                        "mixed_detected": 0,
                        "improvements": 0,
                        "regressions": 0,
                    },
                )
                stats["cases"] += 1
                if clause["normalization"]["normalization_applied"]:
                    stats["normalization_applied"] += 1
                strategy_result = row["strategy_results"][strategy]
                if strategy_result["experimental_label"] == "MIXED":
                    stats["mixed_detected"] += 1
                if strategy_result["improvement"]:
                    stats["improvements"] += 1
                if strategy_result["regression"]:
                    stats["regressions"] += 1
    return result


def representative_case(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    row = next((item for item in predictions if item["text"] == REPRESENTATIVE_TEXT), None)
    if row is None:
        return {}

    return {
        "id": row["id"],
        "text": row["text"],
        "gold_label": row["gold_label"],
        "baseline_label": row["baseline_label"],
        "baseline_confidence": row["baseline_confidence"],
        "strategies": {
            strategy: {
                "clauses": [
                    {
                        "original_clause": clause["original_clause"],
                        "normalized_text": clause["normalization"]["normalized_text"],
                        "label": clause["normalized_prediction"]["label"],
                        "confidence": clause["normalized_prediction"]["confidence"],
                        "normalization_applied": clause["normalization"]["normalization_applied"],
                        "matched_pattern": clause["normalization"]["matched_pattern"],
                    }
                    for clause in row["strategy_results"][strategy]["clause_results"]
                ],
                "final_label": row["strategy_results"][strategy]["experimental_label"],
                "target_mixed_achieved": row["strategy_results"][strategy]["experimental_label"] == "MIXED",
                "fallback_reason": row["strategy_results"][strategy]["fallback_reason"],
            }
            for strategy in STRATEGIES
        },
    }


def summarize_cases(rows) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "text": row["text"],
            "gold_label": row["gold_label"],
            "baseline_label": row["baseline_label"],
            "category": row["category"],
        }
        for row in rows
    ]


def requires_label_policy_review(record: dict[str, Any]) -> bool:
    if record["overall_label"] != "MIXED":
        return False
    sentiments = {aspect.get("sentiment") for aspect in record.get("aspects", [])}
    return "NEUTRAL" in sentiments and "NEGATIVE" in sentiments and "POSITIVE" not in sentiments


def detect_connector(clause: str) -> str | None:
    stripped = clause.strip().rstrip(".!?。！？")
    for connector in ("았지만", "었지만", "였지만", "지만", "았는데", "었는데", "였는데", "인데", "은데", "는데"):
        if stripped.endswith(connector):
            return connector
    if stripped.endswith("데") and len(stripped) >= 2:
        return "ㄴ데"
    for connector in STANDALONE_CONNECTORS:
        if stripped.startswith(connector):
            return connector
    return None


def connector_type(clause: str) -> str | None:
    connector = detect_connector(clause)
    if connector is None:
        return None
    if connector in STANDALONE_CONNECTORS:
        return "STANDALONE"
    return "ATTACHED_ENDING"


def accuracy(rows: list[dict[str, Any]], strategy: str) -> float:
    if not rows:
        return 0.0
    return sum(
        1 for row in rows if row["strategy_results"][strategy]["experimental_match"] is True
    ) / len(rows)


def retention_rate(rows: list[dict[str, Any]], strategy: str, label: str) -> float:
    if not rows:
        return 0.0
    return sum(
        1 for row in rows if row["strategy_results"][strategy]["experimental_label"] == label
    ) / len(rows)


def recall_for_mixed(rows: list[dict[str, Any]], strategy: str) -> float:
    if not rows:
        return 0.0
    return sum(
        1 for row in rows if row["strategy_results"][strategy]["experimental_label"] == "MIXED"
    ) / len(rows)


def f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def label_distribution(labels) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for label in labels:
        distribution[label] = distribution.get(label, 0) + 1
    return dict(sorted(distribution.items()))


def format_console_summary(report: dict[str, Any], output_path: Path | None) -> str:
    summaries = report["strategy_summaries"]
    lines = [
        "SentiTrack clause normalization experiment",
        f"- dataset_total: {report['metadata']['dataset_total']}",
    ]
    for strategy in STRATEGIES:
        summary = summaries[strategy]
        lines.append(
            "- "
            f"{strategy}: pn_accuracy={summary['positive_negative_accuracy']:.4f}, "
            f"mixed_recall={summary['mixed_recall_including_policy_review']:.4f}, "
            f"mixed_precision={summary['mixed_precision']:.4f}, "
            f"false_mixed={summary['false_mixed_count']}, "
            f"regression={summary['regression_count']}, "
            f"improvement={summary['improvement_count']}"
        )
    selected = report["strategy_comparison"]["selected_strategy"]
    lines.append(f"- selected_strategy: {selected['strategy']} ({selected['status']})")
    lines.append(f"- output: {output_path if output_path else 'not written'}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate clause normalization strategies.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--confidence-threshold", type=float, default=DEFAULT_CONFIDENCE_THRESHOLD)
    return parser.parse_args()


def main_cli() -> int:
    args = parse_args()
    try:
        records = load_dataset(args.dataset)
        predictor, model_config = make_pipeline_predictor()
        report = evaluate_normalization_experiment(
            records,
            predictor,
            model_config,
            args.dataset,
            args.confidence_threshold,
        )
    except Exception as exc:
        print(json.dumps({"error": "clause_normalization_failed", "detail": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(format_console_summary(report, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
