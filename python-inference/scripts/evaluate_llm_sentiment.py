from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from evaluate_sentiment_baseline import DEFAULT_DATASET_PATH, LABELS, load_dataset  # noqa: E402
from experiments.aspect_taxonomy import (  # noqa: E402
    CANONICAL_ASPECTS,
    EXCLUDED_ASPECTS,
    conflicting_normalized_sentiments,
    is_canonical_aspect_name,
    validate_taxonomy_output_name,
)
from experiments.llm_sentiment_client import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    JsonlLLMCache,
    LLMCallResult,
    LLMSentimentError,
    OpenAICompatibleAdapter,
    analyze_with_cache,
    build_cache_key,
    cache_key_parts,
    load_config_from_env,
    missing_configuration,
    safe_error_payload,
)
from experiments.llm_sentiment_prompt import (  # noqa: E402
    PROMPT_VERSION,
    build_messages,
    get_prompt_config,
    supported_prompt_versions,
)
from experiments.llm_sentiment_schema import (  # noqa: E402
    SCHEMA_VERSION,
    LLMSentimentResult,
    extract_json_payload,
    get_schema_config,
    schema_version_for_prompt_version,
    supported_schema_versions,
    validate_llm_result,
)


V1_EXPERIMENT_NAME = "LLM_STRUCTURED_SENTIMENT_ASPECT_V1_OFFLINE"
V2_EXPERIMENT_NAME = "LLM_STRUCTURED_SENTIMENT_ASPECT_TAXONOMY_V2_OFFLINE"
EXPERIMENT_NAME = V2_EXPERIMENT_NAME
DISCLAIMER = (
    "This experiment uses a synthetic dataset pending manual review and must not be treated "
    "as final production performance."
)
DEFAULT_OUTPUT_PATH = ROOT_DIR / "evaluation" / "llm_sentiment_taxonomy_v2_report.json"
REPRESENTATIVE_TEXT = "향은 너무 좋지만 지속력이 별로예요."
DEFAULT_SAFE_LIMIT = 5


