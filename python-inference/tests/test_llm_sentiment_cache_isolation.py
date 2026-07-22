import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import evaluate_llm_sentiment as evaluator  # noqa: E402
from experiments.llm_sentiment_client import (  # noqa: E402
    JsonlLLMCache,
    LLMConfig,
    LLMSentimentError,
    OpenAICompatibleAdapter,
    analyze_with_cache,
    build_cache_key,
)
from experiments.llm_sentiment_schema import V1_SCHEMA_VERSION  # noqa: E402


PROMPT_VERSION = "sentiment-aspect-v1"
SCHEMA_VERSION = V1_SCHEMA_VERSION
ROUTER_MODEL = "openrouter/free"


def make_record(record_id, text, label="POSITIVE"):
    return {
        "id": record_id,
        "text": text,
        "overall_label": label,
        "aspects": [{"name": "scent", "sentiment": label}],
        "category": "test",
        "review_status": "PENDING_MANUAL_REVIEW",
        "source": "SYNTHETIC",
    }


def result_json(overall_label="POSITIVE", evidence="향"):
    return json.dumps(
        {
            "overall_label": overall_label,
            "aspects": [{"name": "scent", "sentiment": "POSITIVE", "evidence": evidence}],
            "confidence": None,
            "short_reason": "ok",
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


def provider_payload(content: str, resolved_model: str | None = None, total_tokens: int = 12) -> dict:
    payload = {
        "choices": [{"message": {"content": content}}],
        "usage": {"total_tokens": total_tokens},
    }
    if resolved_model is not None:
        payload["model"] = resolved_model
    return payload


def make_opener(resolved_model=None, overall_label="POSITIVE", evidence="향"):
    def opener(*_args, **_kwargs):
        return FakeResponse(provider_payload(result_json(overall_label, evidence), resolved_model=resolved_model))

    return opener


def make_adapter(opener, model=ROUTER_MODEL):
    """All adapters in this file pin prompt_version/schema_version to v1 explicitly --
    without this, OpenAICompatibleAdapter falls back to the module-default prompt/schema
    (currently v2-taxonomy), which would silently compute a different cache_key than the
    v1 key this file asserts against."""
    return OpenAICompatibleAdapter(
        LLMConfig("secret-key", model, "https://llm.example/v1"),
        opener=opener,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
    )


def refusing_opener(*_args, **_kwargs):
    raise AssertionError("must not call the provider on a cache hit")


# --- 1. --cache-path CLI wiring (dry-run, no network) -----------------------------


def test_cache_path_flag_is_reflected_in_startup_summary_and_dry_run_report(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SENTITRACK_LLM_API_KEY", raising=False)
    monkeypatch.delenv("SENTITRACK_LLM_MODEL", raising=False)
    monkeypatch.delenv("SENTITRACK_LLM_BASE_URL", raising=False)
    custom_cache_path = tmp_path / "custom_cache.jsonl"
    output_path = tmp_path / "dry_run_report.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_llm_sentiment.py",
            "--dry-run",
            "--limit",
            "1",
            "--use-cache",
            "--cache-path",
            str(custom_cache_path),
            "--output",
            str(output_path),
        ],
    )

    exit_code = evaluator.main_cli()
    printed = capsys.readouterr().out

    assert exit_code == 0
    assert str(custom_cache_path) in printed
    assert not custom_cache_path.exists()  # dry-run must never create the cache file


# --- 2. cache isolation: only the specified path is ever touched -------------------


def test_use_cache_only_touches_specified_cache_path(tmp_path, monkeypatch):
    default_cache_path = tmp_path / "default_cache.jsonl"
    custom_cache_path = tmp_path / "custom_cache.jsonl"
    default_cache_path.write_text("", encoding="utf-8")
    default_hash_before = default_cache_path.read_bytes()

    monkeypatch.setattr("experiments.llm_sentiment_client.DEFAULT_CACHE_PATH", default_cache_path)

    cache = JsonlLLMCache(custom_cache_path)
    adapter = make_adapter(make_opener(resolved_model="mistralai/mistral-7b-instruct:free"))

    analyze_with_cache("향이 좋아요.", adapter, cache=cache, use_cache=True)

    assert custom_cache_path.exists()
    assert custom_cache_path.read_text(encoding="utf-8").strip() != ""
    assert default_cache_path.read_bytes() == default_hash_before  # byte-identical, untouched


# --- 3. requested_model / resolved_model are persisted on a fresh call -------------


def test_requested_and_resolved_model_are_stored_on_cache_miss(tmp_path):
    cache = JsonlLLMCache(tmp_path / "cache.jsonl")
    adapter = make_adapter(make_opener(resolved_model="mistralai/mistral-7b-instruct:free"))

    result = analyze_with_cache("향이 좋아요.", adapter, cache=cache, use_cache=True)

    assert result.requested_model == ROUTER_MODEL
    assert result.resolved_model == "mistralai/mistral-7b-instruct:free"

    key = build_cache_key("향이 좋아요.", ROUTER_MODEL, PROMPT_VERSION, SCHEMA_VERSION)
    stored = cache.get(key)
    assert stored is not None
    assert stored["requested_model"] == ROUTER_MODEL
    assert stored["resolved_model"] == "mistralai/mistral-7b-instruct:free"


def test_requested_and_resolved_model_survive_a_cache_hit_in_a_new_session(tmp_path):
    path = tmp_path / "cache.jsonl"
    writer_cache = JsonlLLMCache(path)
    writer_adapter = make_adapter(make_opener(resolved_model="google/gemma-2-9b-it:free"))
    analyze_with_cache("향이 좋아요.", writer_adapter, cache=writer_cache, use_cache=True)

    reader_cache = JsonlLLMCache(path)  # fresh instance, simulates a new session
    reader_adapter = make_adapter(refusing_opener)
    result = analyze_with_cache("향이 좋아요.", reader_adapter, cache=reader_cache, use_cache=True)

    assert result.cache_hit is True
    assert result.requested_model == ROUTER_MODEL
    assert result.resolved_model == "google/gemma-2-9b-it:free"


# --- 4. backward compatibility with cache records written before resolved_model ---


def test_legacy_cache_record_without_resolved_model_field_loads_as_unknown(tmp_path):
    path = tmp_path / "cache.jsonl"
    key = build_cache_key("향이 좋아요.", ROUTER_MODEL, PROMPT_VERSION, SCHEMA_VERSION)
    legacy_record = {
        "cache_key": key,
        "cache_key_parts": {
            "review_text_hash": "irrelevant-for-this-test",
            "model": ROUTER_MODEL,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
        },
        "raw_text": result_json(),
        "latency_ms": 1.0,
        "token_usage": None,
        # no "resolved_model" key at all -- pre-dates this field
        # no "actual_model_if_available" key either -- oldest possible schema
    }
    path.write_text(json.dumps(legacy_record, ensure_ascii=False) + "\n", encoding="utf-8")

    cache = JsonlLLMCache(path)
    adapter = make_adapter(refusing_opener)

    result = analyze_with_cache("향이 좋아요.", adapter, cache=cache, use_cache=True)

    assert result.cache_hit is True
    assert result.resolved_model is None  # explicit unknown, not a guessed value
    assert result.requested_model == ROUTER_MODEL


def test_legacy_cache_record_with_only_actual_model_if_available_still_resolves(tmp_path):
    path = tmp_path / "cache.jsonl"
    key = build_cache_key("향이 좋아요.", ROUTER_MODEL, PROMPT_VERSION, SCHEMA_VERSION)
    legacy_record = {
        "cache_key": key,
        "cache_key_parts": {
            "review_text_hash": "irrelevant-for-this-test",
            "model": ROUTER_MODEL,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
        },
        "raw_text": result_json(),
        "latency_ms": 1.0,
        "token_usage": None,
        "actual_model_if_available": "meta-llama/llama-3-8b-instruct:free",  # pre-rename field only
    }
    path.write_text(json.dumps(legacy_record, ensure_ascii=False) + "\n", encoding="utf-8")

    cache = JsonlLLMCache(path)
    adapter = make_adapter(refusing_opener)

    result = analyze_with_cache("향이 좋아요.", adapter, cache=cache, use_cache=True)

    assert result.cache_hit is True
    assert result.resolved_model == "meta-llama/llama-3-8b-instruct:free"


# --- 5. router alias can resolve to different models across calls -----------------


def test_router_alias_records_distinct_resolved_models_per_call(tmp_path):
    cache = JsonlLLMCache(tmp_path / "cache.jsonl")
    text_a = "향이 진하게 나는 첫 번째 리뷰입니다."
    text_b = "향이 연하게 나는 두 번째 리뷰입니다."
    adapter_a = make_adapter(make_opener(resolved_model="mistralai/mistral-7b-instruct:free"))
    adapter_b = make_adapter(make_opener(resolved_model="google/gemma-2-9b-it:free"))

    result_a = analyze_with_cache(text_a, adapter_a, cache=cache, use_cache=True)
    result_b = analyze_with_cache(text_b, adapter_b, cache=cache, use_cache=True)

    assert result_a.requested_model == ROUTER_MODEL
    assert result_b.requested_model == ROUTER_MODEL
    assert result_a.resolved_model == "mistralai/mistral-7b-instruct:free"
    assert result_b.resolved_model == "google/gemma-2-9b-it:free"
    assert result_a.resolved_model != result_b.resolved_model  # same router alias, different real model


# --- 6. resolved_model distribution aggregation in report metadata ----------------


def test_resolved_model_distribution_counts_each_model_and_unknown():
    predictions = [
        {"resolved_model": "mistralai/mistral-7b-instruct:free"},
        {"resolved_model": "mistralai/mistral-7b-instruct:free"},
        {"resolved_model": "google/gemma-2-9b-it:free"},
        {"resolved_model": None},
        {},  # failure payload shape: key may be absent entirely
    ]

    distribution = evaluator.resolved_model_distribution(predictions)

    assert distribution == {
        "mistralai/mistral-7b-instruct:free": 2,
        "google/gemma-2-9b-it:free": 1,
        "unknown": 2,
    }


def test_cache_only_evaluation_reports_requested_and_resolved_model_with_zero_live_calls(tmp_path):
    """Mirrors evaluate_llm_cache_only.py's network-blocking pattern: a cache-only run
    over a router-alias model must still make zero external calls, and must report
    requested_model/resolved_model distinctly per prediction."""
    cache_path = tmp_path / "cache.jsonl"
    text_a = "향이 진하게 나는 첫 번째 리뷰입니다."
    text_b = "향이 연하게 나는 두 번째 리뷰입니다."

    seed_cache = JsonlLLMCache(cache_path)
    analyze_with_cache(
        text_a,
        make_adapter(make_opener(resolved_model="mistralai/mistral-7b-instruct:free")),
        cache=seed_cache,
        use_cache=True,
    )
    analyze_with_cache(
        text_b,
        make_adapter(make_opener(resolved_model="google/gemma-2-9b-it:free")),
        cache=seed_cache,
        use_cache=True,
    )

    def blocked_opener(*_args, **_kwargs):
        raise LLMSentimentError("NO_LIVE_CALL_SKIPPED", "must never call the provider in this test")

    cache_only_cache = JsonlLLMCache(cache_path)
    cache_only_adapter = make_adapter(blocked_opener)
    records = [make_record("r1", text_a), make_record("r2", text_b)]

    report = evaluator.evaluate_llm_records(
        records,
        cache_only_adapter,
        cache_path,
        cache=cache_only_cache,
        use_cache=True,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
    )

    assert report["metadata"]["actual_api_call_count"] == 0
    assert [row["cache_hit"] for row in report["predictions"]] == [True, True]
    assert report["predictions"][0]["requested_model"] == ROUTER_MODEL
    assert report["predictions"][1]["requested_model"] == ROUTER_MODEL
    assert report["predictions"][0]["resolved_model"] == "mistralai/mistral-7b-instruct:free"
    assert report["predictions"][1]["resolved_model"] == "google/gemma-2-9b-it:free"
    assert report["overall_metrics"]["resolved_model_distribution"] == {
        "mistralai/mistral-7b-instruct:free": 1,
        "google/gemma-2-9b-it:free": 1,
    }
