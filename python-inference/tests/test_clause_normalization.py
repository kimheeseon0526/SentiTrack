import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from experiments.clause_normalization import (  # noqa: E402
    HANGUL_AWARE_DECLARATIVE,
    RAW,
    SIMPLE_DECLARATIVE,
    ensure_terminal_punctuation,
    normalize_clause,
    normalize_hangul_aware_declarative,
    normalize_simple_declarative,
    remove_jongseong_n,
)
from evaluate_clause_normalization import evaluate_normalization_experiment  # noqa: E402


def predictor_from(mapping):
    def predict(text):
        if text not in mapping:
            raise AssertionError(f"Unexpected prediction text: {text}")
        label, confidence = mapping[text]
        return {"normalized_label": label, "score": confidence, "raw_label": "1" if label == "POSITIVE" else "0"}

    return predict


def record(record_id, text, label, category="mixed_contrast"):
    return {
        "id": record_id,
        "text": text,
        "overall_label": label,
        "aspects": [],
        "category": category,
        "note": "test",
        "review_status": "PENDING_MANUAL_REVIEW",
        "source": "SYNTHETIC",
    }


@pytest.mark.parametrize(
    "text,expected",
    [
        ("좋지만", "좋다."),
        ("비싸지만", "비싸다."),
        ("좋았지만", "좋았다."),
        ("아쉬웠는데", "아쉬웠다."),
        ("제품인데", "제품이다."),
        ("좋은데", "좋다."),
        ("좋아하는데", "좋아하다."),
    ],
)
def test_simple_declarative_suffix_rules(text, expected):
    assert normalize_simple_declarative(text)[0] == expected
    assert normalize_clause(text, SIMPLE_DECLARATIVE).normalized_text == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("예쁜데", "예쁘다."),
        ("빠른데", "빠르다."),
        ("강한데", "강하다."),
        ("포근한데", "포근하다."),
    ],
)
def test_hangul_aware_declarative_removes_jongseong_n(text, expected):
    assert normalize_hangul_aware_declarative(text)[0] == expected
    assert normalize_clause(text, HANGUL_AWARE_DECLARATIVE).normalized_text == expected


def test_remove_jongseong_n():
    assert remove_jongseong_n("쁜") == "쁘"
    assert remove_jongseong_n("른") == "르"
    assert remove_jongseong_n("한") == "하"
    assert remove_jongseong_n("좋") == "좋"


def test_raw_strategy_keeps_original_text():
    result = normalize_clause("향은 너무 좋지만", RAW)

    assert result.normalized_text == "향은 너무 좋지만"
    assert result.normalization_applied is False


@pytest.mark.parametrize(
    "text",
    [
        "향이 좋아요.",
        "하지만 저는 좋아요",
        "",
        "   ",
        "가",
        "hello",
        "제품 123",
    ],
)
def test_safety_no_unwanted_normalization(text):
    result = normalize_clause(text, SIMPLE_DECLARATIVE)

    assert result.normalized_text == text


def test_terminal_punctuation_is_not_duplicated():
    assert ensure_terminal_punctuation("좋다.") == "좋다."
    assert normalize_clause("좋지만.", SIMPLE_DECLARATIVE).normalized_text == "좋다."


def test_empty_normalized_clause_falls_back():
    result = normalize_clause("지만", SIMPLE_DECLARATIVE)

    assert result.normalized_text == "지만"
    assert result.fallback_reason == "INVALID_NORMALIZED_CLAUSE"


def test_strategy_comparison_mixed_when_normalized_clause_predictions_disagree():
    records = [record("mixed", "향은 너무 좋지만 지속력이 별로예요.", "MIXED")]
    fake_predictor = predictor_from(
        {
            "향은 너무 좋지만 지속력이 별로예요.": ("NEGATIVE", 0.95),
            "향은 너무 좋지만": ("NEGATIVE", 0.61),
            "지속력이 별로예요.": ("NEGATIVE", 0.98),
            "향은 너무 좋다.": ("POSITIVE", 0.93),
        }
    )

    report = evaluate_normalization_experiment(records, fake_predictor, {}, Path("dataset.jsonl"))
    strategy = report["all_predictions"][0]["strategy_results"][HANGUL_AWARE_DECLARATIVE]

    assert strategy["experimental_label"] == "MIXED"
    assert strategy["improvement"] is True


