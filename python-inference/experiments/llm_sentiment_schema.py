from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .aspect_taxonomy import CANONICAL_ASPECTS, EXCLUDED_ASPECTS, clean_aspect_name
from .llm_sentiment_prompt import V1_PROMPT_VERSION, V2_PROMPT_VERSION


V1_SCHEMA_VERSION = "llm-sentiment-schema-v1"
V2_SCHEMA_VERSION = "llm-sentiment-schema-v2-taxonomy"
SCHEMA_VERSION = V2_SCHEMA_VERSION
OVERALL_LABELS = ("POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL")
ASPECT_SENTIMENTS = ("POSITIVE", "NEGATIVE", "NEUTRAL")
MAX_SHORT_REASON_LENGTH = 220

OverallLabel = Literal["POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL"]
AspectSentimentLabel = Literal["POSITIVE", "NEGATIVE", "NEUTRAL"]


@dataclass(frozen=True)
class SchemaConfig:
    prompt_version: str
    schema_version: str
    strict_taxonomy: bool


def get_schema_config(
    prompt_version: str | None = None,
    schema_version: str | None = None,
) -> SchemaConfig:
    if prompt_version is None and schema_version is None:
        prompt_version = V2_PROMPT_VERSION
        schema_version = V2_SCHEMA_VERSION
    elif prompt_version is None:
        prompt_version = prompt_version_for_schema_version(schema_version)
    elif schema_version is None:
        schema_version = schema_version_for_prompt_version(prompt_version)

    if prompt_version == V1_PROMPT_VERSION and schema_version == V1_SCHEMA_VERSION:
        return SchemaConfig(
            prompt_version=V1_PROMPT_VERSION,
            schema_version=V1_SCHEMA_VERSION,
            strict_taxonomy=False,
        )
    if prompt_version == V2_PROMPT_VERSION and schema_version == V2_SCHEMA_VERSION:
        return SchemaConfig(
            prompt_version=V2_PROMPT_VERSION,
            schema_version=V2_SCHEMA_VERSION,
            strict_taxonomy=True,
        )
    raise ValueError(
        "unsupported prompt/schema version combination: "
        f"prompt_version={prompt_version!r}, schema_version={schema_version!r}"
    )


def schema_version_for_prompt_version(prompt_version: str) -> str:
    if prompt_version == V1_PROMPT_VERSION:
        return V1_SCHEMA_VERSION
    if prompt_version == V2_PROMPT_VERSION:
        return V2_SCHEMA_VERSION
    raise ValueError(
        "unsupported prompt version "
        f"{prompt_version!r}; supported: {V1_PROMPT_VERSION}, {V2_PROMPT_VERSION}"
    )


def prompt_version_for_schema_version(schema_version: str | None) -> str:
    if schema_version == V1_SCHEMA_VERSION:
        return V1_PROMPT_VERSION
    if schema_version == V2_SCHEMA_VERSION:
        return V2_PROMPT_VERSION
    raise ValueError(
        "unsupported schema version "
        f"{schema_version!r}; supported: {V1_SCHEMA_VERSION}, {V2_SCHEMA_VERSION}"
    )


def supported_schema_versions() -> tuple[str, ...]:
    return (V1_SCHEMA_VERSION, V2_SCHEMA_VERSION)