def evaluate_llm_records(
    records: list[dict[str, Any]],
    adapter: OpenAICompatibleAdapter,
    dataset_path: Path,
    *,
    cache: JsonlLLMCache | None = None,
    use_cache: bool = False,
    refresh_cache: bool = False,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    predictions = [
        evaluate_record(
            record,
            adapter,
            cache=cache,
            use_cache=use_cache,
            refresh_cache=refresh_cache,
            prompt_version=prompt_version,
            schema_version=schema_version,
        )
        for record in records
    ]
    return build_report(
        records,
        predictions,
        dataset_path,
        provider_type=adapter.provider_type,
        provider_host=adapter.config.provider_host,
        model=adapter.config.model,
        cache_usage=cache_usage_payload(use_cache, refresh_cache, cache),
        run_mode="EVALUATION",
        prompt_version=prompt_version,
        schema_version=schema_version,
    )


def evaluate_llm_records_resumable(
    records: list[dict[str, Any]],
    selected_records: list[dict[str, Any]],
    adapter: OpenAICompatibleAdapter,
    dataset_path: Path,
    *,
    output_path: Path | None,
    offset: int,
    requested_limit: int | None,
    resume: bool = False,
    save_partial: bool = True,
    stop_on_rate_limit: bool = True,
    progress: bool = True,
    cache: JsonlLLMCache | None = None,
    use_cache: bool = False,
    refresh_cache: bool = False,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    existing_predictions = (
        load_existing_predictions_by_id(output_path) if resume and output_path else {}
    )
    retry_candidates = [
        record
        for record in selected_records
        if not (resume and is_successful_prediction(existing_predictions.get(record["id"])))
    ]
    predictions_by_id = dict(existing_predictions)
    dataset_index_by_id = {record["id"]: index for index, record in enumerate(records)}
    stats: dict[str, Any] = {
        "resume_enabled": resume,
        "offset": offset,
        "requested_limit": requested_limit,
        "dataset_total": len(records),
        "selected_count": len(selected_records),
        "expected_api_call_count": estimated_call_count(
            retry_candidates,
            adapter.config.model,
            use_cache,
            refresh_cache,
            prompt_version,
            schema_version,
            cache=cache,
        ),
        "reused_success_count": 0,
        "retry_candidate_count": len(retry_candidates),
        "retried_failure_count": 0,
        "skipped_by_resume_count": 0,
        "api_calls_attempted": 0,
        "actual_api_call_count": 0,
        "stopped_early": False,
        "stop_reason": None,
        "stopped_at_id": None,
        "partial_saved": False,
        "output_path": str(output_path) if output_path else None,
        "existing_output_found": bool(existing_predictions),
        "refresh_cache_overrides_cache_only": bool(refresh_cache),
    }

    for record in selected_records:
        record_id = record["id"]
        existing = existing_predictions.get(record_id)
        if resume and is_successful_prediction(existing):
            stats["reused_success_count"] += 1
            stats["skipped_by_resume_count"] += 1
            predictions_by_id[record_id] = existing
            if progress:
                print(progress_line(records, dataset_index_by_id, record, "reused existing success"))
            if save_partial:
                save_partial_report(
                    records,
                    predictions_by_id,
                    dataset_path,
                    adapter,
                    cache,
                    use_cache,
                    refresh_cache,
                    prompt_version,
                    schema_version,
                    stats,
                    output_path,
                )
            continue

        if resume and existing is not None:
            stats["retried_failure_count"] += 1

        prediction = evaluate_record(
            record,
            adapter,
            cache=cache,
            use_cache=use_cache,
            refresh_cache=refresh_cache,
            prompt_version=prompt_version,
            schema_version=schema_version,
        )
        predictions_by_id[record_id] = prediction
        if not prediction.get("cache_hit", False):
            stats["api_calls_attempted"] += 1
            stats["actual_api_call_count"] = stats["api_calls_attempted"]

        if progress:
            print(progress_line(records, dataset_index_by_id, record, progress_status(prediction)))

        error_type = prediction_error_type(prediction)
        if error_type == "RATE_LIMIT" and stop_on_rate_limit:
            stats["stopped_early"] = True
            stats["stop_reason"] = "RATE_LIMIT"
            stats["stopped_at_id"] = record_id
            if progress:
                print(
                    progress_line(
                        records,
                        dataset_index_by_id,
                        record,
                        "stopping because RATE_LIMIT was detected",
                    )
                )
            if save_partial:
                save_partial_report(
                    records,
                    predictions_by_id,
                    dataset_path,
                    adapter,
                    cache,
                    use_cache,
                    refresh_cache,
                    prompt_version,
                    schema_version,
                    stats,
                    output_path,
                )
            break

        if save_partial:
            save_partial_report(
                records,
                predictions_by_id,
                dataset_path,
                adapter,
                cache,
                use_cache,
                refresh_cache,
                prompt_version,
                schema_version,
                stats,
                output_path,
            )

    final_predictions = predictions_in_dataset_order(records, predictions_by_id)
    report = build_report(
        records,
        final_predictions,
        dataset_path,
        provider_type=adapter.provider_type,
        provider_host=adapter.config.provider_host,
        model=adapter.config.model,
        cache_usage=cache_usage_payload(use_cache, refresh_cache, cache),
        run_mode="EVALUATION",
        prompt_version=prompt_version,
        schema_version=schema_version,
        run_metadata=stats,
    )
    if output_path and save_partial:
        report["metadata"]["partial_saved"] = True
        write_report(output_path, report)
    return report


def evaluate_record(
    record: dict[str, Any],
    adapter: OpenAICompatibleAdapter,
    *,
    cache: JsonlLLMCache | None = None,
    use_cache: bool = False,
    refresh_cache: bool = False,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    try:
        call = analyze_with_cache(
            record["text"],
            adapter,
            cache=cache,
            use_cache=use_cache,
            refresh_cache=refresh_cache,
            prompt_version=prompt_version,
            schema_version=schema_version,
        )
        if call.result is None:
            raise LLMSentimentError("PROVIDER_ERROR", "missing validated LLM result")
        return prediction_payload(record, call)
    except LLMSentimentError as exc:
        return failure_payload(
            record,
            safe_error_payload(exc),
            adapter.config.model,
            raw_text=exc.raw_text,
            provider_host=adapter.config.provider_host,
            prompt_version=prompt_version,
            schema_version=schema_version,
        )
    except Exception as exc:
        return failure_payload(
            record,
            {"type": "UNEXPECTED_ERROR", "message": str(exc)},
            adapter.config.model,
            prompt_version=prompt_version,
            schema_version=schema_version,
        )


def prediction_payload(record: dict[str, Any], call: LLMCallResult) -> dict[str, Any]:
    assert call.result is not None
    result = call.result
    predicted_aspects = [aspect.model_dump() for aspect in result.aspects]
    gold_aspects = record["aspects"]
    diagnostics = taxonomy_prediction_diagnostics(record["text"], gold_aspects, predicted_aspects)
    aspect_metrics = aspect_match_payload(
        diagnostics["gold_metric_aspects"],
        diagnostics["raw_metric_aspects"],
    )
    evidence_valid = all(aspect["evidence"] in record["text"] for aspect in predicted_aspects)
    overall_match = result.overall_label == record["overall_label"]
    return {
        "id": record["id"],
        "text": record["text"],
        "gold_label": record["overall_label"],
        "gold_aspects": gold_aspects,
        "predicted_overall_label": result.overall_label,
        "predicted_aspects": predicted_aspects,
        "raw_llm_response": call.raw_text,
        "parsed_structured_result": result.model_dump(),
        "raw_predicted_aspects": predicted_aspects,
        "raw_aspect_names": diagnostics["raw_aspect_names"],
        "taxonomy_validation_result": diagnostics["taxonomy_validation_result"],
        "taxonomy_validated_aspects": diagnostics["taxonomy_validated_aspects"],
        "normalized_aspects": diagnostics["normalized_aspects"],
        "normalized_aspect_names": diagnostics["normalized_aspect_names"],
        "schema_valid": True,
        "schema_validation_error": None,
        "evidence_validation_error": None,
        "fallback_normalization_applied": diagnostics["fallback_normalization_applied"],
        "review_required": diagnostics["review_required"],
        "provider_structured_output_used": getattr(call, "provider_structured_output_used", False),
        "provider_fallback_used": getattr(call, "provider_fallback_used", False),
        "provider_model": call.model,
        "provider_host": getattr(call, "provider_host", None),
        "actual_model_if_available": getattr(call, "actual_model_if_available", None),
        "raw_aspect_name_match": diagnostics["raw_aspect_name_matches"],
        "normalized_aspect_name_match": diagnostics["normalized_aspect_name_matches"],
        "raw_pair_match": diagnostics["raw_pair_matches"],
        "normalized_pair_match": diagnostics["normalized_pair_matches"],
        "hallucinated_evidence": diagnostics["hallucinated_evidence"],
        "overall_match": overall_match,
        "aspect_name_matches": aspect_metrics["name_matches"],
        "aspect_sentiment_matches": aspect_metrics["pair_matches"],
        "evidence_valid": evidence_valid,
        "confidence": result.confidence,
        "short_reason": result.short_reason,
        "latency_ms": call.latency_ms,
        "token_usage": call.token_usage,
        "cache_hit": call.cache_hit,
        "prompt_version": call.prompt_version,
        "schema_version": call.schema_version,
        "model": call.model,
        "error": None,
        "category": record["category"],
        "review_status": record["review_status"],
        "source": record["source"],
    }


def failure_payload(
    record: dict[str, Any],
    error: dict[str, str],
    model: str,
    *,
    raw_text: str | None = None,
    provider_host: str | None = None,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    raw_aspects = raw_aspects_from_response(raw_text)
    diagnostics = taxonomy_prediction_diagnostics(record["text"], record["aspects"], raw_aspects)
    schema_error = error if error.get("type") == "SCHEMA_VALIDATION_ERROR" else None
    evidence_error = error if error.get("type") == "EVIDENCE_VALIDATION_ERROR" else None
    return {
        "id": record["id"],
        "text": record["text"],
        "gold_label": record["overall_label"],
        "gold_aspects": record["aspects"],
        "predicted_overall_label": None,
        "predicted_aspects": [],
        "raw_llm_response": raw_text,
        "parsed_structured_result": parsed_payload_or_none(raw_text),
        "raw_predicted_aspects": raw_aspects,
        "raw_aspect_names": diagnostics["raw_aspect_names"],
        "taxonomy_validation_result": diagnostics["taxonomy_validation_result"],
        "taxonomy_validated_aspects": diagnostics["taxonomy_validated_aspects"],
        "normalized_aspects": diagnostics["normalized_aspects"],
        "normalized_aspect_names": diagnostics["normalized_aspect_names"],
        "schema_valid": False,
        "schema_validation_error": schema_error,
        "evidence_validation_error": evidence_error,
        "fallback_normalization_applied": diagnostics["fallback_normalization_applied"],
        "review_required": diagnostics["review_required"],
        "provider_structured_output_used": False,
        "provider_fallback_used": False,
        "provider_model": model,
        "provider_host": provider_host,
        "actual_model_if_available": None,
        "raw_aspect_name_match": diagnostics["raw_aspect_name_matches"],
        "normalized_aspect_name_match": diagnostics["normalized_aspect_name_matches"],
        "raw_pair_match": diagnostics["raw_pair_matches"],
        "normalized_pair_match": diagnostics["normalized_pair_matches"],
        "hallucinated_evidence": diagnostics["hallucinated_evidence"],
        "overall_match": None,
        "aspect_name_matches": [],
        "aspect_sentiment_matches": [],
        "evidence_valid": False,
        "confidence": None,
        "short_reason": None,
        "latency_ms": 0.0,
        "token_usage": None,
        "cache_hit": False,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "model": model,
        "error": error,
        "category": record["category"],
        "review_status": record["review_status"],
        "source": record["source"],
    }


def build_report(
    records: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    dataset_path: Path,
    *,
    provider_type: str,
    provider_host: str | None,
    model: str,
    cache_usage: dict[str, Any],
    run_mode: str,
    dry_run_info: dict[str, Any] | None = None,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
    run_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema_config = get_schema_config(prompt_version, schema_version)
    overall_metrics = calculate_overall_metrics(predictions)
    default_run_metadata = default_report_run_metadata(
        records,
        predictions,
        output_path=None,
    )
    merged_run_metadata = {**default_run_metadata, **(run_metadata or {})}
    merged_run_metadata["actual_api_call_count"] = int(
        merged_run_metadata.get(
            "actual_api_call_count",
            merged_run_metadata.get("api_calls_attempted", 0),
        )
        or 0
    )
    merged_run_metadata["api_calls_attempted"] = merged_run_metadata["actual_api_call_count"]
    merged_run_metadata["cache_hit_count"] = overall_metrics["cache_hit_count"]
    merged_run_metadata["failed_predictions"] = overall_metrics["failed_predictions"]
    metadata = {
        "experiment_name": experiment_name_for_prompt_version(prompt_version),
        "run_mode": run_mode,
        "provider_type": provider_type,
        "provider_host": provider_host,
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "strict_taxonomy": schema_config.strict_taxonomy,
        "canonical_taxonomy": list(CANONICAL_ASPECTS),
        "dataset_path": str(dataset_path),
        "dataset_total": len(records),
        "evaluated_count": len(predictions),
        "cache_usage": cache_usage,
        "disclaimer": DISCLAIMER,
        "confidence_note": (
            "LLM confidence is provider output or self-assessment when present; "
            "it must not be interpreted as the same scale as KoELECTRA score."
        ),
    }
    metadata.update(merged_run_metadata)
    return {
        "metadata": metadata,
        "dry_run": dry_run_info,
        "overall_metrics": overall_metrics,
        "aspect_metrics": calculate_aspect_metrics(predictions),
        "strategy_comparison": strategy_comparison(predictions),
        "baseline_comparison": baseline_comparison(predictions),
        "representative_case": representative_case(predictions),
        "failures": [row for row in predictions if row["error"] is not None],
        "hallucinated_evidence": hallucinated_evidence(predictions),
        "missing_aspects": collect_missing_aspects(predictions),
        "additional_aspects": collect_additional_aspects(predictions),
        "latency_statistics": latency_statistics(predictions),
        "token_statistics": token_statistics(predictions),
        "predictions": predictions,
    }


def calculate_overall_metrics(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in predictions if row["error"] is None]
    failed = [row for row in predictions if row["error"] is not None]
    matrix = confusion_matrix(successful)
    per_label = {}
    for label in LABELS:
        true_positive = matrix[label][label]
        predicted_as_label = sum(matrix[gold][label] for gold in LABELS)
        actual_label = sum(matrix[label][predicted] for predicted in LABELS)
        precision = safe_divide(true_positive, predicted_as_label)
        recall = safe_divide(true_positive, actual_label)
        per_label[label] = {
            "support": actual_label,
            "precision": precision,
            "recall": recall,
            "f1": f1(precision, recall),
        }

    correct = sum(1 for row in successful if row["overall_match"] is True)
    high_confidence_mismatch = [
        summarize_case(row)
        for row in successful
        if row["overall_match"] is False
        and row.get("confidence") is not None
        and float(row["confidence"]) >= 0.8
    ]
    return {
        "total": len(predictions),
        "successful_predictions": len(successful),
        "failed_predictions": len(failed),
        "exact_match_accuracy": safe_divide(correct, len(successful)),
        "per_label": per_label,
        "macro_precision": average(metric["precision"] for metric in per_label.values()),
        "macro_recall": average(metric["recall"] for metric in per_label.values()),
        "macro_f1": average(metric["f1"] for metric in per_label.values()),
        "confusion_matrix": matrix,
        "high_confidence_mismatch_count": len(high_confidence_mismatch),
        "high_confidence_mismatch": high_confidence_mismatch,
        "average_confidence_by_label": average_confidence_by_label(successful),
        "cache_hit_count": sum(1 for row in successful if row["cache_hit"]),
    }


def calculate_aspect_metrics(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in predictions if row["error"] is None]
    metric_rows = successful if successful else predictions
    raw_metric = metric_payload_from_rows(metric_rows, "gold_aspects", "raw_predicted_aspects")
    normalized_metric = metric_payload_from_rows(metric_rows, "gold_aspects", "normalized_aspects")
    evidence_checked = sum(len(row.get("raw_predicted_aspects", [])) for row in metric_rows)
    evidence_valid_count = sum(
        1
        for row in metric_rows
        for aspect in row.get("raw_predicted_aspects", [])
        if isinstance(aspect.get("evidence"), str) and aspect.get("evidence") in row["text"]
    )
    total_predicted_aspects = sum(len(row.get("raw_predicted_aspects", [])) for row in metric_rows)
    direct_canonical_count = sum(
        1
        for row in metric_rows
        for aspect in row.get("raw_predicted_aspects", [])
        if is_canonical_aspect_name(aspect.get("name"))
    )
    taxonomy_violations = [
        aspect
        for row in metric_rows
        for aspect in row.get("taxonomy_validated_aspects", [])
        if aspect.get("status") not in {"CANONICAL"}
    ]
    normalized_conflicts = [
        conflict
        for row in metric_rows
        for conflict in conflicting_normalized_sentiments(row.get("normalized_aspects", []))
    ]
    duplicate_count = duplicate_canonical_aspect_count(metric_rows)
    return {
        "description": (
            "Diagnostic aspect metrics over synthetic PENDING_MANUAL_REVIEW gold aspects. "
            "The 'overall' aspect is excluded because overall sentiment is stored only in overall_label."
        ),
        "raw_aspect_name_precision": raw_metric["aspect_name_precision"],
        "raw_aspect_name_recall": raw_metric["aspect_name_recall"],
        "raw_aspect_name_f1": raw_metric["aspect_name_f1"],
        "raw_pair_precision": raw_metric["pair_precision"],
        "raw_pair_recall": raw_metric["pair_recall"],
        "raw_pair_f1": raw_metric["pair_f1"],
        "normalized_aspect_name_precision": normalized_metric["aspect_name_precision"],
        "normalized_aspect_name_recall": normalized_metric["aspect_name_recall"],
        "normalized_aspect_name_f1": normalized_metric["aspect_name_f1"],
        "normalized_pair_precision": normalized_metric["pair_precision"],
        "normalized_pair_recall": normalized_metric["pair_recall"],
        "normalized_pair_f1": normalized_metric["pair_f1"],
        "aspect_name_precision": raw_metric["aspect_name_precision"],
        "aspect_name_recall": raw_metric["aspect_name_recall"],
        "aspect_name_f1": raw_metric["aspect_name_f1"],
        "pair_precision": raw_metric["pair_precision"],
        "pair_recall": raw_metric["pair_recall"],
        "pair_f1": raw_metric["pair_f1"],
        "canonical_output_rate": safe_divide(direct_canonical_count, total_predicted_aspects),
        "taxonomy_violation_count": len(taxonomy_violations),
        "fallback_normalization_count": sum(
            1
            for row in metric_rows
            for aspect in row.get("taxonomy_validated_aspects", [])
            if aspect.get("status") == "FALLBACK_NORMALIZED"
        ),
        "review_required_count": sum(
            1
            for row in metric_rows
            for aspect in row.get("taxonomy_validated_aspects", [])
            if aspect.get("status") in {"REVIEW_REQUIRED", "EXCLUDED_OVERALL"}
        ),
        "schema_validation_failure_count": sum(1 for row in predictions if not row.get("schema_valid", False)),
        "evidence_substring_validation_rate": safe_divide(evidence_valid_count, evidence_checked),
        "hallucinated_evidence_count": sum(
            len(row.get("hallucinated_evidence", [])) for row in metric_rows
        ),
        "duplicate_canonical_aspect_count": duplicate_count,
        "conflicting_sentiment_count": len(normalized_conflicts),
        "raw_counts": raw_metric["counts"],
        "normalized_counts": normalized_metric["counts"],
        "overall_aspect_gold_count": sum(
            1 for row in metric_rows for aspect in row["gold_aspects"] if aspect["name"] == "overall"
        ),
        "overall_aspect_predicted_count": sum(
            1
            for row in metric_rows
            for aspect in row.get("raw_predicted_aspects", [])
            if aspect.get("name") == "overall"
        ),
        "additional_aspects": collect_additional_aspects(metric_rows),
        "missing_aspects": collect_missing_aspects(metric_rows),
    }


def aspect_match_payload(
    gold_aspects: list[dict[str, Any]],
    predicted_aspects: list[dict[str, Any]],
) -> dict[str, list[Any]]:
    gold_names = aspect_names(gold_aspects)
    predicted_names = aspect_names(predicted_aspects)
    gold_pairs = aspect_pairs(gold_aspects)
    predicted_pairs = aspect_pairs(predicted_aspects)
    return {
        "name_matches": sorted(gold_names & predicted_names),
        "pair_matches": sorted(gold_pairs & predicted_pairs),
    }


def taxonomy_prediction_diagnostics(
    review_text: str,
    gold_aspects: list[dict[str, Any]],
    predicted_aspects: list[dict[str, Any]],
) -> dict[str, Any]:
    gold_metric = metric_ready_aspects(gold_aspects)
    raw_metric = [
        aspect
        for aspect in predicted_aspects
        if is_canonical_aspect_name(aspect.get("name"))
    ]
    taxonomy_validated = []
    normalized_aspects = []
    for aspect in predicted_aspects:
        result = validate_taxonomy_output_name(aspect.get("name"))
        item = {
            **result.to_dict(),
            "sentiment": aspect.get("sentiment"),
            "evidence": aspect.get("evidence"),
        }
        taxonomy_validated.append(item)
        if result.normalized_name is not None and result.status != "EXCLUDED_OVERALL":
            normalized_aspects.append(
                {
                    "name": result.normalized_name,
                    "sentiment": aspect.get("sentiment"),
                    "evidence": aspect.get("evidence"),
                    "raw_name": result.raw_name,
                    "taxonomy_status": result.status,
                }
            )

    raw_names = aspect_names(raw_metric)
    gold_names = aspect_names(gold_metric)
    normalized_names = aspect_names(normalized_aspects)
    raw_pairs = aspect_pairs(raw_metric)
    gold_pairs = aspect_pairs(gold_metric)
    normalized_pairs = aspect_pairs(normalized_aspects)
    hallucinated = [
        {"name": aspect.get("name"), "evidence": aspect.get("evidence")}
        for aspect in predicted_aspects
        if isinstance(aspect.get("evidence"), str) and aspect.get("evidence") not in review_text
    ]
    return {
        "gold_metric_aspects": gold_metric,
        "raw_metric_aspects": raw_metric,
        "raw_aspect_names": [aspect.get("name") for aspect in predicted_aspects],
        "taxonomy_validation_result": taxonomy_validated,
        "taxonomy_validated_aspects": taxonomy_validated,
        "normalized_aspects": normalized_aspects,
        "normalized_aspect_names": sorted(normalized_names),
        "fallback_normalization_applied": any(
            aspect["status"] == "FALLBACK_NORMALIZED" for aspect in taxonomy_validated
        ),
        "review_required": any(
            aspect["status"] in {"REVIEW_REQUIRED", "EXCLUDED_OVERALL"}
            for aspect in taxonomy_validated
        ),
        "raw_aspect_name_matches": sorted(gold_names & raw_names),
        "normalized_aspect_name_matches": sorted(gold_names & normalized_names),
        "raw_pair_matches": sorted(gold_pairs & raw_pairs),
        "normalized_pair_matches": sorted(gold_pairs & normalized_pairs),
        "hallucinated_evidence": hallucinated,
    }


def metric_ready_aspects(aspects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        aspect
        for aspect in aspects
        if str(aspect.get("name", "")).strip().lower() not in EXCLUDED_ASPECTS
    ]


def raw_aspects_from_response(raw_text: str | None) -> list[dict[str, Any]]:
    payload = parsed_payload_or_none(raw_text)
    if not isinstance(payload, dict):
        return []
    aspects = payload.get("aspects")
    if not isinstance(aspects, list):
        return []
    return [aspect for aspect in aspects if isinstance(aspect, dict)]


def parsed_payload_or_none(raw_text: str | None) -> dict[str, Any] | None:
    if not raw_text:
        return None
    try:
        return extract_json_payload(raw_text)
    except Exception:
        return None


def aspect_names(aspects: list[dict[str, Any]]) -> set[str]:
    return {aspect["name"] for aspect in aspects}


def aspect_pairs(aspects: list[dict[str, Any]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for aspect in aspects:
        name = aspect.get("name")
        sentiment = aspect.get("sentiment")
        if name is not None and sentiment is not None:
            pairs.add((str(name), str(sentiment)))
    return pairs


def metric_payload_from_rows(
    rows: list[dict[str, Any]],
    gold_field: str,
    predicted_field: str,
) -> dict[str, Any]:
    gold_names = [aspect_names(metric_ready_aspects(row.get(gold_field, []))) for row in rows]
    predicted_names = [
        aspect_names(metric_ready_aspects(row.get(predicted_field, []))) for row in rows
    ]
    gold_pairs = [aspect_pairs(metric_ready_aspects(row.get(gold_field, []))) for row in rows]
    predicted_pairs = [
        aspect_pairs(metric_ready_aspects(row.get(predicted_field, []))) for row in rows
    ]
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


def duplicate_canonical_aspect_count(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        seen: set[tuple[str, str, str]] = set()
        for aspect in row.get("normalized_aspects", []):
            key = (
                str(aspect.get("name")),
                str(aspect.get("sentiment")),
                str(aspect.get("evidence")),
            )
            if key in seen:
                count += 1
            seen.add(key)
    return count


def strategy_comparison(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aspect_metrics = calculate_aspect_metrics(predictions)
    return [
        {
            "strategy": "V1 Raw",
            "raw_aspect_name_f1": 0.65,
            "raw_pair_f1": 0.65,
            "source": "existing representative 12 report baseline",
        },
        {
            "strategy": "V1 + Taxonomy Post-processing",
            "normalized_aspect_name_f1": 0.9032,
            "normalized_pair_f1": 0.9032,
            "source": "existing aspect taxonomy report baseline",
        },
        {
            "strategy": "V2 Taxonomy-constrained Output",
            "raw_canonical_aspect_precision": aspect_metrics["raw_aspect_name_precision"],
            "raw_canonical_aspect_recall": aspect_metrics["raw_aspect_name_recall"],
            "raw_canonical_aspect_f1": aspect_metrics["raw_aspect_name_f1"],
            "raw_canonical_pair_f1": aspect_metrics["raw_pair_f1"],
            "fallback_normalized_f1": aspect_metrics["normalized_aspect_name_f1"],
            "schema_failure_count": aspect_metrics["schema_validation_failure_count"],
            "taxonomy_violation_count": aspect_metrics["taxonomy_violation_count"],
            "review_required_count": aspect_metrics["review_required_count"],
        },
    ]


def confusion_matrix(predictions: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    matrix = {gold: {predicted: 0 for predicted in LABELS} for gold in LABELS}
    for row in predictions:
        gold = row["gold_label"]
        predicted = row["predicted_overall_label"]
        if gold in LABELS and predicted in LABELS:
            matrix[gold][predicted] += 1
    return matrix


def baseline_comparison(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    llm = calculate_overall_metrics(predictions)
    successful = [row for row in predictions if row["error"] is None]
    binary_rows = [row for row in successful if row["gold_label"] in {"POSITIVE", "NEGATIVE"}]
    false_mixed = [
        row for row in successful if row["predicted_overall_label"] == "MIXED" and row["gold_label"] != "MIXED"
    ]
    regression_rows = [
        row
        for row in binary_rows
        if row["predicted_overall_label"] != row["gold_label"]
    ]
    return {
        "koelectra_baseline": {
            "positive_negative_accuracy": 1.0,
            "four_label_exact_match": 0.5,
            "mixed_precision": 0.0,
            "mixed_recall": 0.0,
            "mixed_f1": 0.0,
            "neutral_precision": 0.0,
            "neutral_recall": 0.0,
            "neutral_f1": 0.0,
            "regression_count": 0,
            "false_mixed": 0,
            "average_latency_ms": "not measured in this LLM offline script",
            "external_api_dependency": False,
            "estimated_cost_or_token_usage": "none",
            "explainability": "single binary label and score only",
            "aspect_support": False,
        },
        "clause_normalization_best_experiment": {
            "positive_negative_accuracy": 1.0,
            "four_label_exact_match": 23 / 40,
            "mixed_precision": 1.0,
            "mixed_recall": 0.3,
            "mixed_f1": 0.4615384615384615,
            "neutral_precision": 0.0,
            "neutral_recall": 0.0,
            "neutral_f1": 0.0,
            "regression_count": 0,
            "false_mixed": 0,
            "average_latency_ms": "local KoELECTRA calls only",
            "external_api_dependency": False,
            "estimated_cost_or_token_usage": "none",
            "explainability": "contrast split and clause predictions",
            "aspect_support": False,
        },
        "llm_structured_experiment": {
            "positive_negative_accuracy": safe_divide(
                sum(1 for row in binary_rows if row["overall_match"] is True),
                len(binary_rows),
            ),
            "four_label_exact_match": llm["exact_match_accuracy"],
            "mixed_precision": llm["per_label"]["MIXED"]["precision"],
            "mixed_recall": llm["per_label"]["MIXED"]["recall"],
            "mixed_f1": llm["per_label"]["MIXED"]["f1"],
            "neutral_precision": llm["per_label"]["NEUTRAL"]["precision"],
            "neutral_recall": llm["per_label"]["NEUTRAL"]["recall"],
            "neutral_f1": llm["per_label"]["NEUTRAL"]["f1"],
            "regression_count": len(regression_rows),
            "false_mixed": len(false_mixed),
            "average_latency_ms": latency_statistics(predictions)["average_latency_ms"],
            "external_api_dependency": True,
            "estimated_cost_or_token_usage": token_statistics(predictions),
            "explainability": "overall label, aspect label, evidence, and short_reason",
            "aspect_support": True,
            "confidence_comparison_note": (
                "LLM confidence is not compared directly with KoELECTRA confidence."
            ),
        },
    }


def representative_case(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    row = next((item for item in predictions if item["text"] == REPRESENTATIVE_TEXT), None)
    if row is None:
        return {}
    return {
        "id": row["id"],
        "text": row["text"],
        "gold_label": row["gold_label"],
        "predicted_overall_label": row["predicted_overall_label"],
        "predicted_aspects": row["predicted_aspects"],
        "evidence_valid": row["evidence_valid"],
        "short_reason": row["short_reason"],
        "schema_validation": row["error"] is None,
        "latency_ms": row["latency_ms"],
        "token_usage": row["token_usage"],
        "cache_hit": row["cache_hit"],
        "target": {
            "overall_label": "MIXED",
            "aspects": [
                {"name": "scent", "sentiment": "POSITIVE"},
                {"name": "longevity", "sentiment": "NEGATIVE"},
            ],
        },
        "error": row["error"],
    }


def hallucinated_evidence(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases = []
    for row in predictions:
        if row["error"] is not None:
            continue
        for aspect in row["predicted_aspects"]:
            evidence = aspect.get("evidence", "")
            if evidence not in row["text"]:
                cases.append(
                    {
                        "id": row["id"],
                        "aspect": aspect,
                        "text": row["text"],
                    }
                )
    return cases


def collect_missing_aspects(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases = []
    for row in predictions:
        if row["error"] is not None:
            continue
        missing = sorted(
            aspect_names(metric_ready_aspects(row["gold_aspects"]))
            - aspect_names(metric_ready_aspects(row.get("raw_predicted_aspects", row.get("predicted_aspects", []))))
        )
        if missing:
            cases.append({"id": row["id"], "missing": missing})
    return cases


def collect_additional_aspects(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases = []
    for row in predictions:
        if row["error"] is not None:
            continue
        additional = sorted(
            aspect_names(metric_ready_aspects(row.get("raw_predicted_aspects", row.get("predicted_aspects", []))))
            - aspect_names(metric_ready_aspects(row["gold_aspects"]))
        )
        if additional:
            cases.append({"id": row["id"], "additional": additional})
    return cases


def latency_statistics(predictions: list[dict[str, Any]]) -> dict[str, float]:
    values = [float(row["latency_ms"]) for row in predictions if row["error"] is None]
    if not values:
        return {"average_latency_ms": 0.0, "p50_latency_ms": 0.0, "p95_latency_ms": 0.0}
    return {
        "average_latency_ms": average(values),
        "p50_latency_ms": percentile(values, 50),
        "p95_latency_ms": percentile(values, 95),
    }


def token_statistics(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    usage_rows = [
        row["token_usage"]
        for row in predictions
        if row["error"] is None and isinstance(row.get("token_usage"), dict)
    ]
    total_tokens = sum(int(row.get("total_tokens", 0)) for row in usage_rows)
    return {
        "average_token_usage": safe_divide(total_tokens, len(usage_rows)),
        "total_token_usage": total_tokens,
        "usage_rows": len(usage_rows),
    }


def average_confidence_by_label(predictions: list[dict[str, Any]]) -> dict[str, float]:
    return {
        label: average(
            float(row["confidence"])
            for row in predictions
            if row["gold_label"] == label and row.get("confidence") is not None
        )
        for label in LABELS
    }


def summarize_case(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "text": row["text"],
        "gold_label": row["gold_label"],
        "predicted_overall_label": row["predicted_overall_label"],
        "confidence": row["confidence"],
    }


def experiment_name_for_prompt_version(prompt_version: str) -> str:
    if prompt_version == "sentiment-aspect-v1":
        return V1_EXPERIMENT_NAME
    if prompt_version == "sentiment-aspect-v2-taxonomy":
        return V2_EXPERIMENT_NAME
    return EXPERIMENT_NAME


def default_report_run_metadata(
    records: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    *,
    output_path: str | None,
) -> dict[str, Any]:
    return {
        "resume_enabled": False,
        "offset": 0,
        "requested_limit": len(predictions),
        "selected_count": len(predictions),
        "expected_api_call_count": len(predictions),
        "actual_api_call_count": 0,
        "api_calls_attempted": 0,
        "cache_hit_count": 0,
        "reused_success_count": 0,
        "retry_candidate_count": len(predictions),
        "retried_failure_count": 0,
        "skipped_by_resume_count": 0,
        "failed_predictions": sum(1 for row in predictions if row.get("error") is not None),
        "stopped_early": False,
        "stop_reason": None,
        "stopped_at_id": None,
        "partial_saved": False,
        "output_path": output_path,
        "existing_output_found": False,
        "dataset_total": len(records),
    }


def load_existing_predictions_by_id(output_path: Path | None) -> dict[str, dict[str, Any]]:
    if output_path is None or not output_path.exists():
        return {}
    report = json.loads(output_path.read_text(encoding="utf-8"))
    predictions = report.get("predictions", []) if isinstance(report, dict) else []
    if not isinstance(predictions, list):
        return {}
    return {
        prediction["id"]: prediction
        for prediction in predictions
        if isinstance(prediction, dict) and isinstance(prediction.get("id"), str)
    }


def is_successful_prediction(prediction: dict[str, Any] | None) -> bool:
    return isinstance(prediction, dict) and prediction.get("error") is None


def predictions_in_dataset_order(
    records: list[dict[str, Any]],
    predictions_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        predictions_by_id[record["id"]]
        for record in records
        if record.get("id") in predictions_by_id
    ]


def prediction_error_type(prediction: dict[str, Any]) -> str | None:
    error = prediction.get("error")
    if not isinstance(error, dict):
        return None
    error_type = error.get("type")
    return error_type if isinstance(error_type, str) else None


def progress_status(prediction: dict[str, Any]) -> str:
    error_type = prediction_error_type(prediction)
    if error_type:
        return f"failed error={error_type}"
    cache_hit = str(bool(prediction.get("cache_hit", False))).lower()
    latency_ms = int(float(prediction.get("latency_ms", 0.0)))
    return (
        f"success overall={prediction.get('predicted_overall_label')} "
        f"latency={latency_ms}ms cache_hit={cache_hit}"
    )


def progress_line(
    records: list[dict[str, Any]],
    dataset_index_by_id: dict[str, int],
    record: dict[str, Any],
    status: str,
) -> str:
    index = dataset_index_by_id.get(record["id"], 0) + 1
    return f"[{index}/{len(records)}] {record['id']} {status}"


def save_partial_report(
    records: list[dict[str, Any]],
    predictions_by_id: dict[str, dict[str, Any]],
    dataset_path: Path,
    adapter: OpenAICompatibleAdapter,
    cache: JsonlLLMCache | None,
    use_cache: bool,
    refresh_cache: bool,
    prompt_version: str,
    schema_version: str,
    stats: dict[str, Any],
    output_path: Path | None,
) -> None:
    if output_path is None:
        return
    stats["partial_saved"] = True
    report = build_report(
        records,
        predictions_in_dataset_order(records, predictions_by_id),
        dataset_path,
        provider_type=adapter.provider_type,
        provider_host=adapter.config.provider_host,
        model=adapter.config.model,
        cache_usage=cache_usage_payload(use_cache, refresh_cache, cache),
        run_mode="EVALUATION",
        prompt_version=prompt_version,
        schema_version=schema_version,
        run_metadata=stats,
    )
    write_report(output_path, report)


def write_report(output_path: Path, report: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_dry_run_report(
    records: list[dict[str, Any]],
    dataset_path: Path,
    limit: int | None,
    use_cache: bool,
    refresh_cache: bool,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
    *,
    offset: int = 0,
    resume: bool = False,
    output_path: Path | None = None,
) -> dict[str, Any]:
    missing = missing_configuration()
    model = "CONFIGURATION_MISSING" if missing else load_config_from_env().model
    selected = apply_offset_and_limit(records, offset, limit)
    sample = selected[0] if selected else (records[0] if records else None)
    sample_validation = None
    if sample:
        sample_json = json.dumps(
            {
                "overall_label": sample["overall_label"],
                "aspects": [
                    {
                        "name": aspect["name"],
                        "sentiment": aspect["sentiment"],
                        "evidence": sample["text"][: min(8, len(sample["text"]))],
                    }
                    for aspect in sample["aspects"][:1]
                ],
                "confidence": None,
                "short_reason": "dry-run schema validation sample",
            },
            ensure_ascii=False,
        )
        try:
            validate_llm_result(sample_json, sample["text"], schema_version)
            sample_validation = {"ok": True, "error": None}
        except Exception as exc:
            sample_validation = {"ok": False, "error": str(exc)}

    existing_predictions = (
        load_existing_predictions_by_id(output_path) if resume and output_path else {}
    )
    reusable_success_count = sum(
        1
        for record in selected
        if is_successful_prediction(existing_predictions.get(record["id"]))
    )
    retry_candidate_count = len(selected) - reusable_success_count
    expected_api_call_count = estimated_call_count(
        [
            record
            for record in selected
            if not is_successful_prediction(existing_predictions.get(record["id"]))
        ],
        model,
        use_cache,
        refresh_cache,
        prompt_version,
        schema_version,
    )
    expected_cache_hit_count = retry_candidate_count - expected_api_call_count
    dry_run_info = {
        "actual_api_calls_performed": 0,
        "actual_api_call_count": 0,
        "dataset_total": len(records),
        "offset": offset,
        "requested_limit": limit,
        "selected_count": len(selected),
        "existing_output_found": bool(existing_predictions),
        "reusable_success_count": reusable_success_count,
        "reused_success_count": reusable_success_count,
        "retry_candidate_count": retry_candidate_count,
        "cache_hit_count": expected_cache_hit_count,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "configuration": {
            "ok": not missing,
            "missing": missing,
            "error": (
                {"error": "missing_llm_configuration", "missing": missing}
                if missing
                else None
            ),
        },
        "sample_prompt_message_count": len(build_messages(sample["text"], prompt_version)) if sample else 0,
        "sample_schema_validation": sample_validation,
        "expected_api_call_count": expected_api_call_count,
    }
    run_metadata = {
        "resume_enabled": resume,
        "offset": offset,
        "requested_limit": limit,
        "dataset_total": len(records),
        "selected_count": len(selected),
        "expected_api_call_count": expected_api_call_count,
        "reused_success_count": reusable_success_count,
        "retry_candidate_count": retry_candidate_count,
        "retried_failure_count": retry_candidate_count,
        "skipped_by_resume_count": reusable_success_count,
        "api_calls_attempted": 0,
        "actual_api_call_count": 0,
        "cache_hit_count": expected_cache_hit_count,
        "failed_predictions": 0,
        "stopped_early": False,
        "stop_reason": None,
        "stopped_at_id": None,
        "partial_saved": False,
        "output_path": str(output_path) if output_path else None,
        "existing_output_found": bool(existing_predictions),
    }
    return build_report(
        records,
        [],
        dataset_path,
        provider_type=OpenAICompatibleAdapter.provider_type,
        provider_host=None if missing else load_config_from_env().provider_host,
        model=model,
        cache_usage={
            "use_cache": use_cache,
            "refresh_cache": refresh_cache,
            "cache_path": str(DEFAULT_CACHE_PATH),
        },
        run_mode="DRY_RUN_ONLY",
        dry_run_info=dry_run_info,
        prompt_version=prompt_version,
        schema_version=schema_version,
        run_metadata=run_metadata,
    )


def estimated_call_count(
    records: list[dict[str, Any]],
    model: str,
    use_cache: bool,
    refresh_cache: bool,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
    *,
    cache: JsonlLLMCache | None = None,
) -> int:
    if refresh_cache or not use_cache:
        return len(records)
    cache = cache or JsonlLLMCache(DEFAULT_CACHE_PATH)
    return sum(
        1
        for record in records
        if cache.get(build_cache_key(record["text"], model, prompt_version, schema_version)) is None
    )


def cache_usage_payload(
    use_cache: bool,
    refresh_cache: bool,
    cache: JsonlLLMCache | None,
) -> dict[str, Any]:
    return {
        "use_cache": use_cache,
        "refresh_cache": refresh_cache,
        "cache_path": str(cache.path if cache else DEFAULT_CACHE_PATH),
    }


def format_startup_summary(
    records: list[dict[str, Any]],
    selected_records: list[dict[str, Any]],
    *,
    dry_run: bool,
    model: str,
    provider_host: str | None,
    use_cache: bool,
    refresh_cache: bool,
    offset: int = 0,
    requested_limit: int | None = DEFAULT_SAFE_LIMIT,
    expected_api_call_count: int | None = None,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    expected = len(selected_records) if expected_api_call_count is None else expected_api_call_count
    actual: int | str = 0 if dry_run else "pending"
    lines = [
        "SentiTrack LLM structured sentiment evaluation",
        f"- provider_host: {provider_host or 'not configured'}",
        f"- model: {model}",
        f"- prompt_version: {prompt_version}",
        f"- schema_version: {schema_version}",
        f"- dataset_total: {len(records)}",
        f"- offset: {offset}",
        f"- requested_limit: {requested_limit}",
        f"- selected_count: {len(selected_records)}",
        f"- cache: use_cache={use_cache}, refresh_cache={refresh_cache}, path={DEFAULT_CACHE_PATH}",
        f"- expected_api_call_count: {expected}",
        f"- actual_api_call_count: {actual}",
    ]
    return "\n".join(lines)


def format_console_summary(report: dict[str, Any], output_path: Path | None) -> str:
    metadata = report["metadata"]
    overall = report["overall_metrics"]
    dry_run = report.get("dry_run")
    lines = [
        "SentiTrack LLM structured sentiment report",
        f"- run_mode: {metadata['run_mode']}",
        f"- experiment_name: {metadata['experiment_name']}",
        f"- prompt_version: {metadata['prompt_version']}",
        f"- schema_version: {metadata['schema_version']}",
        f"- selected_count: {metadata['selected_count']}",
        f"- expected_api_call_count: {metadata['expected_api_call_count']}",
        f"- actual_api_call_count: {metadata['actual_api_call_count']}",
        f"- cache_hit_count: {metadata['cache_hit_count']}",
        f"- reused_success_count: {metadata['reused_success_count']}",
        f"- retry_candidate_count: {metadata['retry_candidate_count']}",
        f"- evaluated_count: {metadata['evaluated_count']}",
        f"- successful_predictions: {overall['successful_predictions']}",
        f"- failed_predictions: {metadata['failed_predictions']}",
        f"- exact_match_accuracy: {overall['exact_match_accuracy']:.4f}",
        f"- stopped_early: {str(bool(metadata['stopped_early'])).lower()}",
        f"- stop_reason: {metadata['stop_reason']}",
        f"- partial_saved: {str(bool(metadata['partial_saved'])).lower()}",
        f"- output_path: {metadata['output_path']}",
        f"- output: {output_path if output_path else 'not written'}",
    ]
    if metadata.get("stopped_early"):
        lines.append(f"- stopped_early: true")
        lines.append(f"- stop_reason: {metadata.get('stop_reason')}")
        if metadata.get("stop_reason") == "RATE_LIMIT":
            lines.append("RATE_LIMIT detected. Partial report saved. Re-run later with --resume --use-cache.")
    if dry_run:
        lines.append(f"- dry_run_expected_api_call_count: {dry_run['expected_api_call_count']}")
        lines.append(f"- dry_run_selected_count: {dry_run['selected_count']}")
        lines.append(f"- dry_run_reusable_success_count: {dry_run['reusable_success_count']}")
        lines.append(f"- dry_run_retry_candidate_count: {dry_run['retry_candidate_count']}")
        if not dry_run["configuration"]["ok"]:
            lines.append(
                "- missing_configuration: "
                + json.dumps(dry_run["configuration"]["missing"], ensure_ascii=False)
            )
    return "\n".join(lines)


def apply_limit(records: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    return apply_offset_and_limit(records, 0, limit)


def apply_offset_and_limit(
    records: list[dict[str, Any]],
    offset: int = 0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if offset < 0:
        raise ValueError("--offset must be zero or greater")
    if limit is None:
        return records[offset : offset + DEFAULT_SAFE_LIMIT]
    if limit < 0:
        raise ValueError("--limit must be zero or greater")
    return records[offset : offset + limit]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate LLM structured sentiment offline.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--limit", type=int, default=DEFAULT_SAFE_LIMIT)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--use-cache", action="store_true")
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--save-partial", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--stop-on-rate-limit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--progress", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prompt-version", default=PROMPT_VERSION)
    parser.add_argument("--schema-version", default=None)
    parser.add_argument("--strict-taxonomy", action="store_true", default=True)
    return parser.parse_args()


def main_cli() -> int:
    args = parse_args()
    try:
        prompt_config = get_prompt_config(args.prompt_version)
        schema_version = args.schema_version or schema_version_for_prompt_version(
            prompt_config.prompt_version
        )
        schema_config = get_schema_config(prompt_config.prompt_version, schema_version)
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "error": "unsupported_version_override",
                    "detail": str(exc),
                    "supported_prompt_versions": list(supported_prompt_versions()),
                    "supported_schema_versions": list(supported_schema_versions()),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    if args.use_cache and args.refresh_cache:
        print(
            json.dumps(
                {"error": "invalid_cache_options", "detail": "--use-cache and --refresh-cache cannot both be set"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    try:
        records = load_dataset(args.dataset)
        selected_records = apply_offset_and_limit(records, args.offset, args.limit)
        missing = missing_configuration()
        model_for_summary = "CONFIGURATION_MISSING"
        provider_host = None
        if not missing:
            config = load_config_from_env()
            model_for_summary = config.model
            provider_host = config.provider_host
        existing_predictions = (
            load_existing_predictions_by_id(args.output) if args.resume else {}
        )
        startup_expected_api_calls = estimated_call_count(
            [
                record
                for record in selected_records
                if not is_successful_prediction(existing_predictions.get(record["id"]))
            ],
            model_for_summary,
            args.use_cache,
            args.refresh_cache,
            prompt_config.prompt_version,
            schema_config.schema_version,
        )

        print(
            format_startup_summary(
                records,
                selected_records,
                dry_run=args.dry_run,
                model=model_for_summary,
                provider_host=provider_host,
                use_cache=args.use_cache,
                refresh_cache=args.refresh_cache,
                offset=args.offset,
                requested_limit=args.limit,
                expected_api_call_count=startup_expected_api_calls,
                prompt_version=prompt_config.prompt_version,
                schema_version=schema_config.schema_version,
            )
        )

        if args.dry_run:
            report = build_dry_run_report(
                records,
                args.dataset,
                args.limit,
                args.use_cache,
                args.refresh_cache,
                prompt_config.prompt_version,
                schema_config.schema_version,
                offset=args.offset,
                resume=args.resume,
                output_path=args.output,
            )
        else:
            if missing:
                print(
                    json.dumps(
                        {"error": "missing_llm_configuration", "missing": missing},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 1
            config = load_config_from_env()
            adapter = OpenAICompatibleAdapter(
                config,
                prompt_version=prompt_config.prompt_version,
                schema_version=schema_config.schema_version,
            )
            cache = JsonlLLMCache(DEFAULT_CACHE_PATH) if args.use_cache or args.refresh_cache else None
            report = evaluate_llm_records_resumable(
                records,
                selected_records,
                adapter,
                args.dataset,
                output_path=args.output,
                offset=args.offset,
                requested_limit=args.limit,
                resume=args.resume,
                save_partial=args.save_partial,
                stop_on_rate_limit=args.stop_on_rate_limit,
                progress=args.progress,
                cache=cache,
                use_cache=args.use_cache,
                refresh_cache=args.refresh_cache,
                prompt_version=prompt_config.prompt_version,
                schema_version=schema_config.schema_version,
            )
    except Exception as exc:
        print(
            json.dumps(
                {"error": "llm_sentiment_evaluation_failed", "detail": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    if args.output and not args.dry_run and not args.save_partial:
        write_report(args.output, report)

    print(format_console_summary(report, None if args.dry_run else args.output))
    return 0


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def average(values) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(items) / len(items)


def percentile(values: list[float], percentile_value: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * percentile_value / 100
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return sorted_values[lower]
    fraction = index - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


if __name__ == "__main__":
    raise SystemExit(main_cli())
