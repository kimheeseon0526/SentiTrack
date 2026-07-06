import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import evaluate_llm_sentiment as evaluator  # noqa: E402
from experiments.llm_sentiment_client import (  # noqa: E402
    JsonlLLMCache,
    LLMCallResult,
    LLMConfig,
    LLMSentimentError,
    build_cache_key,
    cache_key_parts,
)
from experiments.llm_sentiment_schema import V1_SCHEMA_VERSION, validate_llm_result  # noqa: E402


PROMPT_VERSION = "sentiment-aspect-v1"
SCHEMA_VERSION = V1_SCHEMA_VERSION


def make_records(count=5):
    return [
        {
            "id": f"eval-{index + 1:03d}",
            "text": f"review {index} scent",
            "overall_label": "POSITIVE",
            "aspects": [{"name": "scent", "sentiment": "POSITIVE"}],
            "category": "test",
            "review_status": "PENDING_MANUAL_REVIEW",
            "source": "SYNTHETIC",
        }
        for index in range(count)
    ]


def result_json(text):
    return json.dumps(
        {
            "overall_label": "POSITIVE",
            "aspects": [{"name": "scent", "sentiment": "POSITIVE", "evidence": text}],
            "confidence": None,
            "short_reason": "ok",
        }
    )


class FakeAdapter:
    provider_type = "fake"

    def __init__(self, outcomes=None, api_key="secret-api-key"):
        self.config = LLMConfig(api_key, "model-a", "https://llm.example/v1")
        self.outcomes = list(outcomes or [])
        self.calls = []

    def analyze(self, text):
        self.calls.append(text)
        outcome = self.outcomes.pop(0) if self.outcomes else "success"
        if outcome in {"RATE_LIMIT", "PROVIDER_ERROR", "INVALID_JSON"}:
            raise LLMSentimentError(outcome, f"{outcome} without secret-api-key")
        raw_text = result_json(text)
        return LLMCallResult(
            result=validate_llm_result(raw_text, text, SCHEMA_VERSION),
            latency_ms=12.0,
            token_usage=None,
            cache_hit=False,
            model=self.config.model,
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            raw_text=raw_text,
            provider_host=self.config.provider_host,
        )


def write_existing_report(path, records, predictions):
    report = evaluator.build_report(
        records,
        predictions,
        Path("dataset.jsonl"),
        provider_type="fake",
        provider_host="llm.example",
        model="model-a",
        cache_usage={"use_cache": False, "refresh_cache": False, "cache_path": "cache.jsonl"},
        run_mode="EVALUATION",
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
    )
    evaluator.write_report(path, report)


def success_prediction(record):
    adapter = FakeAdapter()
    return evaluator.prediction_payload(
        record,
        adapter.analyze(record["text"]),
    )


def failure_prediction(record, error_type="PROVIDER_ERROR"):
    return evaluator.failure_payload(
        record,
        {"type": error_type, "message": "failed"},
        "model-a",
        provider_host="llm.example",
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
    )


def run_resumable(records, adapter, output_path, **kwargs):
    offset = kwargs.pop("offset", 0)
    limit = kwargs.pop("limit", len(records))
    selected = evaluator.apply_offset_and_limit(
        records,
        offset,
        limit,
    )
    return evaluator.evaluate_llm_records_resumable(
        records,
        selected,
        adapter,
        Path("dataset.jsonl"),
        output_path=output_path,
        offset=offset,
        requested_limit=limit,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        progress=False,
        **kwargs,
    )


def test_offset_and_limit_selects_expected_slice():
    records = make_records(25)

    selected = evaluator.apply_offset_and_limit(records, 10, 10)

    assert [record["id"] for record in selected] == [f"eval-{index:03d}" for index in range(11, 21)]


def test_resume_reuses_existing_success(tmp_path):
    records = make_records(2)
    output = tmp_path / "report.json"
    write_existing_report(output, records, [success_prediction(records[0])])
    adapter = FakeAdapter()

    report = run_resumable(records, adapter, output, resume=True, limit=1)

    assert adapter.calls == []
    assert report["metadata"]["reused_success_count"] == 1
    assert report["metadata"]["actual_api_call_count"] == 0
    assert report["predictions"][0]["id"] == "eval-001"


def test_resume_retries_existing_failure(tmp_path):
    records = make_records(1)
    output = tmp_path / "report.json"
    write_existing_report(output, records, [failure_prediction(records[0])])
    adapter = FakeAdapter()

    report = run_resumable(records, adapter, output, resume=True)

    assert adapter.calls == [records[0]["text"]]
    assert report["metadata"]["retried_failure_count"] == 1
    assert report["predictions"][0]["error"] is None


def test_existing_out_of_range_prediction_is_preserved(tmp_path):
    records = make_records(3)
    output = tmp_path / "report.json"
    write_existing_report(output, records, [success_prediction(records[0])])
    adapter = FakeAdapter()

    report = run_resumable(records, adapter, output, resume=True, offset=1, limit=1)

    assert [row["id"] for row in report["predictions"]] == ["eval-001", "eval-002"]