def test_same_sentiment_two_clauses_are_not_mixed():
    records = [record("positive", "향은 좋지만 지속력도 좋아요.", "POSITIVE")]
    fake_predictor = predictor_from(
        {
            "향은 좋지만 지속력도 좋아요.": ("POSITIVE", 0.95),
            "향은 좋지만": ("POSITIVE", 0.9),
            "지속력도 좋아요.": ("POSITIVE", 0.92),
            "향은 좋다.": ("POSITIVE", 0.91),
        }
    )

    report = evaluate_normalization_experiment(records, fake_predictor, {}, Path("dataset.jsonl"))

    assert report["all_predictions"][0]["strategy_results"][SIMPLE_DECLARATIVE]["experimental_label"] == "POSITIVE"


def test_low_confidence_opposite_clauses_fall_back():
    records = [record("mixed", "가격은 비싸지만 그만큼 만족스러워요.", "MIXED")]
    fake_predictor = predictor_from(
        {
            "가격은 비싸지만 그만큼 만족스러워요.": ("POSITIVE", 0.95),
            "가격은 비싸지만": ("NEGATIVE", 0.65),
            "그만큼 만족스러워요.": ("POSITIVE", 0.96),
            "가격은 비싸다.": ("NEGATIVE", 0.65),
        }
    )

    report = evaluate_normalization_experiment(records, fake_predictor, {}, Path("dataset.jsonl"))
    strategy = report["all_predictions"][0]["strategy_results"][SIMPLE_DECLARATIVE]

    assert strategy["experimental_label"] == "POSITIVE"
    assert strategy["fallback_reason"] == "LOW_CONFIDENCE_MIXED_CANDIDATE"


def test_predictor_exception_falls_back_to_baseline():
    records = [record("mixed", "향은 좋지만 지속력이 별로예요.", "MIXED")]

    def broken_predictor(text):
        if text == "향은 좋지만 지속력이 별로예요.":
            return {"normalized_label": "NEGATIVE", "score": 0.9, "raw_label": "0"}
        raise RuntimeError("boom")

    report = evaluate_normalization_experiment(records, broken_predictor, {}, Path("dataset.jsonl"))
    strategy = report["all_predictions"][0]["strategy_results"][SIMPLE_DECLARATIVE]

    assert strategy["experimental_label"] == "NEGATIVE"
    assert strategy["fallback_reason"].startswith("PREDICTOR_ERROR")


@pytest.mark.parametrize(
    "text,baseline,expected",
    [
        ("향은 좋지만 지속력도 좋아요.", "POSITIVE", "POSITIVE"),
        ("향은 별로지만 지속력도 짧아요.", "NEGATIVE", "NEGATIVE"),
        ("처음 써봤는데 생각보다 고급스럽고 오래 남아요.", "POSITIVE", "POSITIVE"),
        ("향은 좋고 지속력도 좋아요.", "POSITIVE", "POSITIVE"),
        ("향은 별로고 가격도 비싸요.", "NEGATIVE", "NEGATIVE"),
    ],
)
def test_regression_prevention_cases(text, baseline, expected):
    clauses = {
        text: (baseline, 0.95),
        "향은 좋지만": ("POSITIVE", 0.9),
        "지속력도 좋아요.": ("POSITIVE", 0.92),
        "향은 좋다.": ("POSITIVE", 0.9),
        "향은 별로지만": ("NEGATIVE", 0.9),
        "지속력도 짧아요.": ("NEGATIVE", 0.92),
        "향은 별로다.": ("NEGATIVE", 0.9),
        "처음 써봤는데": ("POSITIVE", 0.9),
        "생각보다 고급스럽고 오래 남아요.": ("POSITIVE", 0.94),
        "처음 써봤다.": ("POSITIVE", 0.9),
    }
    report = evaluate_normalization_experiment(
        [record("case", text, expected, "single_positive" if expected == "POSITIVE" else "single_negative")],
        predictor_from(clauses),
        {},
        Path("dataset.jsonl"),
    )

    assert report["all_predictions"][0]["strategy_results"][HANGUL_AWARE_DECLARATIVE]["experimental_label"] == expected