class V1AspectSentiment(BaseModel):
    name: str
    sentiment: AspectSentimentLabel
    evidence: str

    @field_validator("name")
    @classmethod
    def require_non_empty_name(cls, value: str) -> str:
        cleaned = clean_aspect_name(value)
        if not cleaned:
            raise ValueError("aspect name must be a non-empty string")
        return cleaned

    @field_validator("evidence")
    @classmethod
    def require_non_empty_evidence(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("evidence must be a non-empty string")
        return stripped


class AspectSentiment(BaseModel):
    name: str
    sentiment: AspectSentimentLabel
    evidence: str

    @field_validator("name")
    @classmethod
    def validate_canonical_name(cls, value: str) -> str:
        cleaned = clean_aspect_name(value)
        if not cleaned:
            raise ValueError("aspect name must be a non-empty string")
        if cleaned in EXCLUDED_ASPECTS:
            raise ValueError("overall is not allowed as an aspect name")
        if cleaned not in CANONICAL_ASPECTS:
            allowed = ", ".join(CANONICAL_ASPECTS)
            raise ValueError(f"unsupported aspect name {value!r}; allowed: {allowed}")
        return cleaned

    @field_validator("evidence")
    @classmethod
    def require_non_empty_evidence(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("evidence must be a non-empty string")
        return stripped


class LLMSentimentResult(BaseModel):
    overall_label: OverallLabel
    aspects: list[AspectSentiment] = Field(default_factory=list)
    confidence: float | None = None
    short_reason: str

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value

    @field_validator("short_reason")
    @classmethod
    def validate_short_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("short_reason must be a non-empty string")
        if len(stripped) > MAX_SHORT_REASON_LENGTH:
            raise ValueError(
                f"short_reason must be at most {MAX_SHORT_REASON_LENGTH} characters"
            )
        return stripped

    @model_validator(mode="after")
    def validate_duplicate_aspects(self) -> "LLMSentimentResult":
        seen: set[tuple[str, str, str]] = set()
        for aspect in self.aspects:
            key = (aspect.name, aspect.sentiment, aspect.evidence)
            if key in seen:
                raise ValueError("duplicate aspect name/sentiment/evidence is not allowed")
            seen.add(key)
        return self


class V1LLMSentimentResult(BaseModel):
    overall_label: OverallLabel
    aspects: list[V1AspectSentiment] = Field(default_factory=list)
    confidence: float | None = None
    short_reason: str

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value

    @field_validator("short_reason")
    @classmethod
    def validate_short_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("short_reason must be a non-empty string")
        if len(stripped) > MAX_SHORT_REASON_LENGTH:
            raise ValueError(
                f"short_reason must be at most {MAX_SHORT_REASON_LENGTH} characters"
            )
        return stripped

    @model_validator(mode="after")
    def validate_duplicate_aspects(self) -> "V1LLMSentimentResult":
        seen: set[tuple[str, str, str]] = set()
        for aspect in self.aspects:
            key = (aspect.name, aspect.sentiment, aspect.evidence)
            if key in seen:
                raise ValueError("duplicate aspect name/sentiment/evidence is not allowed")
            seen.add(key)
        return self


def extract_json_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty response text")

    candidates = _json_candidates(stripped)
    errors: list[str] = []
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(parsed, dict):
            raise ValueError("JSON payload must be an object")
        return parsed

    detail = "; ".join(errors[:2]) if errors else "no JSON object found"
    raise ValueError(f"invalid JSON response: {detail}")


def validate_llm_result(
    text: str,
    review_text: str,
    schema_version: str = SCHEMA_VERSION,
) -> LLMSentimentResult | V1LLMSentimentResult:
    payload = extract_json_payload(text)
    config = get_schema_config(schema_version=schema_version)
    try:
        result = (
            LLMSentimentResult.model_validate(payload)
            if config.strict_taxonomy
            else V1LLMSentimentResult.model_validate(payload)
        )
    except ValidationError:
        raise

    validate_evidence_substrings(result, review_text)
    return result


def validate_evidence_substrings(
    result: LLMSentimentResult | V1LLMSentimentResult,
    review_text: str,
) -> None:
    for aspect in result.aspects:
        if aspect.evidence not in review_text:
            raise ValueError(
                f"evidence for aspect {aspect.name!r} is not a substring of review text"
            )


def llm_sentiment_json_schema(schema_version: str = SCHEMA_VERSION) -> dict[str, Any]:
    config = get_schema_config(schema_version=schema_version)
    aspect_name_schema = (
        {"type": "string", "enum": list(CANONICAL_ASPECTS)}
        if config.strict_taxonomy
        else {"type": "string", "minLength": 1}
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["overall_label", "aspects", "confidence", "short_reason"],
        "properties": {
            "overall_label": {"type": "string", "enum": list(OVERALL_LABELS)},
            "aspects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "sentiment", "evidence"],
                    "properties": {
                        "name": aspect_name_schema,
                        "sentiment": {"type": "string", "enum": list(ASPECT_SENTIMENTS)},
                        "evidence": {"type": "string", "minLength": 1},
                    },
                },
            },
            "confidence": {
                "anyOf": [
                    {"type": "number", "minimum": 0, "maximum": 1},
                    {"type": "null"},
                ]
            },
            "short_reason": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_SHORT_REASON_LENGTH,
            },
        },
    }


def _json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL):
        candidates.append(match.group(1).strip())

    candidates.append(text)

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and first < last:
        candidates.append(text[first : last + 1])

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped
