"""Estimate what subagent tokens would cost at Anthropic API list prices.

Reads the JSON rows of `mr-usage --json` (a file, or `-` for stdin) and prints,
per agent group (scout, plan, exec, verify, main, other), the estimated cost at the
models that ran and the same tokens re-priced at claude-sonnet-5-5 and
claude-opus-5-5 rates.

Prices are USD per 1M tokens, as of 2026-11-12, from
https://platform.claude.com/docs/en/about-claude/pricing. The re-priced columns
keep the same token counts: a run on another model would use a different number
of tokens, so they are a comparison, not a measurement.

The pure core (price_for, row_cost, group_of, estimate, format_report,
checked_rows) does no I/O. main is the only function that reads files or streams.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import namedtuple
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, TextIO

PRICES_AS_OF = "2026-11-12"

Price = namedtuple("Price", "input cache_write_5m cache_write_1h cache_read output")

PRICES = {
    "claude-opus-5-5": Price(4, 5, 8, 0.20, 20),
    "claude-opus-5": Price(5, 6.25, 10, 0.50, 25),
    "claude-opus-4-8": Price(5, 6.25, 10, 0.50, 25),
    "claude-opus-4-7": Price(5, 6.25, 10, 0.50, 25),
    "claude-opus-4-6": Price(5, 6.25, 10, 0.50, 25),
    "claude-opus-4-5": Price(5, 6.25, 10, 0.50, 25),
    "claude-sonnet-5-5": Price(2, 2.50, 4, 0.10, 10),
    "claude-sonnet-5": Price(2, 2.50, 4, 0.20, 10),
    "claude-sonnet-4-6": Price(3, 3.75, 6, 0.30, 15),
    "claude-sonnet-4-5": Price(3, 3.75, 6, 0.30, 15),
    "claude-haiku-5-5": Price(0.10, 0.125, 0.20, 0.01, 0.50),
    "claude-haiku-4-5": Price(1, 1.25, 2, 0.10, 5),
}
HAIKU_55_KEY = "claude-haiku-5-5"
HAIKU_55_LONG = Price(0.50, 0.625, 1.00, 0.05, 2.50)
HAIKU_LONG_PROMPT_TOKENS = 100000
SONNET_REF = "claude-sonnet-5-5"
OPUS_REF = "claude-opus-5-5"

GROUPS = ("scout", "plan", "exec", "verify")
MAIN_GROUP = "main"
GROUP_ORDER = GROUPS + (MAIN_GROUP, "other")
AGENT_COUNT_KEY = "agent_count"
TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
COUNT_KEYS = TOKEN_KEYS + ("peak_prompt_tokens",)
SUM_KEYS = ("agents", "actual", "sonnet", "opus")


def price_for(model_id: str, peak_prompt_tokens: int = 0) -> Optional[Price]:
    """Price of the longest PRICES prefix that model_id starts with, or None."""
    prefixes = [prefix for prefix in PRICES if model_id.startswith(prefix)]
    if not prefixes:
        return None
    prefix = max(prefixes, key=len)
    if prefix == HAIKU_55_KEY and peak_prompt_tokens > HAIKU_LONG_PROMPT_TOKENS:
        return HAIKU_55_LONG
    return PRICES[prefix]


def row_cost(row: Mapping, price: Price, cache_ttl: str) -> float:
    """USD cost of one row's token counts at price; missing token keys count as 0."""
    cache_write = price.cache_write_1h if cache_ttl == "1h" else price.cache_write_5m
    cost = (
        row.get("input_tokens", 0) * price.input
        + row.get("cache_creation_input_tokens", 0) * cache_write
        + row.get("cache_read_input_tokens", 0) * price.cache_read
        + row.get("output_tokens", 0) * price.output
    )
    return cost / 1_000_000


def group_of(agent_type: str) -> str:
    """Tier group of an agent type: `mr:exec-haiku-high` gives `exec`, the main session gives `main`."""
    if agent_type == MAIN_GROUP:
        return MAIN_GROUP
    name = agent_type.rsplit(":", 1)[-1]
    group = name.split("-", 1)[0]
    return group if group in GROUPS else "other"


def checked_rows(data: object) -> list:
    """Return data if it is a list of objects with integer token counts, else raise ValueError."""
    if not isinstance(data, list):
        raise ValueError("the input must be a JSON list of rows")
    for index, row in enumerate(data):
        if not isinstance(row, dict):
            raise ValueError(f"row {index} is not an object")
        for key in COUNT_KEYS:
            if key in row and not _is_count(row[key]):
                raise ValueError(f"row {index}: {key} is not an integer")
        if AGENT_COUNT_KEY in row and not _is_agent_count(row[AGENT_COUNT_KEY]):
            raise ValueError(f"row {index}: {AGENT_COUNT_KEY} is not a non-negative integer")
    return data


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_agent_count(value: object) -> bool:
    return _is_count(value) and value >= 0


def _empty_sums() -> Dict[str, float]:
    return {"agents": 0, "actual": 0.0, "sonnet": 0.0, "opus": 0.0}


