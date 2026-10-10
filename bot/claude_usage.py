from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Any

import pytz


ET = pytz.timezone("America/New_York")
USAGE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "claude_usage.csv")

USAGE_HEADERS = [
    "date_et",
    "time_et",
    "run_id",
    "report_type",
    "dry_run",
    "model",
    "prompt_token_estimate",
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "response_chars",
    "estimated_input_cost_usd",
    "estimated_cache_write_cost_usd",
    "estimated_cache_read_cost_usd",
    "estimated_output_cost_usd",
    "estimated_total_cost_usd",
]

# USD per million tokens. Cache write uses the 5-minute prompt-cache price.
MODEL_PRICING_PER_MTOK = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "cache_write_5m": 3.75,
        "cache_read": 0.30,
        "output": 15.00,
    },
    "claude-sonnet-5": {
        "input": 2.00,
        "cache_write_5m": 2.50,
        "cache_read": 0.20,
        "output": 10.00,
    },
    "claude-sonnet-5-5": {
        "input": 2.00,
        "cache_write_5m": 2.50,
        "cache_read": 0.10,
        "output": 10.00,
    },
    "claude-haiku-5-5": {
        "input": 0.10,
        "cache_write_5m": 0.125,
        "cache_read": 0.01,
        "output": 0.50,
    },
    "claude-opus-5-5": {
        "input": 4.00,
        "cache_write_5m": 5.00,
        "cache_read": 0.20,
        "output": 20.00,
    },
}


def get_claude_model(default: str = "claude-sonnet-4-6") -> str:
    return (os.getenv("CLAUDE_MODEL") or default).strip() or default


def get_claude_effort(default: str = "low") -> str:
    return (os.getenv("CLAUDE_EFFORT") or default).strip() or default


def extract_message_text(message: Any) -> str:
    parts = getattr(message, "content", None) or []
    text_parts: list[str] = []
    for part in parts:
        part_type = getattr(part, "type", "")
        text = getattr(part, "text", None)
        if (part_type in {"", "text"} or part_type is None) and text:
            text_parts.append(str(text))
    return "\n".join(text_parts).strip()


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cost(tokens: int, rate_per_mtok: float) -> float:
    return (tokens / 1_000_000) * rate_per_mtok


def _fmt_cost(value: float | None) -> str:
    return "" if value is None else f"{value:.8f}"


def estimate_usage_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int,
    cache_read_input_tokens: int,
) -> dict[str, float | None]:
    pricing = MODEL_PRICING_PER_MTOK.get(model)
    if pricing is None:
        return {
            "input": None,
            "cache_write": None,
            "cache_read": None,
            "output": None,
            "total": None,
        }

    input_cost = _cost(input_tokens, pricing["input"])
    cache_write_cost = _cost(cache_creation_input_tokens, pricing["cache_write_5m"])
    cache_read_cost = _cost(cache_read_input_tokens, pricing["cache_read"])
    output_cost = _cost(output_tokens, pricing["output"])
    return {
        "input": input_cost,
        "cache_write": cache_write_cost,
        "cache_read": cache_read_cost,
        "output": output_cost,
        "total": input_cost + cache_write_cost + cache_read_cost + output_cost,
    }


def log_claude_usage(
    *,
    report_type: str,
    model: str,
    usage: Any,
    prompt_token_estimate: int,
    response_chars: int,
    path: str = USAGE_PATH,
) -> None:
    input_tokens = _to_int(getattr(usage, "input_tokens", 0))
    output_tokens = _to_int(getattr(usage, "output_tokens", 0))
    cache_creation = _to_int(getattr(usage, "cache_creation_input_tokens", 0))
    cache_read = _to_int(getattr(usage, "cache_read_input_tokens", 0))
    costs = estimate_usage_cost(model, input_tokens, output_tokens, cache_creation, cache_read)

    now = datetime.now(ET)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    file_exists = os.path.isfile(path)
    row = {
        "date_et": now.strftime("%Y-%m-%d"),
        "time_et": now.strftime("%H:%M"),
        "run_id": os.getenv("GITHUB_RUN_ID", ""),
        "report_type": report_type,
        "dry_run": (os.getenv("DRY_RUN") or "").strip().lower() in {"1", "true", "yes"},
        "model": model,
        "prompt_token_estimate": prompt_token_estimate,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "response_chars": response_chars,
        "estimated_input_cost_usd": _fmt_cost(costs["input"]),
        "estimated_cache_write_cost_usd": _fmt_cost(costs["cache_write"]),
        "estimated_cache_read_cost_usd": _fmt_cost(costs["cache_read"]),
        "estimated_output_cost_usd": _fmt_cost(costs["output"]),
        "estimated_total_cost_usd": _fmt_cost(costs["total"]),
    }

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=USAGE_HEADERS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    if costs["total"] is not None:
        print(
            f"[claude] usage: input={input_tokens}, output={output_tokens}, "
            f"cache_write={cache_creation}, cache_read={cache_read}, "
            f"estimated_cost=${costs['total']:.6f}"
        )
    else:
        print(
            f"[claude] usage: input={input_tokens}, output={output_tokens}, "
            f"cache_write={cache_creation}, cache_read={cache_read}, estimated_cost=unknown"
        )
