from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from evaluate_sentiment_baseline import load_dataset  # noqa: E402
from experiments.aspect_taxonomy import (  # noqa: E402
    ASPECT_ALIASES,
    CANONICAL_ASPECTS,
    EXCLUDED_ASPECTS,
    REVIEW_REQUIRED_ASPECTS,
    conflicting_normalized_sentiments,
    metric_names,
    metric_pairs,
    normalize_aspects,
)


EXPERIMENT_NAME = "LLM_ASPECT_TAXONOMY_NORMALIZATION_OFFLINE"
DEFAULT_REPORT_PATH = ROOT_DIR / "evaluation" / "llm_sentiment_representative_report.json"
DEFAULT_DATASET_PATH = ROOT_DIR / "evaluation" / "sentiment_eval_representative_12.jsonl"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "evaluation" / "aspect_taxonomy_report.json"
DISCLAIMER = (
    "This experiment uses a synthetic dataset pending manual review and must not be treated "
    "as final production performance."
)


def load_llm_report(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        report = json.load(file)
    if not isinstance(report.get("predictions"), list):
        raise ValueError(f"{path}: report must contain a predictions list")
    return report


def evaluate_aspect_taxonomy(
    llm_report: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    report_path: Path,
    dataset_path: Path,
) -> dict[str, Any]:
    predictions = [row for row in llm_report["predictions"] if row.get("error") is None]
    records_by_id = {record["id"]: record for record in records}
    details = [
        build_prediction_detail(row, records_by_id.get(row["id"], {}))
        for row in predictions
    ]

    raw_metrics = calculate_metrics(
        (detail["gold_aspects_raw"] for detail in details),
        (detail["predicted_aspects_raw"] for detail in details),
        mode="raw",
    )
    excluding_overall_metrics = calculate_metrics(
        (detail["gold_aspects_raw"] for detail in details),
        (detail["predicted_aspects_raw"] for detail in details),
        mode="excluding_overall",
    )
    normalized_metrics = calculate_normalized_metrics(details)

    normalization_summary = build_normalization_summary(details, records)
    return {
        "metadata": {
            "experiment_name": EXPERIMENT_NAME,
            "input_report_path": str(report_path),
            "input_dataset_path": str(dataset_path),
            "dataset_total": len(records),
            "evaluated_prediction_count": len(predictions),
            "api_calls_performed": 0,
            "raw_predictions_modified": False,
            "gold_dataset_modified": False,
            "production_code_modified": False,
            "disclaimer": DISCLAIMER,
        },
        "input_report_path": str(report_path),
        "input_dataset_path": str(dataset_path),
        "canonical_taxonomy": {
            "canonical_aspects": list(CANONICAL_ASPECTS),
            "gold_aspect_names": normalization_summary["gold_aspect_names"],
            "canonical_aspects_absent_from_gold": normalization_summary[
                "canonical_aspects_absent_from_gold"
            ],
        },
        "alias_rules": {
            canonical: list(aliases)
            for canonical, aliases in ASPECT_ALIASES.items()
        },
        "excluded_aspect_policy": {
            "excluded_aspects": list(EXCLUDED_ASPECTS),
            "reason": "overall_label is the full-review sentiment; aspects are product attributes.",
            "review_required_aspects": list(REVIEW_REQUIRED_ASPECTS),
        },
        "overall_metrics_preserved": llm_report.get("overall_metrics"),
        "evidence_metrics_preserved": {
            "evidence_substring_validation_rate": llm_report.get("aspect_metrics", {}).get(
                "evidence_substring_validation_rate"
            ),
            "hallucinated_evidence_count": llm_report.get("aspect_metrics", {}).get(
                "hallucinated_evidence_count"
            ),
        },
        "raw_metrics": raw_metrics,
        "metrics_excluding_overall": excluding_overall_metrics,
        "normalized_metrics": normalized_metrics,
        "metric_deltas": metric_deltas(raw_metrics, excluding_overall_metrics, normalized_metrics),
        "normalization_cases": normalization_summary["normalization_cases"],
        "review_required_cases": normalization_summary["review_required_cases"],
        "conflicting_sentiment_cases": normalization_summary["conflicting_sentiment_cases"],
        "remaining_missing_aspects": collect_non_empty(details, "missing_aspects_after_normalization"),
        "remaining_additional_aspects": collect_non_empty(details, "additional_aspects_after_normalization"),
        "newly_matched_by_normalization": collect_non_empty(details, "newly_matched_by_normalization"),
        "sentiment_mismatch_cases": collect_non_empty(details, "sentiment_mismatches_after_normalization"),
        "name_only_mismatch_cases": collect_non_empty(details, "name_only_mismatches_after_normalization"),
        "per_prediction_details": details,
        "disclaimer": DISCLAIMER,
    }


def build_prediction_detail(row: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    gold_aspects = list(record.get("aspects") or row.get("gold_aspects") or [])
    predicted_aspects = list(row.get("predicted_aspects") or [])
    gold_normalized = normalize_aspects(gold_aspects)
    predicted_normalized = normalize_aspects(predicted_aspects)
    raw_gold_names = aspect_names(gold_aspects)
    raw_predicted_names = aspect_names(predicted_aspects)
    raw_gold_pairs = aspect_pairs(gold_aspects)
    raw_predicted_pairs = aspect_pairs(predicted_aspects)
    raw_gold_names_excluding_overall = aspect_names_excluding_overall(gold_aspects)
    raw_predicted_names_excluding_overall = aspect_names_excluding_overall(predicted_aspects)
    normalized_gold_names = metric_names(gold_normalized)
    normalized_predicted_names = metric_names(predicted_normalized)
    normalized_gold_pairs = metric_pairs(gold_normalized)
    normalized_predicted_pairs = metric_pairs(predicted_normalized)
    normalized_pair_matches = normalized_gold_pairs & normalized_predicted_pairs
    normalized_name_matches = normalized_gold_names & normalized_predicted_names

    return {
        "id": row["id"],
        "text": row["text"],
        "gold_label": row.get("gold_label"),
        "predicted_overall_label": row.get("predicted_overall_label"),
        "overall_match": row.get("overall_match"),
        "gold_aspects_raw": gold_aspects,
        "gold_aspects_normalized": gold_normalized,
        "predicted_aspects_raw": predicted_aspects,
        "predicted_aspects_normalized": predicted_normalized,
        "excluded_overall_aspects": [
            aspect
            for aspect in gold_normalized + predicted_normalized
            if aspect["status"] == "EXCLUDED_OVERALL"
        ],
        "alias_rules_applied": [
            {
                "raw_name": aspect["raw_name"],
                "normalized_name": aspect["normalized_name"],
                "matched_alias": aspect["matched_alias"],
                "sentiment": aspect["sentiment"],
            }
            for aspect in gold_normalized + predicted_normalized
            if aspect["normalization_applied"]
        ],
        "review_required_aspects": [
            aspect
            for aspect in gold_normalized + predicted_normalized
            if aspect["status"] == "REVIEW_REQUIRED"
        ],
        "additional_aspects_before_normalization": sorted(raw_predicted_names - raw_gold_names),
        "additional_aspects_excluding_overall": sorted(
            raw_predicted_names_excluding_overall - raw_gold_names_excluding_overall
        ),
        "additional_aspects_after_normalization": sorted(
            normalized_predicted_names - normalized_gold_names
        ),
        "missing_aspects_before_normalization": sorted(raw_gold_names - raw_predicted_names),
        "missing_aspects_excluding_overall": sorted(
            raw_gold_names_excluding_overall - raw_predicted_names_excluding_overall
        ),
        "missing_aspects_after_normalization": sorted(
            normalized_gold_names - normalized_predicted_names
        ),
        "raw_pair_matches": sorted(raw_gold_pairs & raw_predicted_pairs),
        "normalized_pair_matches": sorted(normalized_pair_matches),
        "newly_matched_by_normalization": sorted(
            normalized_name_matches - (raw_gold_names_excluding_overall & raw_predicted_names_excluding_overall)
        ),
        "sentiment_mismatches_after_normalization": sentiment_mismatches(
            normalized_gold_pairs,
            normalized_predicted_pairs,
        ),
        "name_only_mismatches_after_normalization": name_only_mismatches(
            normalized_gold_names,
            normalized_predicted_names,
            normalized_pair_matches,
        ),
        "conflicting_sentiment_cases": conflicting_normalized_sentiments(predicted_normalized),
    }


def calculate_metrics(
    gold_iter: Iterable[list[dict[str, Any]]],
    predicted_iter: Iterable[list[dict[str, Any]]],
    *,
    mode: str,
) -> dict[str, Any]:
    rows = list(zip(gold_iter, predicted_iter))
    if mode == "raw":
        gold_names = [aspect_names(aspects) for aspects, _ in rows]
        predicted_names = [aspect_names(aspects) for _, aspects in rows]
        gold_pairs = [aspect_pairs(aspects) for aspects, _ in rows]
        predicted_pairs = [aspect_pairs(aspects) for _, aspects in rows]
    elif mode == "excluding_overall":
        gold_names = [aspect_names_excluding_overall(aspects) for aspects, _ in rows]
        predicted_names = [aspect_names_excluding_overall(aspects) for _, aspects in rows]
        gold_pairs = [aspect_pairs_excluding_overall(aspects) for aspects, _ in rows]
        predicted_pairs = [aspect_pairs_excluding_overall(aspects) for _, aspects in rows]
    else:
        raise ValueError(f"unsupported metric mode: {mode}")
    return metric_payload(gold_names, predicted_names, gold_pairs, predicted_pairs)


def calculate_normalized_metrics(details: list[dict[str, Any]]) -> dict[str, Any]:
    gold_names = [metric_names(detail["gold_aspects_normalized"]) for detail in details]
    predicted_names = [metric_names(detail["predicted_aspects_normalized"]) for detail in details]
    gold_pairs = [metric_pairs(detail["gold_aspects_normalized"]) for detail in details]
    predicted_pairs = [metric_pairs(detail["predicted_aspects_normalized"]) for detail in details]
    return metric_payload(gold_names, predicted_names, gold_pairs, predicted_pairs)


def metric_payload(
    gold_names: list[set[str]],
    predicted_names: list[set[str]],
    gold_pairs: list[set[tuple[str, str]]],
    predicted_pairs: list[set[tuple[str, str]]],
) -> dict[str, Any]:
    name_match_count = sum(len(gold & predicted) for gold, predicted in zip(gold_names, predicted_names))
    gold_name_count = sum(len(names) for names in gold_names)
    predicted_name_count = sum(len(names) for names in predicted_names)
    pair_match_count = sum(len(gold & predicted) for gold, predicted in zip(gold_pairs, predicted_pairs))
    gold_pair_count = sum(len(pairs) for pairs in gold_pairs)
    predicted_pair_count = sum(len(pairs) for pairs in predicted_pairs)
    name_precision = safe_divide(name_match_count, predicted_name_count)
    name_recall = safe_divide(name_match_count, gold_name_count)
    pair_precision = safe_divide(pair_match_count, predicted_pair_count)
    pair_recall = safe_divide(pair_match_count, gold_pair_count)
    return {
        "total": len(gold_names),
        "exact_aspect_name_match_rate": safe_divide(
            sum(1 for gold, predicted in zip(gold_names, predicted_names) if gold == predicted),
            len(gold_names),
        ),
        "aspect_name_precision": name_precision,
        "aspect_name_recall": name_recall,
        "aspect_name_f1": f1(name_precision, name_recall),
        "pair_precision": pair_precision,
        "pair_recall": pair_recall,
        "pair_f1": f1(pair_precision, pair_recall),
        "counts": {
            "gold_name_count": gold_name_count,
            "predicted_name_count": predicted_name_count,
            "name_match_count": name_match_count,
            "gold_pair_count": gold_pair_count,
            "predicted_pair_count": predicted_pair_count,
            "pair_match_count": pair_match_count,
        },
    }


def build_normalization_summary(
    details: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    all_normalized = [
        aspect
        for detail in details
        for aspect in detail["gold_aspects_normalized"] + detail["predicted_aspects_normalized"]
    ]
    status_counts = Counter(str(aspect["status"]) for aspect in all_normalized)
    gold_aspect_names = sorted(
        {
            aspect["name"].strip().lower()
            for record in records
            for aspect in record["aspects"]
            if aspect["name"].strip().lower() not in EXCLUDED_ASPECTS
        }
    )
    return {
        "gold_aspect_names": gold_aspect_names,
        "canonical_aspects_absent_from_gold": [
            aspect for aspect in CANONICAL_ASPECTS if aspect not in gold_aspect_names
        ],
        "status_counts": dict(sorted(status_counts.items())),
        "normalization_cases": [
            {
                "id": detail["id"],
                "applied": detail["alias_rules_applied"],
            }
            for detail in details
            if detail["alias_rules_applied"]
        ],
        "review_required_cases": [
            {
                "id": detail["id"],
                "review_required_aspects": detail["review_required_aspects"],
            }
            for detail in details
            if detail["review_required_aspects"]
        ],
        "conflicting_sentiment_cases": [
            {
                "id": detail["id"],
                "conflicts": detail["conflicting_sentiment_cases"],
            }
            for detail in details
            if detail["conflicting_sentiment_cases"]
        ],
    }


def metric_deltas(
    raw_metrics: dict[str, Any],
    excluding_overall_metrics: dict[str, Any],
    normalized_metrics: dict[str, Any],
) -> dict[str, float]:
    return {
        "aspect_name_f1_excluding_overall_minus_raw": (
            excluding_overall_metrics["aspect_name_f1"] - raw_metrics["aspect_name_f1"]
        ),
        "aspect_name_f1_normalized_minus_raw": (
            normalized_metrics["aspect_name_f1"] - raw_metrics["aspect_name_f1"]
        ),
        "aspect_name_f1_normalized_minus_excluding_overall": (
            normalized_metrics["aspect_name_f1"] - excluding_overall_metrics["aspect_name_f1"]
        ),
        "pair_f1_excluding_overall_minus_raw": (
            excluding_overall_metrics["pair_f1"] - raw_metrics["pair_f1"]
        ),
        "pair_f1_normalized_minus_raw": normalized_metrics["pair_f1"] - raw_metrics["pair_f1"],
        "pair_f1_normalized_minus_excluding_overall": (
            normalized_metrics["pair_f1"] - excluding_overall_metrics["pair_f1"]
        ),
    }


def sentiment_mismatches(
    gold_pairs: set[tuple[str, str]],
    predicted_pairs: set[tuple[str, str]],
) -> list[dict[str, str]]:
    mismatches = []
    gold_by_name = pairs_by_name(gold_pairs)
    predicted_by_name = pairs_by_name(predicted_pairs)
    for name in sorted(set(gold_by_name) & set(predicted_by_name)):
        if gold_by_name[name] != predicted_by_name[name]:
            mismatches.append(
                {
                    "name": name,
                    "gold_sentiments": sorted(gold_by_name[name]),
                    "predicted_sentiments": sorted(predicted_by_name[name]),
                }
            )
    return mismatches


def name_only_mismatches(
    gold_names: set[str],
    predicted_names: set[str],
    pair_matches: set[tuple[str, str]],
) -> list[str]:
    pair_match_names = {name for name, _sentiment in pair_matches}
    return sorted((gold_names & predicted_names) - pair_match_names)


def pairs_by_name(pairs: set[tuple[str, str]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for name, sentiment in pairs:
        result.setdefault(name, set()).add(sentiment)
    return result


def collect_non_empty(details: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    return [
        {
            "id": detail["id"],
            field: detail[field],
        }
        for detail in details
        if detail[field]
    ]


def aspect_names(aspects: list[dict[str, Any]]) -> set[str]:
    return {str(aspect["name"]).strip().lower() for aspect in aspects}


def aspect_pairs(aspects: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        (str(aspect["name"]).strip().lower(), str(aspect["sentiment"]))
        for aspect in aspects
    }


def aspect_names_excluding_overall(aspects: list[dict[str, Any]]) -> set[str]:
    return {name for name in aspect_names(aspects) if name not in EXCLUDED_ASPECTS}


def aspect_pairs_excluding_overall(aspects: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(name, sentiment) for name, sentiment in aspect_pairs(aspects) if name not in EXCLUDED_ASPECTS}


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def format_console_summary(report: dict[str, Any], output_path: Path | None) -> str:
    raw = report["raw_metrics"]
    excluding = report["metrics_excluding_overall"]
    normalized = report["normalized_metrics"]
    deltas = report["metric_deltas"]
    lines = [
        "SentiTrack aspect taxonomy normalization report",
        f"- evaluated_prediction_count: {report['metadata']['evaluated_prediction_count']}",
        f"- api_calls_performed: {report['metadata']['api_calls_performed']}",
        f"- raw_aspect_name_f1: {raw['aspect_name_f1']:.4f}",
        f"- excluding_overall_aspect_name_f1: {excluding['aspect_name_f1']:.4f}",
        f"- normalized_aspect_name_f1: {normalized['aspect_name_f1']:.4f}",
        f"- raw_pair_f1: {raw['pair_f1']:.4f}",
        f"- normalized_pair_f1: {normalized['pair_f1']:.4f}",
        f"- normalized_name_f1_delta_vs_raw: {deltas['aspect_name_f1_normalized_minus_raw']:.4f}",
        f"- review_required_case_count: {len(report['review_required_cases'])}",
        f"- conflict_case_count: {len(report['conflicting_sentiment_cases'])}",
        f"- output: {output_path if output_path else 'not written'}",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recalculate LLM aspect metrics with taxonomy normalization."
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main_cli() -> int:
    args = parse_args()
    try:
        records = load_dataset(args.dataset)
        llm_report = load_llm_report(args.report)
        report = evaluate_aspect_taxonomy(
            llm_report,
            records,
            report_path=args.report,
            dataset_path=args.dataset,
        )
    except Exception as exc:
        print(
            json.dumps(
                {"error": "aspect_taxonomy_evaluation_failed", "detail": str(exc)},
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
