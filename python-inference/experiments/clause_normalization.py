from __future__ import annotations

from dataclasses import asdict, dataclass


RAW = "RAW"
SIMPLE_DECLARATIVE = "SIMPLE_DECLARATIVE"
HANGUL_AWARE_DECLARATIVE = "HANGUL_AWARE_DECLARATIVE"
STRATEGIES = (RAW, SIMPLE_DECLARATIVE, HANGUL_AWARE_DECLARATIVE)

MIN_NORMALIZED_LENGTH = 2
TERMINAL_PUNCTUATION = (".", "!", "?", "。", "！", "？")

SIMPLE_SUFFIX_RULES = (
    ("았지만", "았다."),
    ("었지만", "었다."),
    ("였지만", "였다."),
    ("았는데", "았다."),
    ("었는데", "었다."),
    ("였는데", "였다."),
    ("인데", "이다."),
    ("지만", "다."),
    ("은데", "다."),
    ("는데", "다."),
)

HANGUL_BASE = 0xAC00
HANGUL_END = 0xD7A3
JONGSEONG_COUNT = 28
JONGSEONG_N_INDEX = 4


@dataclass(frozen=True)
class NormalizationResult:
    original_text: str
    normalized_text: str
    strategy: str
    normalization_applied: bool
    matched_pattern: str | None
    fallback_reason: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_clause(clause: str, strategy: str) -> NormalizationResult:
    if strategy not in STRATEGIES:
        raise ValueError(f"Unsupported normalization strategy: {strategy}")

    if strategy == RAW:
        return NormalizationResult(
            original_text=clause,
            normalized_text=clause,
            strategy=strategy,
            normalization_applied=False,
            matched_pattern=None,
            fallback_reason=None,
        )

    try:
        if not clause.strip():
            return _fallback(clause, strategy, "BLANK_INPUT")

        if strategy == SIMPLE_DECLARATIVE:
            normalized, matched_pattern = normalize_simple_declarative(clause)
        else:
            normalized, matched_pattern = normalize_hangul_aware_declarative(clause)

        if normalized == clause:
            return NormalizationResult(
                original_text=clause,
                normalized_text=clause,
                strategy=strategy,
                normalization_applied=False,
                matched_pattern=None,
                fallback_reason=None,
            )

        if not is_valid_normalized_clause(normalized):
            return _fallback(clause, strategy, "INVALID_NORMALIZED_CLAUSE")

        return NormalizationResult(
            original_text=clause,
            normalized_text=normalized,
            strategy=strategy,
            normalization_applied=True,
            matched_pattern=matched_pattern,
            fallback_reason=None,
        )
    except Exception as exc:
        return _fallback(clause, strategy, f"NORMALIZATION_ERROR: {exc}")


def normalize_simple_declarative(clause: str) -> tuple[str, str | None]:
    stripped = clause.strip()
    body, _punctuation = strip_terminal_punctuation(stripped)

    for suffix, replacement in SIMPLE_SUFFIX_RULES:
        if body.endswith(suffix):
            stem = body[: -len(suffix)].strip()
            return ensure_terminal_punctuation(f"{stem}{replacement}"), suffix

    return clause, None


def normalize_hangul_aware_declarative(clause: str) -> tuple[str, str | None]:
    simple_result, simple_pattern = normalize_simple_declarative(clause)
    if simple_pattern is not None:
        return simple_result, simple_pattern

    stripped = clause.strip()
    body, _punctuation = strip_terminal_punctuation(stripped)
    if not body.endswith("데") or len(body) < 2:
        return clause, None

    previous = body[-2]
    restored = remove_jongseong_n(previous)
    if restored == previous:
        return clause, None

    normalized = f"{body[:-2]}{restored}다."
    return ensure_terminal_punctuation(normalized), "ㄴ데"


def remove_jongseong_n(syllable: str) -> str:
    if len(syllable) != 1:
        return syllable

    code = ord(syllable)
    if code < HANGUL_BASE or code > HANGUL_END:
        return syllable

    offset = code - HANGUL_BASE
    jongseong_index = offset % JONGSEONG_COUNT
    if jongseong_index != JONGSEONG_N_INDEX:
        return syllable

    # Hangul syllables are composed as initial * 588 + vowel * 28 + final consonant.
    # Subtracting the final consonant index removes jongseong ㄴ while preserving initial/vowel.
    return chr(code - JONGSEONG_N_INDEX)


def ensure_terminal_punctuation(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    if stripped.endswith(TERMINAL_PUNCTUATION):
        return stripped
    return f"{stripped}."


def is_valid_normalized_clause(text: str) -> bool:
    stripped = text.strip()
    if len(stripped.rstrip("".join(TERMINAL_PUNCTUATION))) < MIN_NORMALIZED_LENGTH:
        return False
    return bool(stripped)


def strip_terminal_punctuation(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if stripped.endswith(TERMINAL_PUNCTUATION):
        return stripped[:-1].strip(), stripped[-1]
    return stripped, ""


def _fallback(clause: str, strategy: str, reason: str) -> NormalizationResult:
    return NormalizationResult(
        original_text=clause,
        normalized_text=clause,
        strategy=strategy,
        normalization_applied=False,
        matched_pattern=None,
        fallback_reason=reason,
    )