def _add_sums(target: Dict[str, float], sums: Mapping) -> None:
    for key in SUM_KEYS:
        target[key] += sums[key]


def is_placeholder_model(name: str) -> bool:
    """True for Claude Code placeholder names such as `<synthetic>`, which name no model."""
    return name.startswith("<") and name.endswith(">")


def real_models(names: Sequence[str]) -> List[str]:
    """Model names of a row without placeholders; placeholders are kept only when nothing else is recorded."""
    real = [name for name in names if not is_placeholder_model(name)]
    return real or list(names)


def usable_models(row: Mapping) -> list:
    """Model names a row ran on, without any placeholder such as `<synthetic>`."""
    names = [str(model) for model in (row.get("resolved_models") or [])]
    return [name for name in names if not is_placeholder_model(name)]


def _row_price(row: Mapping, models: Sequence[str]) -> Optional[Price]:
    if len(models) != 1:
        return None
    return price_for(models[0], row.get("peak_prompt_tokens", 0))


def _row_sums(row: Mapping, price: Price, cache_ttl: str) -> Dict[str, float]:
    return {
        "agents": row.get(AGENT_COUNT_KEY, 1),
        "actual": row_cost(row, price, cache_ttl),
        "sonnet": row_cost(row, PRICES[SONNET_REF], cache_ttl),
        "opus": row_cost(row, PRICES[OPUS_REF], cache_ttl),
    }


def estimate(rows: list, cache_ttl: str = "5m") -> dict:
    """Sum priced rows per group and in total; unpriced rows are counted and left out of every sum.

    Returns {"groups": {group: sums}, "total": sums, "unpriced": int,
    "unpriced_models": sorted list, "haiku_long": int}, where sums are
    {"agents", "actual", "sonnet", "opus"} and only groups with priced agents appear.
    "haiku_long" counts the agents (agent_count, default 1) priced at the long Haiku rate.
    """
    groups: Dict[str, Dict[str, float]] = {}
    total = _empty_sums()
    unpriced_models: set = set()
    unpriced = 0
    haiku_long = 0
    for row in rows:
        models = real_models([str(model) for model in (row.get("resolved_models") or [])])
        price = _row_price(row, models)
        if price is None:
            unpriced += 1
            unpriced_models.update(models)
            continue
        sums = _row_sums(row, price, cache_ttl)
        if price is HAIKU_55_LONG:
            haiku_long += sums["agents"]
        group = group_of(str(row.get("agent_type", "")))
        _add_sums(groups.setdefault(group, _empty_sums()), sums)
        _add_sums(total, sums)
    ordered = {group: groups[group] for group in GROUP_ORDER if group in groups}
    return {
        "groups": ordered,
        "total": total,
        "unpriced": unpriced,
        "unpriced_models": sorted(unpriced_models),
        "haiku_long": haiku_long,
    }


def _sum_line(name: str, sums: Mapping) -> str:
    return (
        f"{name}  {sums['agents']}  {sums['actual']:.2f}  "
        f"{sums['sonnet']:.2f}  {sums['opus']:.2f}"
    )


def format_report(result: dict, cache_ttl: str) -> str:
    """Render an estimate() result as the mr-cost report text (ends with a newline)."""
    label = "1h" if cache_ttl == "1h" else "5m"
    lines: List[str] = [
        f"mr-cost: estimate at Anthropic API list prices as of {PRICES_AS_OF}, "
        f"USD, {label} cache writes",
        "group  agents  actual  at-sonnet-5.5  at-opus-5.5",
    ]
    lines += [_sum_line(group, sums) for group, sums in result["groups"].items()]
    lines.append(_sum_line("total", result["total"]))
    if result["unpriced"]:
        models = ", ".join(result["unpriced_models"]) or "none recorded"
        lines.append(f"unpriced: {result['unpriced']} agent(s); models: {models}")
    if result["haiku_long"]:
        lines.append(
            f"haiku agents over {HAIKU_LONG_PROMPT_TOKENS // 1000}K prompt tokens, "
            f"priced at the higher rate: {result['haiku_long']}"
        )
    lines.append(
        "Same-token re-pricing: a run on another model would use a different number of tokens."
    )
    return "\n".join(lines) + "\n"


def main(
    argv: Optional[List[str]] = None,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="mr-cost",
        description="Estimate subagent cost at Anthropic API list prices from mr-usage --json rows.",
    )
    parser.add_argument("source", metavar="FILE|-", help="JSON rows from mr-usage --json, or - for stdin")
    parser.add_argument(
        "--cache-ttl", choices=("5m", "1h"), default="5m",
        help="cache write TTL to price (default: 5m)",
    )
    args = parser.parse_args(argv)
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    try:
        text = stdin.read() if args.source == "-" else Path(args.source).read_text(encoding="utf-8")
    except (OSError, ValueError):
        stderr.write(f"mr-cost: cannot read {args.source}\n")
        return 2
    try:
        rows = checked_rows(json.loads(text))
    except ValueError as error:
        stderr.write(f"mr-cost: {error}\n")
        return 2
    stdout.write(format_report(estimate(rows, args.cache_ttl), args.cache_ttl))
    return 0