def test_final_predictions_are_dataset_ordered(tmp_path):
    records = make_records(3)
    output = tmp_path / "report.json"
    write_existing_report(output, records, [success_prediction(records[2])])
    adapter = FakeAdapter()

    report = run_resumable(records, adapter, output, resume=True, offset=0, limit=2)

    assert [row["id"] for row in report["predictions"]] == ["eval-001", "eval-002", "eval-003"]


def test_use_cache_hit_avoids_api_call(tmp_path):
    records = make_records(1)
    cache = JsonlLLMCache(tmp_path / "cache.jsonl")
    cache.set(
        build_cache_key(records[0]["text"], "model-a", PROMPT_VERSION, SCHEMA_VERSION),
        {
            "cache_key_parts": cache_key_parts(records[0]["text"], "model-a", PROMPT_VERSION, SCHEMA_VERSION),
            "raw_text": result_json(records[0]["text"]),
            "latency_ms": 1.0,
            "token_usage": None,
        },
    )
    adapter = FakeAdapter()

    report = run_resumable(records, adapter, tmp_path / "report.json", cache=cache, use_cache=True)

    assert adapter.calls == []
    assert report["predictions"][0]["cache_hit"] is True
    assert report["metadata"]["cache_hit_count"] == 1
    assert report["metadata"]["actual_api_call_count"] == 0
    assert report["overall_metrics"]["successful_predictions"] == 1


def test_refresh_cache_ignores_cache(tmp_path):
    records = make_records(1)
    cache = JsonlLLMCache(tmp_path / "cache.jsonl")
    cache.set(
        build_cache_key(records[0]["text"], "model-a", PROMPT_VERSION, SCHEMA_VERSION),
        {
            "cache_key_parts": cache_key_parts(records[0]["text"], "model-a", PROMPT_VERSION, SCHEMA_VERSION),
            "raw_text": result_json(records[0]["text"]),
            "latency_ms": 1.0,
            "token_usage": None,
        },
    )
    adapter = FakeAdapter()

    run_resumable(records, adapter, tmp_path / "report.json", cache=cache, refresh_cache=True)

    assert adapter.calls == [records[0]["text"]]


def test_rate_limit_stops_and_saves_partial_report(tmp_path):
    records = make_records(3)
    output = tmp_path / "report.json"
    adapter = FakeAdapter(["success", "RATE_LIMIT", "success"])

    report = run_resumable(records, adapter, output, stop_on_rate_limit=True)
    saved = json.loads(output.read_text(encoding="utf-8"))

    assert adapter.calls == [records[0]["text"], records[1]["text"]]
    assert report["metadata"]["stopped_early"] is True
    assert report["metadata"]["stop_reason"] == "RATE_LIMIT"
    assert report["metadata"]["partial_saved"] is True
    assert report["metadata"]["actual_api_call_count"] == 2
    assert saved["metadata"]["partial_saved"] is True
    assert saved["metadata"]["stop_reason"] == "RATE_LIMIT"
    assert [row["id"] for row in saved["predictions"]] == ["eval-001", "eval-002"]


def test_provider_error_continues_to_next_item(tmp_path):
    records = make_records(2)
    adapter = FakeAdapter(["PROVIDER_ERROR", "success"])

    report = run_resumable(records, adapter, tmp_path / "report.json")

    assert adapter.calls == [records[0]["text"], records[1]["text"]]
    assert [row["error"]["type"] if row["error"] else None for row in report["predictions"]] == [
        "PROVIDER_ERROR",
        None,
    ]


def test_invalid_json_continues_to_next_item(tmp_path):
    records = make_records(2)
    adapter = FakeAdapter(["INVALID_JSON", "success"])

    report = run_resumable(records, adapter, tmp_path / "report.json")

    assert adapter.calls == [records[0]["text"], records[1]["text"]]
    assert report["predictions"][0]["error"]["type"] == "INVALID_JSON"
    assert report["predictions"][1]["error"] is None


def test_dry_run_expected_call_count_with_resume(tmp_path):
    records = make_records(3)
    output = tmp_path / "report.json"
    write_existing_report(output, records, [success_prediction(records[0])])

    report = evaluator.build_dry_run_report(
        records,
        Path("dataset.jsonl"),
        3,
        False,
        False,
        PROMPT_VERSION,
        SCHEMA_VERSION,
        offset=0,
        resume=True,
        output_path=output,
    )

    assert report["dry_run"]["actual_api_calls_performed"] == 0
    assert report["dry_run"]["actual_api_call_count"] == 0
    assert report["metadata"]["actual_api_call_count"] == 0
    assert report["dry_run"]["expected_api_call_count"] == 2
    assert report["dry_run"]["reusable_success_count"] == 1


