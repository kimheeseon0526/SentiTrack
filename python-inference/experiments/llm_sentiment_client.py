from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .llm_sentiment_prompt import PROMPT_VERSION, build_messages
from .llm_sentiment_schema import (
    SCHEMA_VERSION,
    LLMSentimentResult,
    extract_json_payload,
    get_schema_config,
    llm_sentiment_json_schema,
    schema_version_for_prompt_version,
    validate_llm_result,
)


REQUIRED_ENV_VARS = (
    "SENTITRACK_LLM_API_KEY",
    "SENTITRACK_LLM_MODEL",
    "SENTITRACK_LLM_BASE_URL",
)
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RETRIES = 2
DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "llm_sentiment_cache.jsonl"

CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
TIMEOUT = "TIMEOUT"
RATE_LIMIT = "RATE_LIMIT"
PROVIDER_ERROR = "PROVIDER_ERROR"
INVALID_JSON = "INVALID_JSON"
SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"
EVIDENCE_VALIDATION_ERROR = "EVIDENCE_VALIDATION_ERROR"
UNSUPPORTED_STRUCTURED_OUTPUT = "UNSUPPORTED_STRUCTURED_OUTPUT"


class LLMSentimentError(Exception):
    def __init__(self, error_type: str, message: str, raw_text: str | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.raw_text = raw_text


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str
    base_url: str

    @property
    def provider_host(self) -> str:
        parsed = urllib.parse.urlparse(self.base_url)
        return parsed.netloc or self.base_url


@dataclass
class LLMCallResult:
    """`model` is the requested_model -- the model id sent in the API request.
    `actual_model_if_available` is the resolved_model -- the model reported back in
    the response's own `model` field, i.e. the model that actually produced this
    response. For a request to a fixed model id these normally match. For a router
    alias like `openrouter/free`, OpenRouter picks a different underlying free model
    per request, so resolved_model can vary call-to-call even though requested_model
    never changes -- responses from different resolved models must never be pooled
    together and reported as one fixed model's performance.
    `requested_model`/`resolved_model` are read-only aliases kept alongside the
    original field names so existing call sites and persisted cache records keep
    working unchanged."""

    result: LLMSentimentResult | None
    latency_ms: float
    token_usage: dict[str, Any] | None
    cache_hit: bool
    model: str
    prompt_version: str
    schema_version: str
    raw_text: str | None = None
    raw_payload: dict[str, Any] | None = None
    provider_structured_output_used: bool = False
    provider_fallback_used: bool = False
    provider_host: str | None = None
    actual_model_if_available: str | None = None
    error: dict[str, str] | None = None

    @property
    def requested_model(self) -> str:
        return self.model

    @property
    def resolved_model(self) -> str | None:
        return self.actual_model_if_available


def load_config_from_env(environ: dict[str, str] | None = None) -> LLMConfig:
    source = environ if environ is not None else os.environ
    missing = [name for name in REQUIRED_ENV_VARS if not source.get(name)]
    if missing:
        raise LLMSentimentError(
            CONFIGURATION_ERROR,
            json.dumps(
                {
                    "error": "missing_llm_configuration",
                    "missing": missing,
                },
                ensure_ascii=False,
            ),
        )
    return LLMConfig(
        api_key=source["SENTITRACK_LLM_API_KEY"],
        model=source["SENTITRACK_LLM_MODEL"],
        base_url=source["SENTITRACK_LLM_BASE_URL"].rstrip("/"),
    )


def missing_configuration(environ: dict[str, str] | None = None) -> list[str]:
    source = environ if environ is not None else os.environ
    return [name for name in REQUIRED_ENV_VARS if not source.get(name)]


def build_cache_key(
    review_text: str,
    model: str,
    prompt_version: str | None = None,
    schema_version: str | None = None,
) -> str:
    prompt_version = prompt_version or PROMPT_VERSION
    schema_version = schema_version or SCHEMA_VERSION
    text_hash = hashlib.sha256(review_text.encode("utf-8")).hexdigest()
    raw_key = "|".join([text_hash, model, prompt_version, schema_version])
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def cache_key_parts(
    review_text: str,
    model: str,
    prompt_version: str | None = None,
    schema_version: str | None = None,
) -> dict[str, str]:
    prompt_version = prompt_version or PROMPT_VERSION
    schema_version = schema_version or SCHEMA_VERSION
    return {
        "review_text_hash": hashlib.sha256(review_text.encode("utf-8")).hexdigest(),
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
    }


EXACT_DUPLICATE = "EXACT_DUPLICATE"
RESPONSE_CONFLICT = "RESPONSE_CONFLICT"
KEY_COLLISION = "KEY_COLLISION"


def _input_hash_of(record: dict[str, Any]) -> str | None:
    parts = record.get("cache_key_parts")
    if isinstance(parts, dict):
        value = parts.get("review_text_hash")
        if isinstance(value, str):
            return value
    return None


def _resolved_model_of(record: dict[str, Any]) -> str | None:
    """Read the resolved_model (the model that actually produced a cached response)
    from a persisted cache record. Falls back to the legacy `actual_model_if_available`
    key for records written before `resolved_model` existed, so old cache entries keep
    loading without error. Returns None -- never a guessed value -- when genuinely
    unknown; callers must represent that explicitly (e.g. as "unknown") rather than
    treating it as a particular model."""
    value = record.get("resolved_model")
    if isinstance(value, str):
        return value
    legacy = record.get("actual_model_if_available")
    return legacy if isinstance(legacy, str) else None


def _requested_model_of(record: dict[str, Any]) -> str | None:
    """Read the requested_model from a persisted cache record, falling back to
    `cache_key_parts.model` (always present -- it is part of the cache key) for
    records written before the explicit `requested_model` field existed."""
    value = record.get("requested_model")
    if isinstance(value, str):
        return value
    return _cache_key_model_of(record)


def _cache_key_model_of(record: dict[str, Any]) -> str | None:
    parts = record.get("cache_key_parts")
    if isinstance(parts, dict):
        value = parts.get("model")
        if isinstance(value, str):
            return value
    return None


def _canonical_meaningful_payload(raw_text: Any) -> Any:
    """The part of an LLM response that actually matters for reproducibility: the
    overall label plus the (name, sentiment, evidence) aspect triples, order
    -independent. `confidence` and `short_reason` are deliberately excluded -- a
    self-reported score and freeform wording can differ between two calls of the
    same non-deterministic model without the underlying sentiment result actually
    disagreeing, and comparing on them would manufacture false conflicts out of
    surface noise. Falls back to the raw text itself when it isn't parseable JSON,
    since no semantic comparison is possible in that case."""
    if not isinstance(raw_text, str):
        return raw_text
    try:
        payload = extract_json_payload(raw_text)
    except ValueError:
        return raw_text
    aspects = payload.get("aspects")
    normalized_aspects: list[tuple[Any, Any, Any]] = []
    if isinstance(aspects, list):
        for aspect in aspects:
            if isinstance(aspect, dict):
                normalized_aspects.append((aspect.get("name"), aspect.get("sentiment"), aspect.get("evidence")))
    normalized_aspects.sort(key=lambda item: tuple(str(part) for part in item))
    return {"overall_label": payload.get("overall_label"), "aspects": normalized_aspects}


def _classify_duplicate(existing: dict[str, Any], record: dict[str, Any]) -> str:
    existing_hash = _input_hash_of(existing)
    later_hash = _input_hash_of(record)
    if existing_hash is not None and later_hash is not None and existing_hash != later_hash:
        return KEY_COLLISION
    existing_payload = _canonical_meaningful_payload(existing.get("raw_text"))
    later_payload = _canonical_meaningful_payload(record.get("raw_text"))
    if existing_payload == later_payload:
        return EXACT_DUPLICATE
    return RESPONSE_CONFLICT


class JsonlLLMCache:
    """Append-only JSONL cache keyed by (review text hash, model, prompt/schema version).

    Resolution policy is first-write-wins, both on disk and in memory: the first
    stored response for a given cache_key is treated as the permanent ground truth.
    Non-deterministic LLM responses re-requested under the same key must never
    silently replace an earlier result -- that was the root cause of the
    reproducibility bug where re-evaluating the same cache produced different
    metrics across sessions. `set()` therefore only writes when the key is new,
    unless `allow_overwrite=True` is passed explicitly.

    When the same cache_key appears more than once in the JSONL file (e.g. from a
    cache file written before this write-once policy existed), the duplicate lines
    are classified rather than blindly resolved:
      - EXACT_DUPLICATE: same key, same input, same meaningful response payload --
        harmless, not a real conflict.
      - RESPONSE_CONFLICT: same key, same input, different meaningful response
        payload -- genuine LLM non-determinism/drift.
      - KEY_COLLISION: same key, but the stored input hash differs -- the cache_key
        does not uniquely identify the input it was supposed to.
    """

    def __init__(self, path: Path = DEFAULT_CACHE_PATH):
        self.path = path
        self._items: dict[str, dict[str, Any]] | None = None
        self._duplicates: list[dict[str, Any]] = []
        self._response_conflicts: list[dict[str, Any]] = []
        self._key_collisions: list[dict[str, Any]] = []

    def get(self, key: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        assert self._items is not None
        return self._items.get(key)

    def set(self, key: str, value: dict[str, Any], *, allow_overwrite: bool = False) -> bool:
        """Write a cache entry. Returns False (no-op) if the key already exists and
        allow_overwrite is False -- the existing stored value is left untouched."""
        self._ensure_loaded()
        assert self._items is not None
        if key in self._items and not allow_overwrite:
            return False
        self._items[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps({"cache_key": key, **value}, ensure_ascii=False) + "\n")
        return True

    @property
    def duplicates(self) -> list[dict[str, Any]]:
        """Repeated writes for a key that agree on both input and meaningful result --
        harmless, counted separately from real conflicts."""
        self._ensure_loaded()
        return list(self._duplicates)

    @property
    def response_conflicts(self) -> list[dict[str, Any]]:
        """Same key, same input, disagreeing meaningful response -- real LLM drift."""
        self._ensure_loaded()
        return list(self._response_conflicts)

    @property
    def key_collisions(self) -> list[dict[str, Any]]:
        """Same key, but a different underlying input -- the cache_key hash failed to
        uniquely identify its input."""
        self._ensure_loaded()
        return list(self._key_collisions)

    @property
    def conflicts(self) -> list[dict[str, Any]]:
        """response_conflicts + key_collisions -- the entries that represent a real
        disagreement, as opposed to harmless exact duplicates. Each entry carries only
        cache_key / input hash / conflict_type / line_number: no review text or LLM
        response content, to avoid leaking review content into diagnostic reports."""
        self._ensure_loaded()
        tagged = [{**entry, "conflict_type": RESPONSE_CONFLICT} for entry in self._response_conflicts]
        tagged += [{**entry, "conflict_type": KEY_COLLISION} for entry in self._key_collisions]
        return tagged

    def _ensure_loaded(self) -> None:
        if self._items is not None:
            return
        self._items = {}
        self._duplicates = []
        self._response_conflicts = []
        self._key_collisions = []
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                record = json.loads(stripped)
                key = record.get("cache_key")
                if not isinstance(key, str):
                    continue
                existing = self._items.get(key)
                if existing is None:
                    self._items[key] = record
                    continue

                classification = _classify_duplicate(existing, record)
                if classification == KEY_COLLISION:
                    self._key_collisions.append(
                        {
                            "cache_key": key,
                            "input_hash_first": _input_hash_of(existing),
                            "input_hash_later": _input_hash_of(record),
                            "line_number": line_number,
                        }
                    )
                elif classification == RESPONSE_CONFLICT:
                    self._response_conflicts.append(
                        {
                            "cache_key": key,
                            "input_hash": _input_hash_of(existing),
                            "line_number": line_number,
                        }
                    )
                else:
                    self._duplicates.append(
                        {
                            "cache_key": key,
                            "input_hash": _input_hash_of(existing),
                            "line_number": line_number,
                        }
                    )
                # first occurrence always wins, regardless of classification.


class OpenAICompatibleAdapter:
    provider_type = "openai_compatible_chat_completions"

    def __init__(
        self,
        config: LLMConfig,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        opener: Any | None = None,
        prompt_version: str | None = None,
        schema_version: str | None = None,
    ):
        if max_retries > DEFAULT_MAX_RETRIES:
            raise ValueError("max_retries must be 2 or less")
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.opener = opener or urllib.request.urlopen
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        if prompt_version is not None or schema_version is not None:
            resolved_prompt_version = prompt_version or PROMPT_VERSION
            resolved_schema_version = schema_version or schema_version_for_prompt_version(
                resolved_prompt_version
            )
            get_schema_config(resolved_prompt_version, resolved_schema_version)
            self.prompt_version = resolved_prompt_version
            self.schema_version = resolved_schema_version

    def analyze(self, review_text: str) -> LLMCallResult:
        started = time.perf_counter()
        response, structured_output_used, provider_fallback_used = self._request_with_retry(review_text)
        latency_ms = (time.perf_counter() - started) * 1000
        raw_text = extract_response_text(response)
        raw_payload = None
        try:
            raw_payload = extract_json_payload(raw_text)
        except ValueError:
            raw_payload = None
        token_usage = response.get("usage") if isinstance(response.get("usage"), dict) else None
        try:
            schema_version = self.schema_version or SCHEMA_VERSION
            result = validate_llm_result(raw_text, review_text, schema_version)
        except json.JSONDecodeError as exc:
            raise LLMSentimentError(INVALID_JSON, str(exc), raw_text=raw_text) from exc
        except ValidationError as exc:
            raise LLMSentimentError(SCHEMA_VALIDATION_ERROR, str(exc), raw_text=raw_text) from exc
        except ValueError as exc:
            message = str(exc)
            error_type = (
                EVIDENCE_VALIDATION_ERROR
                if "substring of review text" in message
                else INVALID_JSON
            )
            raise LLMSentimentError(error_type, message, raw_text=raw_text) from exc

        # response.get("model") is the resolved_model: the model that actually produced
        # this response. For a fixed model id this normally equals self.config.model
        # (the requested_model). For a router alias such as "openrouter/free", OpenRouter
        # routes each request to a different underlying free model, so resolved_model can
        # differ from requested_model and can vary call-to-call -- see LLMCallResult
        # docstring. Never assume resolved_model == requested_model for router aliases.
        return LLMCallResult(
            result=result,
            latency_ms=latency_ms,
            token_usage=token_usage,
            cache_hit=False,
            model=self.config.model,
            prompt_version=self.prompt_version or PROMPT_VERSION,
            schema_version=self.schema_version or SCHEMA_VERSION,
            raw_text=raw_text,
            raw_payload=raw_payload,
            provider_structured_output_used=structured_output_used,
            provider_fallback_used=provider_fallback_used,
            provider_host=self.config.provider_host,
            actual_model_if_available=response.get("model") if isinstance(response.get("model"), str) else None,
        )

    def _request_with_retry(self, review_text: str) -> tuple[dict[str, Any], bool, bool]:
        last_error: LLMSentimentError | None = None
        fallback_used = False
        for attempt in range(self.max_retries + 1):
            try:
                try:
                    return self._request(review_text, structured_output=True), True, fallback_used
                except LLMSentimentError as exc:
                    if exc.error_type != UNSUPPORTED_STRUCTURED_OUTPUT:
                        raise
                    fallback_used = True
                    return self._request(review_text, structured_output=False), False, fallback_used
            except LLMSentimentError as exc:
                if exc.error_type not in {TIMEOUT, RATE_LIMIT, PROVIDER_ERROR}:
                    raise
                last_error = exc
                if attempt >= self.max_retries:
                    raise
                time.sleep(0.1 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _request(self, review_text: str, *, structured_output: bool) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": (
                build_messages(review_text, self.prompt_version)
                if self.prompt_version is not None
                else build_messages(review_text)
            ),
            "temperature": 0,
            "response_format": structured_response_format(self.schema_version or SCHEMA_VERSION)
            if structured_output
            else {"type": "json_object"},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except TimeoutError as exc:
            raise LLMSentimentError(TIMEOUT, "provider request timed out") from exc
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise LLMSentimentError(RATE_LIMIT, "provider rate limit") from exc
            error_body = _read_http_error_body(exc)
            if structured_output and exc.code in {400, 422} and _looks_like_response_format_error(error_body):
                raise LLMSentimentError(
                    UNSUPPORTED_STRUCTURED_OUTPUT,
                    "provider rejected json_schema response_format",
                ) from exc
            raise LLMSentimentError(PROVIDER_ERROR, f"provider HTTP error {exc.code}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", "")
            if isinstance(reason, TimeoutError):
                raise LLMSentimentError(TIMEOUT, "provider request timed out") from exc
            raise LLMSentimentError(PROVIDER_ERROR, "provider request failed") from exc

        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise LLMSentimentError(INVALID_JSON, str(exc)) from exc
        if not isinstance(parsed, dict):
            raise LLMSentimentError(PROVIDER_ERROR, "provider response must be a JSON object")
        return parsed


def analyze_with_cache(
    review_text: str,
    adapter: OpenAICompatibleAdapter,
    cache: JsonlLLMCache | None = None,
    use_cache: bool = False,
    refresh_cache: bool = False,
    prompt_version: str | None = None,
    schema_version: str | None = None,
) -> LLMCallResult:
    """`refresh_cache` forces a live call for this run (bypasses reading the cache) but
    never overwrites an existing cache entry: a key already written by an earlier
    successful call stays the permanent ground truth. This is what keeps repeated
    evaluations of the same cache deterministic even when a live provider response
    is itself non-deterministic across calls."""
    if use_cache and refresh_cache:
        raise ValueError("--use-cache and --refresh-cache cannot be used together")
    explicit_version_selection = (
        prompt_version is not None
        or schema_version is not None
        or getattr(adapter, "prompt_version", None) is not None
        or getattr(adapter, "schema_version", None) is not None
    )
    prompt_version = prompt_version or getattr(adapter, "prompt_version", None) or PROMPT_VERSION
    schema_version = schema_version or getattr(adapter, "schema_version", None) or SCHEMA_VERSION
    if explicit_version_selection:
        get_schema_config(prompt_version, schema_version)
    cache_key = build_cache_key(
        review_text,
        adapter.config.model,
        prompt_version,
        schema_version,
    )

    if use_cache and cache is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            raw_text = cached.get("raw_text", "")
            result = validate_llm_result(raw_text, review_text, schema_version)
            return LLMCallResult(
                result=result,
                latency_ms=float(cached.get("latency_ms", 0.0)),
                token_usage=cached.get("token_usage"),
                cache_hit=True,
                model=adapter.config.model,
                prompt_version=prompt_version,
                schema_version=schema_version,
                raw_text=raw_text,
                raw_payload=extract_json_payload(raw_text),
                provider_structured_output_used=bool(
                    cached.get("provider_structured_output_used", False)
                ),
                provider_fallback_used=bool(cached.get("provider_fallback_used", False)),
                provider_host=adapter.config.provider_host,
                actual_model_if_available=_resolved_model_of(cached),
            )

    result = adapter.analyze(review_text)
    if (use_cache or refresh_cache) and cache is not None and result.raw_text is not None:
        cache.set(
            cache_key,
            {
                "cache_key_parts": cache_key_parts(
                    review_text,
                    adapter.config.model,
                    prompt_version,
                    schema_version,
                ),
                "raw_text": result.raw_text,
                "latency_ms": result.latency_ms,
                "token_usage": result.token_usage,
                "provider_structured_output_used": result.provider_structured_output_used,
                "provider_fallback_used": result.provider_fallback_used,
                "actual_model_if_available": result.actual_model_if_available,
                # requested_model/resolved_model duplicate cache_key_parts.model and
                # actual_model_if_available under explicit names for easier diagnosis --
                # see LLMCallResult docstring on why these two can differ for router
                # aliases like "openrouter/free". Kept alongside the legacy fields rather
                # than replacing them so existing readers/tests are unaffected.
                "requested_model": adapter.config.model,
                "resolved_model": result.actual_model_if_available,
            },
        )
    return result


def extract_response_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMSentimentError(PROVIDER_ERROR, "provider response missing choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise LLMSentimentError(PROVIDER_ERROR, "provider response missing message content")
    return content


def structured_response_format(schema_version: str = SCHEMA_VERSION) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_version.replace("-", "_"),
            "strict": True,
            "schema": llm_sentiment_json_schema(schema_version),
        },
    }


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _looks_like_response_format_error(message: str) -> bool:
    lowered = message.lower()
    return "response_format" in lowered or "json_schema" in lowered or "structured" in lowered


def safe_error_payload(exc: LLMSentimentError) -> dict[str, str]:
    return {
        "type": exc.error_type,
        "message": _redact_known_secret_words(exc.message),
    }


def _redact_known_secret_words(message: str) -> str:
    redacted = message
    for env_name in ("SENTITRACK_LLM_API_KEY",):
        value = os.environ.get(env_name)
        if value:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted
