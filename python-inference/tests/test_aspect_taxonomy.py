import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from experiments.aspect_taxonomy import normalize_aspect_name  # noqa: E402
import evaluate_aspect_taxonomy as evaluator  # noqa: E402


def test_canonical_aspect_is_kept():
    result = normalize_aspect_name("scent")

    assert result.normalized_name == "scent"
    assert result.status == "CANONICAL"
    assert result.normalization_applied is False


def test_case_and_whitespace_are_normalized():
    result = normalize_aspect_name("  First   Scent  ")

    assert result.raw_name == "  First   Scent  "
    assert result.normalized_name == "scent"
    assert result.matched_alias == "first scent"
    assert result.status == "NORMALIZED"


def test_requested_aliases_normalize_to_canonical_names():
    assert normalize_aspect_name("first scent").normalized_name == "scent"
    assert normalize_aspect_name("afternote").normalized_name == "scent"
    assert normalize_aspect_name("price-performance").normalized_name == "price"
    assert normalize_aspect_name("spray").normalized_name == "usability"


def test_overall_is_excluded_from_aspect_metrics():
    result = normalize_aspect_name("overall")

    assert result.normalized_name is None
    assert result.status == "EXCLUDED_OVERALL"


def test_review_required_names_are_not_auto_mapped():
    assert normalize_aspect_name("satisfaction").status == "REVIEW_REQUIRED"
    assert normalize_aspect_name("gift suitability").status == "REVIEW_REQUIRED"


def test_physical_reaction_candidates_normalize():
    assert normalize_aspect_name("health").normalized_name == "physical_reaction"
    assert normalize_aspect_name("headache").normalized_name == "physical_reaction"
    assert normalize_aspect_name("irritation").normalized_name == "physical_reaction"


def test_unknown_blank_and_none_inputs_are_safe():
    assert normalize_aspect_name("unknown axis").status == "OTHER"
    assert normalize_aspect_name(" ").status == "OTHER"
    assert normalize_aspect_name(None).status == "OTHER"


def test_gold_and_prediction_overall_are_both_excluded():
    report = make_report(
        [
            make_prediction(
                "r1",
                gold_aspects=[{"name": "overall", "sentiment": "NEUTRAL"}],
                predicted_aspects=[{"name": "overall", "sentiment": "NEUTRAL"}],
            )
        ]
    )
    records = [make_record("r1", [{"name": "overall", "sentiment": "NEUTRAL"}])]

    result = evaluator.evaluate_aspect_taxonomy(
        report,
        records,
        report_path=Path("report.json"),
        dataset_path=Path("dataset.jsonl"),
    )

    assert result["metadata"]["api_calls_performed"] == 0
    assert result["normalized_metrics"]["counts"]["gold_name_count"] == 0
    assert result["normalized_metrics"]["counts"]["predicted_name_count"] == 0
    assert result["per_prediction_details"][0]["missing_aspects_after_normalization"] == []


def test_normalization_improves_name_and_pair_metrics():
    report = make_report(
        [
            make_prediction(
                "r1",
                gold_aspects=[{"name": "scent", "sentiment": "POSITIVE"}],
                predicted_aspects=[
                    {"name": "first scent", "sentiment": "POSITIVE"},
                    {"name": "afternote", "sentiment": "POSITIVE"},
                ],
            ),
            make_prediction(
                "r2",
                gold_aspects=[{"name": "price", "sentiment": "POSITIVE"}],
                predicted_aspects=[{"name": "price-performance", "sentiment": "POSITIVE"}],
            ),
        ]
    )
    records = [
        make_record("r1", [{"name": "scent", "sentiment": "POSITIVE"}]),
        make_record("r2", [{"name": "price", "sentiment": "POSITIVE"}]),
    ]

    result = evaluator.evaluate_aspect_taxonomy(
        report,
        records,
        report_path=Path("report.json"),
        dataset_path=Path("dataset.jsonl"),
    )

    assert result["raw_metrics"]["aspect_name_f1"] == 0.0
    assert result["normalized_metrics"]["aspect_name_f1"] == 1.0
    assert result["normalized_metrics"]["pair_f1"] == 1.0
    assert result["metric_deltas"]["aspect_name_f1_normalized_minus_raw"] == 1.0


