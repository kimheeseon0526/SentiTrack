import json
import sys
import urllib.error
from io import BytesIO
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import evaluate_llm_sentiment as evaluator  # noqa: E402
from experiments.aspect_taxonomy import validate_taxonomy_output_name  # noqa: E402
from experiments.llm_sentiment_client import (  # noqa: E402
    LLMConfig,
    OpenAICompatibleAdapter,
    build_cache_key,
)
from experiments.llm_sentiment_prompt import PROMPT_VERSION, build_messages  # noqa: E402
from experiments.llm_sentiment_schema import SCHEMA_VERSION, validate_llm_result  # noqa: E402


def response_json(aspects=None, overall_label="POSITIVE", evidence="great scent"):
    return json.dumps(
        {
            "overall_label": overall_label,
            "aspects": aspects if aspects is not None else [
                {"name": "scent", "sentiment": "POSITIVE", "evidence": evidence}
            ],
            "confidence": None,
            "short_reason": "schema test",
        }
    )


def record(aspects=None, text="great scent", label="POSITIVE"):
    return {
        "id": "r1",
        "text": text,
        "overall_label": label,
        "aspects": aspects if aspects is not None else [
            {"name": "scent", "sentiment": "POSITIVE"}
        ],
        "category": "test",
        "review_status": "PENDING_MANUAL_REVIEW",
        "source": "SYNTHETIC",
    }


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def provider_payload(content):
    return {"model": "actual-model", "choices": [{"message": {"content": content}}]}


def test_prompt_and_schema_versions_are_v2():
    assert PROMPT_VERSION == "sentiment-aspect-v2-taxonomy"
    assert SCHEMA_VERSION == "llm-sentiment-schema-v2-taxonomy"
    assert build_messages("sample")[1]["content"].find(PROMPT_VERSION) != -1


def test_canonical_aspect_is_allowed():
    result = validate_llm_result(response_json(), "great scent")
    assert result.aspects[0].name == "scent"


def test_first_scent_is_rejected_by_strict_schema():
    with pytest.raises(Exception, match="unsupported aspect name"):
        validate_llm_result(
            response_json([{"name": "first scent", "sentiment": "POSITIVE", "evidence": "first scent"}]),
            "first scent",
        )


def test_overall_aspect_is_rejected_by_strict_schema():
    with pytest.raises(Exception, match="overall"):
        validate_llm_result(
            response_json([{"name": "overall", "sentiment": "NEUTRAL", "evidence": "cannot judge"}], "NEUTRAL"),
            "cannot judge",
        )


def test_other_and_empty_aspects_are_allowed():
    assert validate_llm_result(
        response_json([{"name": "other", "sentiment": "NEUTRAL", "evidence": "texture"}]),
        "texture",
    ).aspects[0].name == "other"
    assert validate_llm_result(response_json([], "NEUTRAL"), "cannot judge").aspects == []


def test_hallucinated_evidence_is_rejected():
    with pytest.raises(ValueError, match="substring"):
        validate_llm_result(response_json(evidence="not present"), "great scent")


def test_duplicate_canonical_pair_is_rejected_but_conflicting_sentiment_is_allowed():
    aspect = {"name": "scent", "sentiment": "POSITIVE", "evidence": "scent"}
    with pytest.raises(Exception, match="duplicate"):
        validate_llm_result(response_json([aspect, aspect]), "scent")
    result = validate_llm_result(
        response_json(
            [
                {"name": "scent", "sentiment": "POSITIVE", "evidence": "scent is good"},
                {"name": "scent", "sentiment": "NEGATIVE", "evidence": "scent is sharp"},
            ],
            "MIXED",
        ),
        "scent is good but scent is sharp",
    )
    assert len(result.aspects) == 2


def test_alias_fallback_and_unknown_review_required_statuses():
    fallback = validate_taxonomy_output_name("first scent")
    unknown = validate_taxonomy_output_name("satisfaction")
    assert fallback.status == "FALLBACK_NORMALIZED"
    assert fallback.normalized_name == "scent"
    assert unknown.status == "REVIEW_REQUIRED"


def test_raw_and_normalized_aspects_are_preserved_in_prediction_payload():
    call = type(
        "Call",
        (),
        {
            "result": validate_llm_result(response_json(), "great scent"),
            "latency_ms": 1.0,
            "token_usage": None,
            "cache_hit": False,
            "model": "model",
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "raw_text": response_json(),
            "raw_payload": json.loads(response_json()),
            "provider_structured_output_used": True,
            "provider_fallback_used": False,
            "provider_host": "llm.example",
            "actual_model_if_available": "actual-model",
        },
    )()
    payload = evaluator.prediction_payload(record(), call)
    assert payload["raw_predicted_aspects"][0]["name"] == "scent"
    assert payload["normalized_aspects"][0]["name"] == "scent"
    assert payload["schema_valid"] is True


def test_schema_validation_failure_records_raw_fallback_diagnostics():
    raw = response_json([{"name": "first scent", "sentiment": "POSITIVE", "evidence": "first scent"}])
    payload = evaluator.failure_payload(
        record(text="first scent"),
        {"type": "SCHEMA_VALIDATION_ERROR", "message": "bad aspect"},
        "model",
        raw_text=raw,
    )
    assert payload["schema_valid"] is False
    assert payload["fallback_normalization_applied"] is True
    assert payload["normalized_aspects"][0]["name"] == "scent"


def test_structured_output_unsupported_falls_back_to_json_object():
    calls = []

    def opener(request, *_args, **_kwargs):
        body = json.loads(request.data.decode("utf-8"))
        calls.append(body["response_format"]["type"])
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                "https://llm.example",
                400,
                "Bad Request",
                None,
                BytesIO(b'{"error":"unsupported response_format json_schema"}'),
            )
        return FakeResponse(provider_payload(response_json()))

    adapter = OpenAICompatibleAdapter(
        LLMConfig("secret", "model", "https://llm.example/v1"),
        opener=opener,
        max_retries=0,
    )
    result = adapter.analyze("great scent")
    assert calls == ["json_schema", "json_object"]
    assert result.provider_fallback_used is True
    assert result.provider_structured_output_used is False


def test_cache_key_includes_prompt_and_schema_versions():
    text = "great scent"
    v2_key = build_cache_key(text, "model", PROMPT_VERSION, SCHEMA_VERSION)
    changed_key = build_cache_key(text, "model", "sentiment-aspect-v1", SCHEMA_VERSION)
    assert v2_key != changed_key


def test_taxonomy_metrics_and_canonical_output_rate_are_calculated():
    predictions = [
        evaluator.prediction_payload(
            record(),
            type(
                "Call",
                (),
                {
                    "result": validate_llm_result(response_json(), "great scent"),
                    "latency_ms": 1.0,
                    "token_usage": None,
                    "cache_hit": False,
                    "model": "model",
                    "prompt_version": PROMPT_VERSION,
                    "schema_version": SCHEMA_VERSION,
                    "raw_text": response_json(),
                    "raw_payload": json.loads(response_json()),
                    "provider_structured_output_used": True,
                    "provider_fallback_used": False,
                    "provider_host": "llm.example",
                    "actual_model_if_available": None,
                },
            )(),
        )
    ]
    metrics = evaluator.calculate_aspect_metrics(predictions)
    assert metrics["raw_aspect_name_f1"] == 1.0
    assert metrics["raw_pair_f1"] == 1.0
    assert metrics["canonical_output_rate"] == 1.0
    assert metrics["taxonomy_violation_count"] == 0
