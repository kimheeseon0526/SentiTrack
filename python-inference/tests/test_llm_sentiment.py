import json
import sys
import urllib.error
from io import BytesIO
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from experiments.llm_sentiment_client import (  # noqa: E402
    LLMConfig,
    LLMSentimentError,
    OpenAICompatibleAdapter,
    JsonlLLMCache,
    analyze_with_cache,
    build_cache_key,
    load_config_from_env,
)
from experiments.llm_sentiment_schema import extract_json_payload, validate_llm_result  # noqa: E402
import evaluate_llm_sentiment as evaluator  # noqa: E402


REPRESENTATIVE_TEXT = "향은 너무 좋지만 지속력이 별로예요."


def make_record(record_id: str, text: str, label: str, aspects: list[dict] | None = None) -> dict:
    return {
        "id": record_id,
        "text": text,
        "overall_label": label,
        "aspects": aspects or [{"name": "scent", "sentiment": label if label != "MIXED" else "POSITIVE"}],
        "category": "test",
        "note": "test",
        "review_status": "PENDING_MANUAL_REVIEW",
        "source": "SYNTHETIC",
    }


def result_json(
    *,
    overall_label: str = "POSITIVE",
    aspects: list[dict] | None = None,
    confidence=None,
    short_reason: str = "짧은 이유입니다.",
) -> str:
    return json.dumps(
        {
            "overall_label": overall_label,
            "aspects": aspects or [{"name": "scent", "sentiment": "POSITIVE", "evidence": "향"}],
            "confidence": confidence,
            "short_reason": short_reason,
        },
        ensure_ascii=False,
    )


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def provider_payload(content: str, total_tokens: int = 12) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"total_tokens": total_tokens},
    }


def test_normal_json_parsing_and_validation():
    text = "향이 좋아요."
    parsed = extract_json_payload(result_json())
    result = validate_llm_result(json.dumps(parsed, ensure_ascii=False), text)

    assert result.overall_label == "POSITIVE"
    assert result.aspects[0].evidence == "향"


def test_json_inside_code_block_is_handled():
    text = "향이 좋아요."
    response = "```json\n" + result_json() + "\n```"

    result = validate_llm_result(response, text)

    assert result.overall_label == "POSITIVE"


def test_invalid_json_raises_validation_error():
    with pytest.raises(ValueError, match="invalid JSON"):
        extract_json_payload("{not-json")


def test_unsupported_overall_label_is_rejected():
    with pytest.raises(Exception, match="overall_label"):
        validate_llm_result(result_json(overall_label="HAPPY"), "향이 좋아요.")


def test_invalid_aspect_sentiment_is_rejected():
    with pytest.raises(Exception, match="sentiment"):
        validate_llm_result(
            result_json(aspects=[{"name": "scent", "sentiment": "MIXED", "evidence": "향"}]),
            "향이 좋아요.",
        )


def test_blank_aspect_name_is_rejected():
    with pytest.raises(Exception, match="non-empty"):
        validate_llm_result(
            result_json(aspects=[{"name": " ", "sentiment": "POSITIVE", "evidence": "향"}]),
            "향이 좋아요.",
        )


def test_evidence_must_exist_in_review_text():
    with pytest.raises(ValueError, match="substring"):
        validate_llm_result(
            result_json(aspects=[{"name": "scent", "sentiment": "POSITIVE", "evidence": "없는 문구"}]),
            "향이 좋아요.",
        )


def test_duplicate_aspect_combination_is_rejected():
    aspect = {"name": "scent", "sentiment": "POSITIVE", "evidence": "향"}
    with pytest.raises(Exception, match="duplicate"):
        validate_llm_result(result_json(aspects=[aspect, aspect]), "향이 좋아요.")


def test_confidence_range_is_rejected():
    with pytest.raises(Exception, match="confidence"):
        validate_llm_result(result_json(confidence=1.2), "향이 좋아요.")


def test_provider_timeout_is_classified():
    adapter = OpenAICompatibleAdapter(
        LLMConfig("secret-key", "test-model", "https://llm.example/v1"),
        max_retries=0,
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()),
    )

    with pytest.raises(LLMSentimentError) as exc:
        adapter.analyze("향이 좋아요.")

    assert exc.value.error_type == "TIMEOUT"


