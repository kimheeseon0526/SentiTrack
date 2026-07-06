from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable


CANONICAL_ASPECTS = (
    "scent",
    "longevity",
    "price",
    "design",
    "usability",
    "packaging",
    "delivery",
    "volume",
    "physical_reaction",
    "other",
)

EXCLUDED_ASPECTS = ("overall",)

REVIEW_REQUIRED_ASPECTS = (
    "satisfaction",
    "gift suitability",
)

ASPECT_ALIASES = {
    "scent": (
        "scent",
        "fragrance",
        "first scent",
        "opening scent",
        "dry down",
        "afternote",
        "top note",
        "middle note",
        "base note",
        "향",
        "첫향",
        "잔향",
    ),
    "longevity": (
        "longevity",
        "lasting power",
        "duration",
        "persistence",
        "지속력",
    ),
    "price": (
        "price",
        "value",
        "price-performance",
        "cost",
        "가성비",
        "가격",
    ),
    "usability": (
        "usability",
        "spray",
        "atomizer",
        "sprayer",
        "분사",
        "분사력",
    ),
    "design": (
        "design",
        "bottle design",
        "appearance",
        "bottle",
        "디자인",
        "용기 디자인",
    ),
    "packaging": (
        "packaging",
        "package",
        "box",
        "포장",
    ),
    "delivery": (
        "delivery",
        "shipping",
        "배송",
    ),
    "volume": (
        "volume",
        "capacity",
        "amount",
        "용량",
    ),
    "physical_reaction": (
        "physical reaction",
        "headache",
        "irritation",
        "dizziness",
        "health",
    ),
    "other": ("other",),
}

NORMALIZATION_STATUSES = (
    "CANONICAL",
    "NORMALIZED",
    "FALLBACK_NORMALIZED",
    "OTHER",
    "REVIEW_REQUIRED",
    "EXCLUDED_OVERALL",
)


@dataclass(frozen=True)
class AspectNormalizationResult:
    raw_name: str | None
    normalized_name: str | None
    matched_alias: str | None
    normalization_applied: bool
    status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_aspect_name(name: str | None) -> AspectNormalizationResult:
    if name is None:
        return AspectNormalizationResult(
            raw_name=None,
            normalized_name=None,
            matched_alias=None,
            normalization_applied=False,
            status="OTHER",
        )

    raw_name = name
    cleaned = clean_aspect_name(name)
    if not cleaned:
        return AspectNormalizationResult(
            raw_name=raw_name,
            normalized_name=None,
            matched_alias=None,
            normalization_applied=False,
            status="OTHER",
        )

    if cleaned in EXCLUDED_ASPECTS:
        return AspectNormalizationResult(
            raw_name=raw_name,
            normalized_name=None,
            matched_alias=cleaned,
            normalization_applied=False,
            status="EXCLUDED_OVERALL",
        )

    if cleaned in REVIEW_REQUIRED_ASPECTS:
        return AspectNormalizationResult(
            raw_name=raw_name,
            normalized_name=cleaned,
            matched_alias=cleaned,
            normalization_applied=False,
            status="REVIEW_REQUIRED",
        )

    for canonical in CANONICAL_ASPECTS:
        if cleaned == canonical:
            return AspectNormalizationResult(
                raw_name=raw_name,
                normalized_name=canonical,
                matched_alias=canonical,
                normalization_applied=False,
                status="CANONICAL",
            )

    alias_index = build_alias_index()
    canonical = alias_index.get(cleaned)
    if canonical is not None:
        return AspectNormalizationResult(
            raw_name=raw_name,
            normalized_name=canonical,
            matched_alias=cleaned,
            normalization_applied=True,
            status="NORMALIZED",
        )

    return AspectNormalizationResult(
        raw_name=raw_name,
        normalized_name=cleaned,
        matched_alias=None,
        normalization_applied=False,
        status="OTHER",
    )


def validate_taxonomy_output_name(name: str | None) -> AspectNormalizationResult:
    """Validate a provider aspect name for taxonomy-constrained v2 output.

    This keeps the legacy normalization helper stable for the v1 post-processing
    experiment while exposing the stricter v2 fallback statuses requested by the
    taxonomy-constrained evaluation.
    """
    result = normalize_aspect_name(name)
    if result.status == "NORMALIZED":
        return AspectNormalizationResult(
            raw_name=result.raw_name,
            normalized_name=result.normalized_name,
            matched_alias=result.matched_alias,
            normalization_applied=True,
            status="FALLBACK_NORMALIZED",
        )
    if result.status == "OTHER" and result.normalized_name not in CANONICAL_ASPECTS:
        return AspectNormalizationResult(
            raw_name=result.raw_name,
            normalized_name=None,
            matched_alias=result.matched_alias,
            normalization_applied=False,
            status="REVIEW_REQUIRED",
        )
    return result


def is_canonical_aspect_name(name: str | None) -> bool:
    if name is None:
        return False
    return clean_aspect_name(name) in CANONICAL_ASPECTS


def clean_aspect_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def build_alias_index() -> dict[str, str]:
    alias_index: dict[str, str] = {}
    for canonical, aliases in ASPECT_ALIASES.items():
        for alias in aliases:
            cleaned = clean_aspect_name(alias)
            if cleaned != canonical:
                alias_index[cleaned] = canonical
    return alias_index


def normalize_aspects(aspects: Iterable[dict]) -> list[dict[str, object]]:
    normalized = []
    for aspect in aspects:
        result = normalize_aspect_name(aspect.get("name"))
        normalized.append(
            {
                **result.to_dict(),
                "sentiment": aspect.get("sentiment"),
                "evidence": aspect.get("evidence"),
                "metric_name": metric_name(result),
            }
        )
    return normalized


def metric_name(result: AspectNormalizationResult) -> str | None:
    if result.status == "EXCLUDED_OVERALL":
        return None
    return result.normalized_name


def metric_names(normalized_aspects: Iterable[dict[str, object]]) -> set[str]:
    return {
        str(aspect["metric_name"])
        for aspect in normalized_aspects
        if aspect.get("metric_name") is not None
    }


def metric_pairs(normalized_aspects: Iterable[dict[str, object]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for aspect in normalized_aspects:
        name = aspect.get("metric_name")
        sentiment = aspect.get("sentiment")
        if name is not None and sentiment is not None:
            pairs.add((str(name), str(sentiment)))
    return pairs


def conflicting_normalized_sentiments(
    normalized_aspects: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    sentiments_by_name: dict[str, set[str]] = {}
    raw_by_name: dict[str, list[str | None]] = {}
    for aspect in normalized_aspects:
        name = aspect.get("metric_name")
        sentiment = aspect.get("sentiment")
        if name is None or sentiment is None:
            continue
        key = str(name)
        sentiments_by_name.setdefault(key, set()).add(str(sentiment))
        raw_by_name.setdefault(key, []).append(aspect.get("raw_name"))

    conflicts = []
    for name, sentiments in sorted(sentiments_by_name.items()):
        if len(sentiments) > 1:
            conflicts.append(
                {
                    "normalized_name": name,
                    "sentiments": sorted(sentiments),
                    "raw_names": raw_by_name[name],
                    "status": "CONFLICTING_NORMALIZED_SENTIMENT",
                }
            )
    return conflicts