def test_sentiment_difference_prevents_pair_match():
    report = make_report(
        [
            make_prediction(
                "r1",
                gold_aspects=[{"name": "price", "sentiment": "POSITIVE"}],
                predicted_aspects=[{"name": "price", "sentiment": "NEGATIVE"}],
            )
        ]
    )
    records = [make_record("r1", [{"name": "price", "sentiment": "POSITIVE"}])]

    result = evaluator.evaluate_aspect_taxonomy(
        report,
        records,
        report_path=Path("report.json"),
        dataset_path=Path("dataset.jsonl"),
    )

    assert result["normalized_metrics"]["aspect_name_f1"] == 1.0
    assert result["normalized_metrics"]["pair_f1"] == 0.0
    assert result["sentiment_mismatch_cases"][0]["id"] == "r1"


def test_conflicting_normalized_sentiment_is_recorded():
    report = make_report(
        [
            make_prediction(
                "r1",
                gold_aspects=[{"name": "scent", "sentiment": "POSITIVE"}],
                predicted_aspects=[
                    {"name": "first scent", "sentiment": "POSITIVE"},
                    {"name": "afternote", "sentiment": "NEGATIVE"},
                ],
            )
        ]
    )
    records = [make_record("r1", [{"name": "scent", "sentiment": "POSITIVE"}])]

    result = evaluator.evaluate_aspect_taxonomy(
        report,
        records,
        report_path=Path("report.json"),
        dataset_path=Path("dataset.jsonl"),
    )

    conflicts = result["conflicting_sentiment_cases"]
    assert conflicts[0]["conflicts"][0]["status"] == "CONFLICTING_NORMALIZED_SENTIMENT"
    assert conflicts[0]["conflicts"][0]["normalized_name"] == "scent"


def test_review_required_additional_aspect_remains_visible():
    report = make_report(
        [
            make_prediction(
                "r1",
                gold_aspects=[{"name": "price", "sentiment": "NEGATIVE"}],
                predicted_aspects=[
                    {"name": "price", "sentiment": "NEGATIVE"},
                    {"name": "satisfaction", "sentiment": "POSITIVE"},
                ],
            )
        ]
    )
    records = [make_record("r1", [{"name": "price", "sentiment": "NEGATIVE"}])]

    result = evaluator.evaluate_aspect_taxonomy(
        report,
        records,
        report_path=Path("report.json"),
        dataset_path=Path("dataset.jsonl"),
    )

    assert result["review_required_cases"][0]["id"] == "r1"
    assert result["remaining_additional_aspects"][0]["additional_aspects_after_normalization"] == [
        "satisfaction"
    ]


def make_report(predictions):
    return {
        "overall_metrics": {"exact_match_accuracy": 1.0},
        "aspect_metrics": {
            "evidence_substring_validation_rate": 1.0,
            "hallucinated_evidence_count": 0,
        },
        "predictions": predictions,
    }


def make_record(record_id, aspects):
    return {
        "id": record_id,
        "text": "sample text",
        "overall_label": "POSITIVE",
        "aspects": aspects,
        "category": "test",
        "note": "test",
        "review_status": "PENDING_MANUAL_REVIEW",
        "source": "SYNTHETIC",
    }


def make_prediction(record_id, *, gold_aspects, predicted_aspects):
    return {
        "id": record_id,
        "text": "sample text",
        "gold_label": "POSITIVE",
        "gold_aspects": gold_aspects,
        "predicted_overall_label": "POSITIVE",
        "predicted_aspects": predicted_aspects,
        "overall_match": True,
        "error": None,
    }