def test_provider_rate_limit_is_classified():
    def opener(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://llm.example", 429, "Too Many Requests", None, BytesIO())

    adapter = OpenAICompatibleAdapter(
        LLMConfig("secret-key", "test-model", "https://llm.example/v1"),
        max_retries=0,
        opener=opener,
    )

    with pytest.raises(LLMSentimentError) as exc:
        adapter.analyze("향이 좋아요.")

    assert exc.value.error_type == "RATE_LIMIT"


def test_retry_count_is_bounded():
    calls = {"count": 0}

    def opener(*_args, **_kwargs):
        calls["count"] += 1
        raise urllib.error.HTTPError("https://llm.example", 500, "Server Error", None, BytesIO())

    adapter = OpenAICompatibleAdapter(
        LLMConfig("secret-key", "test-model", "https://llm.example/v1"),
        max_retries=2,
        opener=opener,
    )

    with pytest.raises(LLMSentimentError) as exc:
        adapter.analyze("향이 좋아요.")

    assert exc.value.error_type == "PROVIDER_ERROR"
    assert calls["count"] == 3


def test_api_key_is_not_exposed_in_configuration_error():
    with pytest.raises(LLMSentimentError) as exc:
        load_config_from_env({})

    assert "secret-key" not in str(exc.value)
    assert "SENTITRACK_LLM_API_KEY" in str(exc.value)


def test_cache_hit_avoids_provider_call(tmp_path):
    cache = JsonlLLMCache(tmp_path / "cache.jsonl")
    config = LLMConfig("secret-key", "model-a", "https://llm.example/v1")
    text = "향이 좋아요."
    cache.set(
        build_cache_key(text, "model-a"),
        {
            "raw_text": result_json(),
            "latency_ms": 1.0,
            "token_usage": {"total_tokens": 10},
        },
    )

    adapter = OpenAICompatibleAdapter(
        config,
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("called")),
    )
    result = analyze_with_cache(text, adapter, cache=cache, use_cache=True)

    assert result.cache_hit is True
    assert result.result.overall_label == "POSITIVE"


def test_cache_miss_calls_provider_and_writes_cache(tmp_path):
    cache = JsonlLLMCache(tmp_path / "cache.jsonl")
    text = "향이 좋아요."
    calls = {"count": 0}

    def opener(*_args, **_kwargs):
        calls["count"] += 1
        return FakeResponse(provider_payload(result_json()))

    adapter = OpenAICompatibleAdapter(
        LLMConfig("secret-key", "model-a", "https://llm.example/v1"),
        opener=opener,
    )
    result = analyze_with_cache(text, adapter, cache=cache, use_cache=True)

    assert result.cache_hit is False
    assert calls["count"] == 1
    assert cache.get(build_cache_key(text, "model-a")) is not None


def test_prompt_version_change_causes_cache_miss(tmp_path, monkeypatch):
    cache = JsonlLLMCache(tmp_path / "cache.jsonl")
    text = "향이 좋아요."
    cache.set(
        build_cache_key(text, "model-a"),
        {"raw_text": result_json(), "latency_ms": 1.0, "token_usage": None},
    )
    monkeypatch.setattr("experiments.llm_sentiment_client.PROMPT_VERSION", "changed-version")
    calls = {"count": 0}

    def opener(*_args, **_kwargs):
        calls["count"] += 1
        return FakeResponse(provider_payload(result_json()))

    adapter = OpenAICompatibleAdapter(
        LLMConfig("secret-key", "model-a", "https://llm.example/v1"),
        opener=opener,
    )
    analyze_with_cache(text, adapter, cache=cache, use_cache=True)

    assert calls["count"] == 1


def test_dry_run_does_not_call_provider(monkeypatch):
    records = [make_record("r1", "향이 좋아요.", "POSITIVE")]
    monkeypatch.delenv("SENTITRACK_LLM_API_KEY", raising=False)
    monkeypatch.delenv("SENTITRACK_LLM_MODEL", raising=False)
    monkeypatch.delenv("SENTITRACK_LLM_BASE_URL", raising=False)

    report = evaluator.build_dry_run_report(records, Path("dataset.jsonl"), 1, False, False)

    assert report["metadata"]["run_mode"] == "DRY_RUN_ONLY"
    assert report["dry_run"]["actual_api_calls_performed"] == 0
    assert report["dry_run"]["configuration"]["ok"] is False


def test_limit_is_applied():
    records = [make_record(str(index), "향이 좋아요.", "POSITIVE") for index in range(3)]

    selected = evaluator.apply_limit(records, 2)

    assert [record["id"] for record in selected] == ["0", "1"]


