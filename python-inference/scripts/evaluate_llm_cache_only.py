"""Evaluate the LLM structured sentiment pipeline strictly from the existing JSONL cache,
without ever attempting a live network call.

This environment has no SENTITRACK_LLM_API_KEY/MODEL/BASE_URL configured (confirmed absent at
process/user/machine env scope), so a normal --use-cache run would still try a real HTTP call
for any cache miss. This script injects a stub `opener` into OpenAICompatibleAdapter that raises
a local, non-network error for any attempted request -- cache hits are evaluated for real
(schema validation etc.) exactly as evaluate_llm_sentiment.py does, cache misses are cleanly
recorded as NO_LIVE_CALL_SKIPPED failures instead of ever touching the network.

Usage: python scripts/evaluate_llm_cache_only.py --dataset <path> --output <path>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from evaluate_llm_sentiment import evaluate_llm_records, format_console_summary  # noqa: E402
from evaluate_sentiment_baseline import DEFAULT_DATASET_PATH, load_dataset  # noqa: E402
from experiments.llm_sentiment_client import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    JsonlLLMCache,
    LLMConfig,
    LLMSentimentError,
    OpenAICompatibleAdapter,
)
from experiments.llm_sentiment_prompt import PROMPT_VERSION  # noqa: E402
from experiments.llm_sentiment_schema import schema_version_for_prompt_version  # noqa: E402

NO_LIVE_CALL_ERROR_TYPE = "NO_LIVE_CALL_SKIPPED"
PLACEHOLDER_MODEL = "openrouter/free"
PLACEHOLDER_BASE_URL = "https://openrouter.ai/api/v1"


def _blocked_opener(request, timeout=None):
    raise LLMSentimentError(
        NO_LIVE_CALL_ERROR_TYPE,
        "offline cache-only evaluation: no LLM credentials configured in this environment, live call skipped",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate LLM structured sentiment from cache only, no live calls.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompt-version", default=PROMPT_VERSION)
    parser.add_argument("--model", default=PLACEHOLDER_MODEL)
    return parser.parse_args()


def main_run() -> int:
    args = parse_args()
    prompt_version = args.prompt_version
    schema_version = schema_version_for_prompt_version(prompt_version)

    records = load_dataset(args.dataset)
    config = LLMConfig(api_key="unused-cache-only-run", model=args.model, base_url=PLACEHOLDER_BASE_URL)
    adapter = OpenAICompatibleAdapter(
        config,
        opener=_blocked_opener,
        prompt_version=prompt_version,
        schema_version=schema_version,
    )
    cache = JsonlLLMCache(DEFAULT_CACHE_PATH)

    report = evaluate_llm_records(
        records,
        adapter,
        args.dataset,
        cache=cache,
        use_cache=True,
        prompt_version=prompt_version,
        schema_version=schema_version,
    )
    report["metadata"]["run_mode"] = "CACHE_ONLY_NO_LIVE_CALLS"
    report["metadata"]["note"] = (
        "No live LLM API calls were made in this run. Cache hits were validated for real; "
        "cache misses are recorded as NO_LIVE_CALL_SKIPPED failures, not RATE_LIMIT/PROVIDER_ERROR."
    )
    skipped_count = sum(
        1 for row in report["predictions"] if (row.get("error") or {}).get("type") == NO_LIVE_CALL_ERROR_TYPE
    )
    report["metadata"]["no_live_call_skipped_count"] = skipped_count
    report["metadata"]["cache_hit_evaluated_count"] = len(records) - skipped_count

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(format_console_summary(report, args.output))
    print(f"- no_live_call_skipped_count: {skipped_count}")
    print(f"- cache_hit_evaluated_count: {len(records) - skipped_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_run())
