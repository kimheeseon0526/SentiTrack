import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from experiments.clause_sentiment import (  # noqa: E402
    analyze_clause_sentiment,
    combine_clause_predictions,
    has_contrast_expression,
    split_contrast_clauses,
)


def predictor_from(mapping):
    def predict(text):
        if text not in mapping:
            raise AssertionError(f"Unexpected prediction text: {text}")
        label, confidence = mapping[text]
        return {"normalized_label": label, "score": confidence, "raw_label": "1" if label == "POSITIVE" else "0"}

    return predict


@pytest.mark.parametrize(
    "text",
    [
        "향은 너무 좋지만 지속력이 별로예요.",
        "배송은 빨랐지만 포장이 아쉬워요.",
        "가격은 비싸지만 그만큼 만족스러워요.",
        "지속력은 별로지만 향 하나는 정말 최고예요.",
        "처음 써봤는데 생각보다 고급스럽고 오래 남아요.",
    ],
)
def test_detects_contrast_expression(text):
    assert has_contrast_expression(text) is True
    assert len(split_contrast_clauses(text)) == 2


def test_split_returns_original_when_no_contrast():
    text = "향은 좋고 지속력도 좋아요."

    assert split_contrast_clauses(text) == [text]
    assert has_contrast_expression(text) is False


@pytest.mark.parametrize(
    "text,baseline,first,second",
    [
        ("향은 너무 좋지만 지속력이 별로예요.", "NEGATIVE", ("POSITIVE", 0.91), ("NEGATIVE", 0.92)),
        ("배송은 빨랐지만 포장이 아쉬워요.", "NEGATIVE", ("POSITIVE", 0.9), ("NEGATIVE", 0.93)),
        ("가격은 비싸지만 그만큼 만족스러워요.", "POSITIVE", ("NEGATIVE", 0.88), ("POSITIVE", 0.95)),
        ("지속력은 별로지만 향 하나는 정말 최고예요.", "POSITIVE", ("NEGATIVE", 0.9), ("POSITIVE", 0.9)),
    ],
)
def test_mixed_expected_cases(text, baseline, first, second):
    clauses = split_contrast_clauses(text)
    predictor = predictor_from(
        {
            text: (baseline, 0.96),
            clauses[0]: first,
            clauses[1]: second,
        }
    )

    result = analyze_clause_sentiment(text, predictor)

    assert result["experimental_label"] == "MIXED"
    assert result["contrast_detected"] is True
    assert [clause["label"] for clause in result["clauses"]] == [first[0], second[0]]


@pytest.mark.parametrize(
    "text,baseline,first,second,expected",
    [
        ("향은 좋지만 지속력도 좋아요.", "POSITIVE", ("POSITIVE", 0.91), ("POSITIVE", 0.93), "POSITIVE"),
        ("향은 별로지만 지속력도 짧아요.", "NEGATIVE", ("NEGATIVE", 0.91), ("NEGATIVE", 0.93), "NEGATIVE"),
        ("처음 써봤는데 생각보다 고급스럽고 오래 남아요.", "POSITIVE", ("POSITIVE", 0.9), ("POSITIVE", 0.94), "POSITIVE"),
    ],
)
def test_false_mixed_prevention_with_contrast(text, baseline, first, second, expected):
    clauses = split_contrast_clauses(text)
    predictor = predictor_from(
        {
            text: (baseline, 0.95),
            clauses[0]: first,
            clauses[1]: second,
        }
    )

    result = analyze_clause_sentiment(text, predictor)

    assert result["experimental_label"] == expected
    assert result["experimental_label"] != "MIXED"


@pytest.mark.parametrize(
    "text,baseline,expected",
    [
        ("향은 좋고 지속력도 좋아요.", "POSITIVE", "POSITIVE"),
        ("향은 별로고 가격도 비싸요.", "NEGATIVE", "NEGATIVE"),
    ],
)
def test_false_mixed_prevention_without_contrast(text, baseline, expected):
    result = analyze_clause_sentiment(text, predictor_from({text: (baseline, 0.95)}))

    assert result["experimental_label"] == expected
    assert result["contrast_detected"] is False
    assert result["fallback_reason"] == "NO_CONTRAST"


def test_low_confidence_mixed_candidate_falls_back_to_baseline():
    text = "향은 좋지만 지속력이 별로예요."
    clauses = split_contrast_clauses(text)
    predictor = predictor_from(
        {
            text: ("NEGATIVE", 0.96),
            clauses[0]: ("POSITIVE", 0.69),
            clauses[1]: ("NEGATIVE", 0.95),
        }
    )

    result = analyze_clause_sentiment(text, predictor)

    assert result["experimental_label"] == "NEGATIVE"
    assert result["fallback_reason"] == "LOW_CONFIDENCE_MIXED_CANDIDATE"


def test_combine_clause_predictions_requires_two_valid_clauses():
    assert combine_clause_predictions("POSITIVE", [{"label": "NEGATIVE", "confidence": 0.95}]) == "POSITIVE"


def test_combine_clause_predictions_respects_threshold():
    predictions = [
        {"label": "POSITIVE", "confidence": 0.95},
        {"label": "NEGATIVE", "confidence": 0.69},
    ]

    assert combine_clause_predictions("POSITIVE", predictions, 0.7) == "POSITIVE"


def test_predictor_exception_falls_back_to_baseline_shape():
    def broken_predictor(text):
        raise RuntimeError("boom")

    result = analyze_clause_sentiment("향은 좋지만 지속력이 별로예요.", broken_predictor)

    assert result["experimental_label"] == result["baseline_label"]
    assert result["fallback_used"] is True
    assert result["fallback_reason"].startswith("PREDICTOR_ERROR")


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_or_blank_text_falls_back(text):
    result = analyze_clause_sentiment(text, predictor_from({text: ("NEGATIVE", 0.5)}))

    assert result["experimental_label"] == "NEGATIVE"
    assert result["fallback_reason"] == "NO_CONTRAST"


def test_too_short_clause_falls_back_to_baseline():
    text = "향은 좋지만 별로"
    clauses = split_contrast_clauses(text)

    assert clauses == ["향은 좋지만", "별로"]

    result = analyze_clause_sentiment(text, predictor_from({text: ("NEGATIVE", 0.8)}))

    assert result["experimental_label"] == "NEGATIVE"
    assert result["fallback_reason"] == "INVALID_CLAUSE_SPLIT"


def test_same_sentiment_two_clauses_keep_same_label():
    predictions = [
        {"label": "NEGATIVE", "confidence": 0.91},
        {"label": "NEGATIVE", "confidence": 0.93},
    ]

    assert combine_clause_predictions("POSITIVE", predictions, 0.7) == "NEGATIVE"
