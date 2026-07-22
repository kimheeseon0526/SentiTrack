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
    cache_key_parts,
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


def write_raw_cache_line(
    path,
    cache_key: str,
    raw_text: str,
    review_text: str,
    model: str = "model-a",
) -> None:
    """Append a JSONL line directly, bypassing `.set()`, to simulate a pre-existing cache
    file entry (including drifted/collided entries that write-once would never itself
    produce going forward)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "cache_key": cache_key,
        "cache_key_parts": cache_key_parts(review_text, model),
        "raw_text": raw_text,
        "latency_ms": 1.0,
        "token_usage": None,
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


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


def test_cache_set_does_not_overwrite_existing_entry_by_default(tmp_path):
    cache = JsonlLLMCache(tmp_path / "cache.jsonl")
    key = build_cache_key("향이 좋아요.", "model-a")
    first_value = {"raw_text": result_json(overall_label="POSITIVE"), "latency_ms": 1.0, "token_usage": None}
    second_value = {"raw_text": result_json(overall_label="NEGATIVE"), "latency_ms": 2.0, "token_usage": None}

    written_first = cache.set(key, first_value)
    written_second = cache.set(key, second_value)

    assert written_first is True
    assert written_second is False
    assert cache.get(key)["raw_text"] == first_value["raw_text"]


def test_cache_set_overwrites_when_explicitly_allowed(tmp_path):
    cache = JsonlLLMCache(tmp_path / "cache.jsonl")
    key = build_cache_key("향이 좋아요.", "model-a")
    first_value = {"raw_text": result_json(overall_label="POSITIVE"), "latency_ms": 1.0, "token_usage": None}
    second_value = {"raw_text": result_json(overall_label="NEGATIVE"), "latency_ms": 2.0, "token_usage": None}

    cache.set(key, first_value)
    written_second = cache.set(key, second_value, allow_overwrite=True)

    assert written_second is True
    assert cache.get(key)["raw_text"] == second_value["raw_text"]


def test_explicit_overwrite_is_visible_as_response_conflict_on_reload(tmp_path):
    """`allow_overwrite=True` is a low-level escape hatch (not wired to any CLI flag) for
    deliberately correcting a cache entry. Even when used, a fresh reload must still
    resolve deterministically (first entry wins) and must surface the discrepancy via
    `.conflicts` rather than silently accepting whichever value happened to load last.
    No review text or raw LLM response content should appear in the conflict entry."""
    path = tmp_path / "cache.jsonl"
    key = build_cache_key("향이 좋아요.", "model-a")
    first_value = {"raw_text": result_json(overall_label="POSITIVE"), "latency_ms": 1.0, "token_usage": None}
    second_value = {"raw_text": result_json(overall_label="NEGATIVE"), "latency_ms": 2.0, "token_usage": None}

    writer = JsonlLLMCache(path)
    writer.set(key, first_value)
    writer.set(key, second_value, allow_overwrite=True)

    reader = JsonlLLMCache(path)
    assert reader.get(key)["raw_text"] == first_value["raw_text"]
    assert reader.duplicates == []
    assert reader.key_collisions == []
    conflicts = reader.conflicts
    assert len(conflicts) == 1
    entry = conflicts[0]
    assert entry["cache_key"] == key
    assert entry["conflict_type"] == "RESPONSE_CONFLICT"
    assert "raw_text" not in entry
    assert "first_raw_text" not in entry
    assert "later_raw_text" not in entry
    assert result_json(overall_label="POSITIVE") not in json.dumps(entry, ensure_ascii=False)
    assert result_json(overall_label="NEGATIVE") not in json.dumps(entry, ensure_ascii=False)


def test_same_key_same_text_same_payload_is_exact_duplicate(tmp_path):
    path = tmp_path / "cache.jsonl"
    text = "향이 좋아요."
    key = build_cache_key(text, "model-a")
    same_raw_text = result_json(overall_label="POSITIVE")

    write_raw_cache_line(path, key, same_raw_text, text)
    write_raw_cache_line(path, key, same_raw_text, text)

    cache = JsonlLLMCache(path)
    assert len(cache.duplicates) == 1
    assert cache.response_conflicts == []
    assert cache.key_collisions == []
    assert cache.conflicts == []
    assert cache.get(key)["raw_text"] == same_raw_text


def test_same_key_same_text_different_payload_is_response_conflict(tmp_path):
    path = tmp_path / "cache.jsonl"
    text = "향이 좋아요."
    key = build_cache_key(text, "model-a")

    write_raw_cache_line(path, key, result_json(overall_label="POSITIVE"), text)
    write_raw_cache_line(path, key, result_json(overall_label="NEGATIVE"), text)

    cache = JsonlLLMCache(path)
    assert cache.duplicates == []
    assert len(cache.response_conflicts) == 1
    assert cache.key_collisions == []
    assert cache.response_conflicts[0]["cache_key"] == key
    # first value is retained despite the later, disagreeing response
    assert cache.get(key)["raw_text"] == result_json(overall_label="POSITIVE")


def test_same_key_different_text_is_key_collision(tmp_path):
    path = tmp_path / "cache.jsonl"
    key = build_cache_key("향이 좋아요.", "model-a")  # shared key, simulating a hash collision

    write_raw_cache_line(path, key, result_json(overall_label="POSITIVE"), "향이 좋아요.")
    write_raw_cache_line(path, key, result_json(overall_label="NEGATIVE"), "완전히 다른 문장입니다.")

    cache = JsonlLLMCache(path)
    assert cache.duplicates == []
    assert cache.response_conflicts == []
    assert len(cache.key_collisions) == 1
    collision = cache.key_collisions[0]
    assert collision["cache_key"] == key
    assert collision["input_hash_first"] != collision["input_hash_later"]
    assert "raw_text" not in collision
    assert "향" not in json.dumps(collision, ensure_ascii=False)
    # first value is retained despite the later, unrelated response
    assert cache.get(key)["raw_text"] == result_json(overall_label="POSITIVE")


def test_conflicts_property_combines_response_conflicts_and_key_collisions_only(tmp_path):
    path = tmp_path / "cache.jsonl"
    dup_key = build_cache_key("dup", "model-a")
    conflict_key = build_cache_key("conflict", "model-a")
    collision_key = build_cache_key("collision", "model-a")

    write_raw_cache_line(path, dup_key, result_json(overall_label="POSITIVE"), "dup")
    write_raw_cache_line(path, dup_key, result_json(overall_label="POSITIVE"), "dup")

    write_raw_cache_line(path, conflict_key, result_json(overall_label="POSITIVE"), "conflict")
    write_raw_cache_line(path, conflict_key, result_json(overall_label="NEGATIVE"), "conflict")

    write_raw_cache_line(path, collision_key, result_json(overall_label="POSITIVE"), "collision-a")
    write_raw_cache_line(path, collision_key, result_json(overall_label="NEGATIVE"), "collision-b")

    cache = JsonlLLMCache(path)
    assert len(cache.duplicates) == 1
    assert len(cache.response_conflicts) == 1
    assert len(cache.key_collisions) == 1
    conflicts = cache.conflicts
    assert len(conflicts) == 2
    conflict_types = {entry["conflict_type"] for entry in conflicts}
    assert conflict_types == {"RESPONSE_CONFLICT", "KEY_COLLISION"}


def test_duplicates_and_conflicts_never_trigger_a_live_call(tmp_path):
    """Even when the cache file already contains duplicate/conflicting entries, a
    cache-only evaluation run (blocked opener, same shape as evaluate_llm_cache_only.py)
    must make zero real network calls -- duplicates/conflicts are a read-time
    classification concern only, never a reason to fall through to a live request."""
    path = tmp_path / "cache.jsonl"
    duplicate_text = "향이 좋아요."
    conflict_text = "향은 너무 좋지만 지속력이 별로예요."

    duplicate_key = build_cache_key(duplicate_text, "model-a")
    write_raw_cache_line(path, duplicate_key, result_json(overall_label="POSITIVE"), duplicate_text)
    write_raw_cache_line(path, duplicate_key, result_json(overall_label="POSITIVE"), duplicate_text)

    conflict_key = build_cache_key(conflict_text, "model-a")
    write_raw_cache_line(path, conflict_key, result_json(overall_label="MIXED"), conflict_text)
    write_raw_cache_line(path, conflict_key, result_json(overall_label="POSITIVE"), conflict_text)

    cache = JsonlLLMCache(path)

    def blocked_opener(*_args, **_kwargs):
        raise LLMSentimentError("NO_LIVE_CALL_SKIPPED", "live call should never happen in this test")

    adapter = OpenAICompatibleAdapter(
        LLMConfig("secret-key", "model-a", "https://llm.example/v1"),
        opener=blocked_opener,
    )
    records = [
        make_record("r1", duplicate_text, "POSITIVE"),
        make_record("r2", conflict_text, "MIXED"),
    ]

    report = evaluator.evaluate_llm_records(
        records,
        adapter,
        path,
        cache=cache,
        use_cache=True,
    )

    assert report["metadata"]["actual_api_call_count"] == 0
    assert all(row["error"] is None for row in report["predictions"])
    assert [row["cache_hit"] for row in report["predictions"]] == [True, True]
    assert report["predictions"][0]["predicted_overall_label"] == "POSITIVE"
    assert report["predictions"][1]["predicted_overall_label"] == "MIXED"

    cache_usage = report["metadata"]["cache_usage"]
    assert cache_usage["cache_duplicate_count"] == 1
    assert cache_usage["cache_response_conflict_count"] == 1
    assert cache_usage["cache_key_collision_count"] == 0
    assert cache_usage["cache_conflict_count"] == 1
    assert len(cache_usage["cache_conflicts"]) == 1
    assert cache_usage["cache_conflicts"][0]["conflict_type"] == "RESPONSE_CONFLICT"


def test_second_session_reuses_cached_value_without_recalling_provider(tmp_path):
    """Simulates two separate sessions (fresh JsonlLLMCache instance each, same file) --
    the second session must reuse the first session's stored answer, never re-call the
    provider, even though a fresh provider call would return a different response."""
    path = tmp_path / "cache.jsonl"
    text = "향이 좋아요."

    session_one_cache = JsonlLLMCache(path)
    session_one_adapter = OpenAICompatibleAdapter(
        LLMConfig("secret-key", "model-a", "https://llm.example/v1"),
        opener=lambda *_a, **_k: FakeResponse(provider_payload(result_json(overall_label="POSITIVE"))),
    )
    first_result = analyze_with_cache(text, session_one_adapter, cache=session_one_cache, use_cache=True)

    session_two_cache = JsonlLLMCache(path)
    session_two_adapter = OpenAICompatibleAdapter(
        LLMConfig("secret-key", "model-a", "https://llm.example/v1"),
        opener=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("provider must not be called on cache hit")),
    )
    second_result = analyze_with_cache(text, session_two_adapter, cache=session_two_cache, use_cache=True)

    assert first_result.result.overall_label == "POSITIVE"
    assert second_result.cache_hit is True
    assert second_result.result.overall_label == "POSITIVE"


def test_refresh_cache_does_not_overwrite_existing_ground_truth(tmp_path):
    """Reproduces the documented reproducibility bug: a later --refresh-cache run for a
    text that overlaps with an earlier cached evaluation must not silently replace the
    stored answer, even though the fresh provider call itself succeeds and returns a
    different result for this run's own report."""
    path = tmp_path / "cache.jsonl"
    text = "향은 너무 좋지만 지속력이 별로예요."

    first_cache = JsonlLLMCache(path)
    first_adapter = OpenAICompatibleAdapter(
        LLMConfig("secret-key", "model-a", "https://llm.example/v1"),
        opener=lambda *_a, **_k: FakeResponse(provider_payload(result_json(overall_label="MIXED"))),
    )
    analyze_with_cache(text, first_adapter, cache=first_cache, use_cache=True)

    refresh_cache_instance = JsonlLLMCache(path)
    refresh_adapter = OpenAICompatibleAdapter(
        LLMConfig("secret-key", "model-a", "https://llm.example/v1"),
        opener=lambda *_a, **_k: FakeResponse(provider_payload(result_json(overall_label="POSITIVE"))),
    )
    refresh_result = analyze_with_cache(text, refresh_adapter, cache=refresh_cache_instance, refresh_cache=True)

    assert refresh_result.result.overall_label == "POSITIVE"

    reread_cache = JsonlLLMCache(path)
    key = build_cache_key(text, "model-a")
    assert reread_cache.get(key)["raw_text"] == result_json(overall_label="MIXED")
    assert reread_cache.conflicts == []


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
