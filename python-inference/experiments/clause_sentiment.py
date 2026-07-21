from __future__ import annotations

import re
from typing import Any, Callable


SUPPORTED_LABELS = ("POSITIVE", "NEGATIVE")
EXPERIMENTAL_LABELS = ("POSITIVE", "NEGATIVE", "MIXED")
DEFAULT_CONFIDENCE_THRESHOLD = 0.7
ANALYSIS_METHOD = "CLAUSE_HYBRID"
MIN_CLAUSE_LENGTH = 4

STANDALONE_CONNECTORS = ("하지만", "그러나", "그런데", "근데", "다만", "반면", "반면에")
ENDING_CONNECTORS = ("지만", "는데", "은데", "인데", "ㄴ데")

Predictor = Callable[[str], dict[str, Any]]


def has_contrast_expression(text: str) -> bool:
    return len(split_contrast_clauses(text)) >= 2


def split_contrast_clauses(text: str) -> list[str]:
    original = text
    stripped = text.strip()
    if not stripped:
        return [original]

    standalone_split = _split_standalone_connector(stripped)
    if standalone_split:
        return standalone_split

    ending_split = _split_ending_connector(stripped)
    if ending_split:
        return ending_split

    return [original]


def _split_standalone_connector(text: str) -> list[str] | None:
    connector_pattern = "|".join(re.escape(connector) for connector in STANDALONE_CONNECTORS)
    # Standalone contrast adverbs usually appear between clauses with whitespace.
    match = re.search(rf"(.+?)\s+({connector_pattern})\s+(.+)", text)
    if not match:
        return None

    first = match.group(1).strip()
    second = f"{match.group(2)} {match.group(3)}".strip()
    return _safe_split_result(first, second)


def _split_ending_connector(text: str) -> list[str] | None:
    ending_pattern = "|".join(re.escape(ending) for ending in ENDING_CONNECTORS)
    # Ending connectors such as "지만" attach to the first clause, so keep them there.
    match = re.search(rf"(.+?(?:{ending_pattern}))\s*(.+)", text)
    if not match:
        return None

    first = match.group(1).strip()
    second = match.group(2).strip()
    return _safe_split_result(first, second)


def _safe_split_result(first: str, second: str) -> list[str] | None:
    clauses = [clause for clause in (first.strip(), second.strip()) if clause.strip()]
    if len(clauses) < 2:
        return None
    return clauses


def is_valid_clause(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < MIN_CLAUSE_LENGTH:
        return False
    return bool(re.search(r"[0-9A-Za-z가-힣]", stripped))


def normalize_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    label = prediction.get("normalized_label", prediction.get("label"))
    confidence = prediction.get("score", prediction.get("confidence"))
    if label not in SUPPORTED_LABELS:
        raise ValueError(f"Unsupported prediction label: {label!r}")
    return {
        "label": label,
        "confidence": float(confidence),
        "raw_label": prediction.get("raw_label"),
    }


def combine_clause_predictions(
    baseline_label: str,
    clause_predictions: list[dict[str, Any]],
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> str:
    try:
        valid_predictions = [
            prediction
            for prediction in clause_predictions
            if prediction.get("label") in SUPPORTED_LABELS
            and float(prediction.get("confidence", 0.0)) >= 0.0
        ]
        if baseline_label not in SUPPORTED_LABELS:
            return baseline_label
        if len(valid_predictions) < 2:
            return baseline_label

        labels = {prediction["label"] for prediction in valid_predictions}
        if labels == {"POSITIVE"}:
            return "POSITIVE"
        if labels == {"NEGATIVE"}:
            return "NEGATIVE"
        if labels == set(SUPPORTED_LABELS):
            positive_confidence = max(
                prediction["confidence"]
                for prediction in valid_predictions
                if prediction["label"] == "POSITIVE"
            )
            negative_confidence = max(
                prediction["confidence"]
                for prediction in valid_predictions
                if prediction["label"] == "NEGATIVE"
            )
            if (
                positive_confidence >= confidence_threshold
                and negative_confidence >= confidence_threshold
            ):
                return "MIXED"

        return baseline_label
    except Exception:
        return baseline_label


def analyze_clause_sentiment(
    text: str,
    predictor: Predictor,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    clause_normalizer: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    baseline_prediction = {"label": "NEGATIVE", "confidence": 0.0}
    try:
        baseline_prediction = normalize_prediction(predictor(text))
        baseline_label = baseline_prediction["label"]
        baseline_confidence = baseline_prediction["confidence"]
        raw_clauses = split_contrast_clauses(text)
        contrast_detected = len(raw_clauses) >= 2

        if not contrast_detected:
            return _fallback_result(
                text,
                baseline_label,
                baseline_confidence,
                False,
                [],
                "NO_CONTRAST",
            )

        if len(raw_clauses) < 2 or any(not is_valid_clause(clause) for clause in raw_clauses):
            return _fallback_result(
                text,
                baseline_label,
                baseline_confidence,
                True,
                [],
                "INVALID_CLAUSE_SPLIT",
            )

        clause_predictions = []
        for clause in raw_clauses:
            normalized_text = clause_normalizer(clause) if clause_normalizer is not None else clause
            prediction = normalize_prediction(predictor(normalized_text))
            clause_predictions.append(
                {
                    "text": clause,
                    "normalized_text": normalized_text if clause_normalizer is not None else None,
                    "label": prediction["label"],
                    "confidence": prediction["confidence"],
                    "raw_label": prediction.get("raw_label"),
                }
            )

        experimental_label = combine_clause_predictions(
            baseline_label,
            clause_predictions,
            confidence_threshold,
        )
        fallback_reason = None
        if experimental_label == baseline_label and {
            prediction["label"] for prediction in clause_predictions
        } == set(SUPPORTED_LABELS):
            fallback_reason = "LOW_CONFIDENCE_MIXED_CANDIDATE"

        return {
            "text": text,
            "baseline_label": baseline_label,
            "baseline_confidence": baseline_confidence,
            "contrast_detected": contrast_detected,
            "clauses": clause_predictions,
            "experimental_label": experimental_label,
            "analysis_method": ANALYSIS_METHOD,
            "fallback_used": fallback_reason is not None,
            "fallback_reason": fallback_reason,
        }
    except Exception as exc:
        baseline_label = baseline_prediction.get("label", "NEGATIVE")
        baseline_confidence = baseline_prediction.get("confidence", 0.0)
        return _fallback_result(
            text,
            baseline_label,
            baseline_confidence,
            has_contrast_expression(text),
            [],
            f"PREDICTOR_ERROR: {exc}",
        )


def _fallback_result(
    text: str,
    baseline_label: str,
    baseline_confidence: float,
    contrast_detected: bool,
    clauses: list[dict[str, Any]],
    fallback_reason: str,
) -> dict[str, Any]:
    return {
        "text": text,
        "baseline_label": baseline_label,
        "baseline_confidence": baseline_confidence,
        "contrast_detected": contrast_detected,
        "clauses": clauses,
        "experimental_label": baseline_label,
        "analysis_method": ANALYSIS_METHOD,
        "fallback_used": True,
        "fallback_reason": fallback_reason,
    }