def test_progress_output_and_report_do_not_expose_api_key(tmp_path, capsys):
    records = make_records(2)
    output = tmp_path / "report.json"
    adapter = FakeAdapter(["PROVIDER_ERROR", "success"], api_key="super-secret-key")
    selected = evaluator.apply_offset_and_limit(records, 0, 2)

    evaluator.evaluate_llm_records_resumable(
        records,
        selected,
        adapter,
        Path("dataset.jsonl"),
        output_path=output,
        offset=0,
        requested_limit=2,
        progress=True,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
    )
    console = capsys.readouterr().out
    report_text = output.read_text(encoding="utf-8")

    assert "super-secret-key" not in console
    assert "super-secret-key" not in report_text


def test_console_summary_does_not_expose_api_key(tmp_path, capsys):
    records = make_records(1)
    output = tmp_path / "report.json"
    adapter = FakeAdapter(api_key="super-secret-key")

    report = run_resumable(records, adapter, output)
    console = evaluator.format_console_summary(report, output)

    assert "super-secret-key" not in console


def test_versions_are_recorded_in_cache_metadata_and_report(tmp_path):
    records = make_records(1)
    cache = JsonlLLMCache(tmp_path / "cache.jsonl")
    adapter = FakeAdapter()

    report = run_resumable(records, adapter, tmp_path / "report.json", cache=cache, use_cache=True)
    cache_text = (tmp_path / "cache.jsonl").read_text(encoding="utf-8")

    assert report["metadata"]["prompt_version"] == PROMPT_VERSION
    assert report["metadata"]["schema_version"] == SCHEMA_VERSION
    assert report["predictions"][0]["prompt_version"] == PROMPT_VERSION
    assert PROMPT_VERSION in cache_text
    assert SCHEMA_VERSION in cache_text


def test_actual_api_call_count_counts_only_provider_attempts(tmp_path):
    records = make_records(3)
    cache = JsonlLLMCache(tmp_path / "cache.jsonl")
    cache.set(
        build_cache_key(records[0]["text"], "model-a", PROMPT_VERSION, SCHEMA_VERSION),
        {
            "cache_key_parts": cache_key_parts(records[0]["text"], "model-a", PROMPT_VERSION, SCHEMA_VERSION),
            "raw_text": result_json(records[0]["text"]),
            "latency_ms": 1.0,
            "token_usage": None,
        },
    )
    output = tmp_path / "report.json"
    write_existing_report(output, records, [success_prediction(records[1])])
    adapter = FakeAdapter()

    report = run_resumable(records, adapter, output, resume=True, cache=cache, use_cache=True)

    assert adapter.calls == [records[2]["text"]]
    assert report["metadata"]["reused_success_count"] == 1
    assert report["metadata"]["cache_hit_count"] == 1
    assert report["metadata"]["actual_api_call_count"] == 1


def test_prompt_versions_are_selectable_in_dry_run(tmp_path):
    records = make_records(1)

    v1 = evaluator.build_dry_run_report(
        records,
        Path("dataset.jsonl"),
        1,
        False,
        False,
        "sentiment-aspect-v1",
        "llm-sentiment-schema-v1",
        output_path=tmp_path / "v1.json",
    )
    v2 = evaluator.build_dry_run_report(
        records,
        Path("dataset.jsonl"),
        1,
        False,
        False,
        "sentiment-aspect-v2-taxonomy",
        "llm-sentiment-schema-v2-taxonomy",
        output_path=tmp_path / "v2.json",
    )

    assert v1["metadata"]["prompt_version"] == "sentiment-aspect-v1"
    assert v2["metadata"]["prompt_version"] == "sentiment-aspect-v2-taxonomy"


def test_experiment_name_matches_prompt_version(tmp_path):
    records = make_records(1)

    v1 = evaluator.build_dry_run_report(
        records,
        Path("dataset.jsonl"),
        1,
        False,
        False,
        "sentiment-aspect-v1",
        "llm-sentiment-schema-v1",
        output_path=tmp_path / "v1.json",
    )
    v2 = evaluator.build_dry_run_report(
        records,
        Path("dataset.jsonl"),
        1,
        False,
        False,
        "sentiment-aspect-v2-taxonomy",
        "llm-sentiment-schema-v2-taxonomy",
        output_path=tmp_path / "v2.json",
    )

    assert v1["metadata"]["experiment_name"] == "LLM_STRUCTURED_SENTIMENT_ASPECT_V1_OFFLINE"
    assert v1["metadata"]["schema_version"] == "llm-sentiment-schema-v1"
    assert v2["metadata"]["experiment_name"] == "LLM_STRUCTURED_SENTIMENT_ASPECT_TAXONOMY_V2_OFFLINE"
    assert v2["metadata"]["schema_version"] == "llm-sentiment-schema-v2-taxonomy"


def test_report_metadata_does_not_expose_api_key(tmp_path):
    records = make_records(1)
    adapter = FakeAdapter(api_key="super-secret-key")

    report = run_resumable(records, adapter, tmp_path / "report.json")
    metadata_text = json.dumps(report["metadata"], ensure_ascii=False)

    assert "super-secret-key" not in metadata_text
