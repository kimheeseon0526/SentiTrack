from __future__ import annotations

import json
from dataclasses import dataclass

from .aspect_taxonomy import ASPECT_ALIASES, CANONICAL_ASPECTS


V1_PROMPT_VERSION = "sentiment-aspect-v1"
V2_PROMPT_VERSION = "sentiment-aspect-v2-taxonomy"
PROMPT_VERSION = V2_PROMPT_VERSION


V1_SYSTEM_PROMPT = """You analyze Korean perfume and product reviews.
Return JSON only. Do not include markdown, commentary, or extra text.
Separate the overall review sentiment from aspect-level sentiment.
Use only evidence phrases that appear verbatim in the review.
Do not infer consumer gender, age, taste, health status, psychology, or medical facts.
Do not invent aspects that are not explicitly supported by the review.
Keep short_reason to one or two short sentences.

Overall labels:
- POSITIVE: clear positive evaluation and no meaningful negative evaluation.
- NEGATIVE: clear negative evaluation and no meaningful positive evaluation.
- MIXED: both positive and negative evaluations exist.
- NEUTRAL: no clear positive or negative evaluation; factual, uncertain, or pending judgment.

Aspect names:
- Use concise free-form product attribute names supported by the review.
- Free-form aspect names such as "first scent" are allowed.
- Preserve explicitly stated aspect wording when it helps explain the review.

Aspect sentiments:
- POSITIVE
- NEGATIVE
- NEUTRAL
"""


V2_SYSTEM_PROMPT = """You analyze Korean perfume and product reviews.
Return JSON only. Do not include markdown, commentary, or extra text.
Separate the overall review sentiment from aspect-level sentiment.
Use only evidence phrases that appear verbatim in the review.
Do not infer consumer gender, age, taste, health status, psychology, or medical facts.
Do not invent aspects that are not explicitly supported by the review.
Keep short_reason to one or two short sentences.

Overall labels:
- POSITIVE: clear positive evaluation and no meaningful negative evaluation.
- NEGATIVE: clear negative evaluation and no meaningful positive evaluation.
- MIXED: both positive and negative evaluations exist.
- NEUTRAL: no clear positive or negative evaluation; factual, uncertain, or pending judgment.

Strict aspect taxonomy:
- Aspect name MUST be exactly one canonical value from the provided taxonomy.
- Do not output "overall" as an aspect name.
- Overall review sentiment belongs only in overall_label.
- Do not infer an aspect that is not explicitly present in the review text.
- Evidence must be a verbatim substring from the review.
- If the same canonical aspect repeats with the same sentiment, merge it when possible.
- If the same canonical aspect has both positive and negative sentiment, keep separate evidence items.
- For an ambiguous product attribute, use "other" or omit the aspect.
- Never invent free-form natural-language aspect names.

Aspect sentiments:
- POSITIVE
- NEGATIVE
- NEUTRAL

Important examples:
Review: The first scent is soft but the lasting power is weak.
JSON: {"overall_label":"MIXED","aspects":[{"name":"scent","sentiment":"POSITIVE","evidence":"first scent is soft"},{"name":"longevity","sentiment":"NEGATIVE","evidence":"lasting power is weak"}],"confidence":null,"short_reason":"The scent is positive while longevity is negative."}

Review: I only tried it once, so I cannot judge yet.
JSON: {"overall_label":"NEUTRAL","aspects":[],"confidence":null,"short_reason":"The review does not provide a clear product-attribute evaluation."}
"""


@dataclass(frozen=True)
class PromptConfig:
    prompt_version: str
    system_prompt: str
    strict_taxonomy: bool


def get_prompt_config(prompt_version: str = PROMPT_VERSION) -> PromptConfig:
    if prompt_version == V1_PROMPT_VERSION:
        return PromptConfig(
            prompt_version=V1_PROMPT_VERSION,
            system_prompt=V1_SYSTEM_PROMPT,
            strict_taxonomy=False,
        )
    if prompt_version == V2_PROMPT_VERSION:
        return PromptConfig(
            prompt_version=V2_PROMPT_VERSION,
            system_prompt=V2_SYSTEM_PROMPT,
            strict_taxonomy=True,
        )
    raise ValueError(
        "unsupported prompt version "
        f"{prompt_version!r}; supported: {', '.join(supported_prompt_versions())}"
    )


def supported_prompt_versions() -> tuple[str, ...]:
    return (V1_PROMPT_VERSION, V2_PROMPT_VERSION)


def canonical_taxonomy_payload() -> dict[str, object]:
    return {
        "canonical_aspects": list(CANONICAL_ASPECTS),
        "alias_guide": {
            canonical: [alias for alias in aliases if alias != canonical]
            for canonical, aliases in ASPECT_ALIASES.items()
        },
        "excluded_aspects": ["overall"],
        "notes": [
            "satisfaction is full-review sentiment, not a product attribute",
            "gift suitability must not be inferred as design or packaging",
            "use other only for explicit attributes outside the taxonomy",
        ],
    }


def build_user_prompt(review_text: str, prompt_version: str = PROMPT_VERSION) -> str:
    config = get_prompt_config(prompt_version)
    payload = {
        "task": "Analyze this review and return one JSON object.",
        "prompt_version": config.prompt_version,
        "output_schema": {
            "overall_label": "POSITIVE | NEGATIVE | MIXED | NEUTRAL",
            "aspects": [
                {
                    "name": (
                        "one canonical aspect only; never overall"
                        if config.strict_taxonomy
                        else "free-form aspect name explicitly supported by review"
                    ),
                    "sentiment": "POSITIVE | NEGATIVE | NEUTRAL",
                    "evidence": "verbatim substring from review",
                }
            ],
            "confidence": "number between 0 and 1, or null if unavailable",
            "short_reason": "one or two short sentences",
        },
        "review": review_text,
    }
    if config.strict_taxonomy:
        payload["taxonomy"] = canonical_taxonomy_payload()
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_messages(
    review_text: str,
    prompt_version: str = PROMPT_VERSION,
) -> list[dict[str, str]]:
    config = get_prompt_config(prompt_version)
    return [
        {"role": "system", "content": config.system_prompt},
        {"role": "user", "content": build_user_prompt(review_text, config.prompt_version)},
    ]
