import json
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import evaluate_llm_sentiment as evaluator  # noqa: E402
from experiments.llm_sentiment_client import build_cache_key, cache_key_parts  # noqa: E402
from experiments.llm_sentiment_prompt import build_messages, get_prompt_config  # noqa: E402
from experiments.llm_sentiment_schema import (  # noqa: E402
    V1_SCHEMA_VERSION,
    V2_SCHEMA_VERSION,
    get_schema_config,
    llm_sentiment_json_schema,
    schema_version_for_prompt_version,
    validate_llm_result,
)


V1_PROMPT_VERSION = "sentiment-aspect-v1"
V2_PROMPT_VERSION = "sentiment-aspect-v2-taxonomy"


def response_json(aspects):
    return json.dumps(
        {
            "overall_label": "POSITIVE",
            "aspects": aspects,
            "confidence": None,
            "short_reason": "schema test",
        }
    )


def test_v1_prompt_version_is_selected():
    config = get_prompt_config(V1_PROMPT_VERSION)
    messages = build_messages("first scent is soft", V1_PROMPT_VERSION)

    assert config.prompt_version == V1_PROMPT_VERSION
    assert json.loads(messages[1]["content"])["prompt_version"] == V1_PROMPT_VERSION
    assert "taxonomy" not in json.loads(messages[1]["content"])


def test_v1_schema_allows_free_form_first_scent():
    result = validate_llm_result(
        response_json(
            [{"name": "first scent", "sentiment": "POSITIVE", "evidence": "first scent"}]
        ),
        "first scent is soft",
        V1_SCHEMA_VERSION,
    )

    assert result.aspects[0].name == "first scent"


def test_v1_schema_allows_overall_aspect_for_compatibility():
    result = validate_llm_result(
        response_json([{"name": "overall", "sentiment": "POSITIVE", "evidence": "overall"}]),
        "overall good",
        V1_SCHEMA_VERSION,
    )

    assert result.aspects[0].name == "overall"


def test_v2_prompt_version_is_selected():
    config = get_prompt_config(V2_PROMPT_VERSION)
    messages = build_messages("first scent is soft", V2_PROMPT_VERSION)
    payload = json.loads(messages[1]["content"])

    assert config.prompt_version == V2_PROMPT_VERSION
    assert payload["prompt_version"] == V2_PROMPT_VERSION
    assert "taxonomy" in payload


def test_v2_schema_rejects_first_scent():
    with pytest.raises(Exception, match="unsupported aspect name"):
        validate_llm_result(
            response_json(
                [{"name": "first scent", "sentiment": "POSITIVE", "evidence": "first scent"}]
            ),
            "first scent is soft",
            V2_SCHEMA_VERSION,
        )


def test_v2_schema_rejects_overall_aspect():
    with pytest.raises(Exception, match="overall"):
        validate_llm_result(
            response_json([{"name": "overall", "sentiment": "POSITIVE", "evidence": "overall"}]),
            "overall good",
            V2_SCHEMA_VERSION,
        )


def test_prompt_version_is_in_cache_key():
    text = "first scent is soft"

    v1_key = build_cache_key(text, "model", V1_PROMPT_VERSION, V1_SCHEMA_VERSION)
    v2_key = build_cache_key(text, "model", V2_PROMPT_VERSION, V1_SCHEMA_VERSION)

    assert v1_key != v2_key
    assert cache_key_parts(text, "model", V1_PROMPT_VERSION, V1_SCHEMA_VERSION)[
        "prompt_version"
    ] == V1_PROMPT_VERSION


def test_schema_version_is_in_cache_key():
    text = "first scent is soft"

    v1_key = build_cache_key(text, "model", V1_PROMPT_VERSION, V1_SCHEMA_VERSION)
    v2_key = build_cache_key(text, "model", V1_PROMPT_VERSION, V2_SCHEMA_VERSION)

    assert v1_key != v2_key
    assert cache_key_parts(text, "model", V1_PROMPT_VERSION, V2_SCHEMA_VERSION)[
        "schema_version"
    ] == V2_SCHEMA_VERSION


def test_unknown_prompt_version_returns_clear_error(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_llm_sentiment.py",
            "--prompt-version",
            "unknown-version",
            "--dry-run",
        ],
    )

    exit_code = evaluator.main_cli()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["error"] == "unsupported_version_override"
    assert "unknown-version" in output["detail"]


def test_prompt_version_selects_matching_schema_version():
    assert schema_version_for_prompt_version(V1_PROMPT_VERSION) == V1_SCHEMA_VERSION
    assert schema_version_for_prompt_version(V2_PROMPT_VERSION) == V2_SCHEMA_VERSION
    assert get_schema_config(V1_PROMPT_VERSION, V1_SCHEMA_VERSION).strict_taxonomy is False
    assert get_schema_config(V2_PROMPT_VERSION, V2_SCHEMA_VERSION).strict_taxonomy is True


def test_json_schema_matches_v1_and_v2_aspect_name_rules():
    v1_name_schema = llm_sentiment_json_schema(V1_SCHEMA_VERSION)["properties"]["aspects"][
        "items"
    ]["properties"]["name"]
    v2_name_schema = llm_sentiment_json_schema(V2_SCHEMA_VERSION)["properties"]["aspects"][
        "items"
    ]["properties"]["name"]

    assert "enum" not in v1_name_schema
    assert "enum" in v2_name_schema
    assert "overall" not in v2_name_schema["enum"]