def test_item_failure_does_not_stop_next_item():
    class FailingOnceAdapter:
        provider_type = "fake"
        config = LLMConfig("secret-key", "model-a", "https://llm.example/v1")

        def __init__(self):
            self.calls = 0

        def analyze(self, text):
            self.calls += 1
            if self.calls == 1:
                raise LLMSentimentError("PROVIDER_ERROR", "temporary failure")
            result = validate_llm_result(result_json(), text)
            return type(
                "Call",
                (),
                {
                    "result": result,
                    "latency_ms": 1.0,
                    "token_usage": None,
                    "cache_hit": False,
                    "model": "model-a",
                    "prompt_version": "sentiment-aspect-v1",
                    "schema_version": "llm-sentiment-schema-v1",
                    "raw_text": result_json(),
                },
            )()

    records = [
        make_record("r1", "향이 좋아요.", "POSITIVE"),
        make_record("r2", "향이 좋아요.", "POSITIVE"),
    ]

    report = evaluator.evaluate_llm_records(records, FailingOnceAdapter(), Path("dataset.jsonl"))

    assert report["overall_metrics"]["failed_predictions"] == 1
    assert report["overall_metrics"]["successful_predictions"] == 1


def test_metric_calculation():
    predictions = [
        {
            **evaluator.prediction_payload(
                make_record("p", "향이 좋아요.", "POSITIVE"),
                fake_call(validate_llm_result(result_json(overall_label="POSITIVE"), "향이 좋아요.")),
            )
        },
        {
            **evaluator.prediction_payload(
                make_record("m", REPRESENTATIVE_TEXT, "MIXED"),
                fake_call(
                    validate_llm_result(
                        result_json(
                            overall_label="MIXED",
                            aspects=[
                                {"name": "scent", "sentiment": "POSITIVE", "evidence": "향은 너무 좋지만"},
                                {"name": "longevity", "sentiment": "NEGATIVE", "evidence": "지속력이 별로예요"},
                            ],
                        ),
                        REPRESENTATIVE_TEXT,
                    )
                ),
            )
        },
    ]

    metrics = evaluator.calculate_overall_metrics(predictions)

    assert metrics["exact_match_accuracy"] == 1.0
    assert metrics["per_label"]["MIXED"]["recall"] == 1.0


def test_aspect_pair_metric_calculation():
    record = make_record(
        "r1",
        REPRESENTATIVE_TEXT,
        "MIXED",
        [
            {"name": "scent", "sentiment": "POSITIVE"},
            {"name": "longevity", "sentiment": "NEGATIVE"},
        ],
    )
    result = validate_llm_result(
        result_json(
            overall_label="MIXED",
            aspects=[
                {"name": "scent", "sentiment": "POSITIVE", "evidence": "향은 너무 좋지만"},
                {"name": "longevity", "sentiment": "NEGATIVE", "evidence": "지속력이 별로예요"},
            ],
        ),
        REPRESENTATIVE_TEXT,
    )
    prediction = evaluator.prediction_payload(record, fake_call(result))

    metrics = evaluator.calculate_aspect_metrics([prediction])

    assert metrics["pair_precision"] == 1.0
    assert metrics["pair_recall"] == 1.0
    assert metrics["evidence_substring_validation_rate"] == 1.0


def test_representative_mixed_mock_result():
    record = make_record(
        "eval-021",
        REPRESENTATIVE_TEXT,
        "MIXED",
        [
            {"name": "scent", "sentiment": "POSITIVE"},
            {"name": "longevity", "sentiment": "NEGATIVE"},
        ],
    )
    result = validate_llm_result(
        result_json(
            overall_label="MIXED",
            aspects=[
                {"name": "scent", "sentiment": "POSITIVE", "evidence": "향은 너무 좋지만"},
                {"name": "longevity", "sentiment": "NEGATIVE", "evidence": "지속력이 별로예요"},
            ],
        ),
        REPRESENTATIVE_TEXT,
    )

    prediction = evaluator.prediction_payload(record, fake_call(result))
    representative = evaluator.representative_case([prediction])

    assert representative["predicted_overall_label"] == "MIXED"
    assert representative["evidence_valid"] is True
    assert ("scent", "POSITIVE") in prediction["aspect_sentiment_matches"]
    assert ("longevity", "NEGATIVE") in prediction["aspect_sentiment_matches"]


def test_positive_is_not_converted_to_mixed():
    text = "향은 좋지만 지속력도 좋아요."
    result = validate_llm_result(
        result_json(
            overall_label="POSITIVE",
            aspects=[
                {"name": "scent", "sentiment": "POSITIVE", "evidence": "향은 좋지만"},
                {"name": "longevity", "sentiment": "POSITIVE", "evidence": "지속력도 좋아요"},
            ],
        ),
        text,
    )

    assert result.overall_label == "POSITIVE"


def fake_call(result):
    return type(
        "Call",
        (),
        {
            "result": result,
            "latency_ms": 1.0,
            "token_usage": {"total_tokens": 10},
            "cache_hit": False,
            "model": "model-a",
            "prompt_version": "sentiment-aspect-v1",
            "schema_version": "llm-sentiment-schema-v1",
            "raw_text": result_json(overall_label=result.overall_label),
        },
    )()
