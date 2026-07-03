import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import evaluate_sentiment_baseline as baseline  # noqa: E402


def make_record(
    record_id: str,
    text: str,
    overall_label: str,
    *,
    category: str = "test_category",
    review_status: str = baseline.EXPECTED_REVIEW_STATUS,
    source: str = baseline.EXPECTED_SOURCE,
) -> dict:
    return {
        "id": record_id,
        "text": text,
        "overall_label": overall_label,
        "aspects": [{"name": "overall", "sentiment": "NEUTRAL"}],
        "category": category,
        "note": "test note",
        "review_status": review_status,
        "source": source,
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def test_load_dataset_accepts_required_schema(tmp_path):
    dataset_path = tmp_path / "dataset.jsonl"
    write_jsonl(
        dataset_path,
        [
            make_record("sample-1", "향이 좋아요.", "POSITIVE"),
            make_record("sample-2", "그냥 무난해요.", "NEUTRAL"),
        ],
    )

    records = baseline.load_dataset(dataset_path)

    assert [record["id"] for record in records] == ["sample-1", "sample-2"]
    assert records[0]["review_status"] == "PENDING_MANUAL_REVIEW"
    assert records[0]["source"] == "SYNTHETIC"


def test_load_dataset_rejects_invalid_review_status(tmp_path):
    dataset_path = tmp_path / "dataset.jsonl"
    write_jsonl(
        dataset_path,
        [make_record("sample-1", "향이 좋아요.", "POSITIVE", review_status="APPROVED")],
    )

    with pytest.raises(ValueError, match="review_status"):
        baseline.load_dataset(dataset_path)


def test_load_dataset_rejects_invalid_source(tmp_path):
    dataset_path = tmp_path / "dataset.jsonl"
    write_jsonl(
        dataset_path,
        [make_record("sample-1", "향이 좋아요.", "POSITIVE", source="PRODUCTION")],
    )

    with pytest.raises(ValueError, match="source"):
        baseline.load_dataset(dataset_path)


def test_load_dataset_rejects_duplicate_ids(tmp_path):
    dataset_path = tmp_path / "dataset.jsonl"
    write_jsonl(
        dataset_path,
        [
            make_record("dup", "향이 좋아요.", "POSITIVE"),
            make_record("dup", "향이 별로예요.", "NEGATIVE"),
        ],
    )

    with pytest.raises(ValueError, match="duplicate id"):
        baseline.load_dataset(dataset_path)


def test_load_dataset_rejects_missing_required_field(tmp_path):
    dataset_path = tmp_path / "dataset.jsonl"
    record = make_record("sample-1", "향이 좋아요.", "POSITIVE")
    del record["category"]
    write_jsonl(dataset_path, [record])

    with pytest.raises(ValueError, match="category"):
        baseline.load_dataset(dataset_path)


def test_evaluate_records_statuses_and_high_confidence_flags():
    records = [
        make_record("match", "match", "POSITIVE"),
        make_record("mismatch", "mismatch", "NEGATIVE"),
        make_record("mixed", "mixed", "MIXED", category="mixed_contrast"),
        make_record("neutral", "neutral", "NEUTRAL", category="neutral_observation"),
    ]
    fake_predictions = {
        "match": {"raw_label": "1", "normalized_label": "POSITIVE", "score": 0.91},
        "mismatch": {"raw_label": "1", "normalized_label": "POSITIVE", "score": 0.88},
        "mixed": {"raw_label": "0", "normalized_label": "NEGATIVE", "score": 0.93},
        "neutral": {"raw_label": "1", "normalized_label": "POSITIVE", "score": 0.82},
    }

    report = baseline.evaluate_records(
        records,
        lambda text: fake_predictions[text],
        {"model_name": "test-model", "model_revision": "test-revision"},
        Path("dataset.jsonl"),
    )
    rows = {row["id"]: row for row in report["predictions"]}

    assert rows["match"]["result_status"] == "MATCH"
    assert rows["match"]["is_correct"] is True
    assert rows["mismatch"]["result_status"] == "MISMATCH"
    assert rows["mismatch"]["is_correct"] is False
    assert rows["mismatch"]["is_high_confidence_mismatch"] is True
    assert rows["mixed"]["result_status"] == "UNSUPPORTED_EXPECTED_LABEL"
    assert rows["mixed"]["is_correct"] is None
    assert rows["mixed"]["is_high_confidence_unsupported"] is True
    assert rows["neutral"]["result_status"] == "UNSUPPORTED_EXPECTED_LABEL"
    assert rows["neutral"]["is_correct"] is None
    assert rows["neutral"]["is_high_confidence_unsupported"] is True

    summary = report["summary"]
    assert summary["result_status_counts"] == {
        "MATCH": 1,
        "MISMATCH": 1,
        "UNSUPPORTED_EXPECTED_LABEL": 2,
    }
    assert summary["high_confidence_mismatch_count"] == 1
    assert summary["high_confidence_unsupported_count"] == 2
    assert summary["unsupported_label_distribution"] == {
        "MIXED": {"POSITIVE": 0, "NEGATIVE": 1},
        "NEUTRAL": {"POSITIVE": 1, "NEGATIVE": 0},
    }


def test_confidence_statistics_and_metric_names():
    records = [
        make_record("p", "p", "POSITIVE"),
        make_record("n", "n", "NEGATIVE"),
        make_record("m", "m", "MIXED"),
        make_record("u", "u", "NEUTRAL"),
    ]
    fake_predictions = {
        "p": {"raw_label": "1", "normalized_label": "POSITIVE", "score": 0.8},
        "n": {"raw_label": "1", "normalized_label": "POSITIVE", "score": 0.6},
        "m": {"raw_label": "0", "normalized_label": "NEGATIVE", "score": 1.0},
        "u": {"raw_label": "1", "normalized_label": "POSITIVE", "score": 0.4},
    }

    report = baseline.evaluate_records(records, lambda text: fake_predictions[text])
    stats = report["summary"]["confidence_statistics"]

    assert stats["overall_average_confidence"] == pytest.approx(0.7)
    assert stats["average_confidence_by_gold_label"]["POSITIVE"] == pytest.approx(0.8)
    assert stats["average_confidence_by_predicted_label"]["POSITIVE"] == pytest.approx(0.6)
    assert stats["mismatch_average_confidence"] == pytest.approx(0.6)
    assert stats["unsupported_expected_label_average_confidence"] == pytest.approx(0.7)
    assert report["four_class_diagnostic_metrics"]["diagnostic_exact_match_rate"] == pytest.approx(0.25)
    assert report["binary_supported_metrics"]["accuracy"] == pytest.approx(0.5)
    assert report["binary_only_metrics"] == report["binary_supported_metrics"]


def test_metadata_and_disclaimer_are_included():
    report = baseline.evaluate_records(
        [],
        lambda text: {"raw_label": "1", "normalized_label": "POSITIVE", "score": 0.9},
        {"model_name": "test-model", "model_revision": "test-revision"},
        Path("dataset.jsonl"),
    )

    assert report["metadata"]["model_name"] == "test-model"
    assert report["metadata"]["model_revision"] == "test-revision"
    assert report["metadata"]["dataset_path"] == "dataset.jsonl"
    assert report["metadata"]["dataset_total"] == 0
    assert report["metadata"]["supported_model_labels"] == ["POSITIVE", "NEGATIVE"]
    assert report["metadata"]["unsupported_expected_labels"] == ["MIXED", "NEUTRAL"]
    assert report["metadata"]["disclaimer"] == baseline.DISCLAIMER


def test_empty_prediction_list_returns_zero_metrics():
    report = baseline.evaluate_records(
        [],
        lambda text: {"raw_label": "1", "normalized_label": "POSITIVE", "score": 0.9},
    )

    assert report["dataset"]["total"] == 0
    assert report["four_class_diagnostic_metrics"]["total"] == 0
    assert report["four_class_diagnostic_metrics"]["diagnostic_exact_match_rate"] == 0.0
    assert report["binary_supported_metrics"]["total"] == 0
    assert report["binary_supported_metrics"]["accuracy"] == 0.0
    assert report["summary"]["confidence_statistics"]["overall_average_confidence"] == 0.0
