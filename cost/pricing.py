"""Exact, dated OpenRouter pricing and currency conversion assumptions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

TOKENS_PER_MILLION = Decimal("1000000")
USD_QUANTUM = Decimal("0.00000001")
KES_QUANTUM = Decimal("0.0001")
PRICING_VERIFIED_ON = "2026-07-29"
EXCHANGE_RATE = Decimal("129.5000")
EXCHANGE_RATE_DATE = "2026-07-29"
EXCHANGE_RATE_SOURCE = "https://www.centralbank.go.ke/forex/"


@dataclass(frozen=True)
class ModelPricing:
    """List prices per million text tokens."""

    input_usd: Decimal
    cached_input_usd: Decimal
    output_usd: Decimal
    source_url: str


@dataclass(frozen=True)
class CostBreakdown:
    """Exact request-level token cost attribution."""

    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    input_cost_usd: Decimal
    cached_input_cost_usd: Decimal
    output_cost_usd: Decimal
    total_cost_usd: Decimal


MODEL_PRICING = {
    "openai/gpt-4o-mini": ModelPricing(
        Decimal("0.15"),
        Decimal("0.075"),
        Decimal("0.60"),
        "https://openrouter.ai/openai/gpt-4o-mini",
    ),
    "openai/gpt-4o": ModelPricing(
        Decimal("2.50"),
        Decimal("1.25"),
        Decimal("10.00"),
        "https://openrouter.ai/openai/gpt-4o",
    ),
}


def _validate_tokens(**counts: int) -> None:
    for name, value in counts.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer.")


def _token_cost(tokens: int, rate: Decimal) -> Decimal:
    return Decimal(tokens) * rate / TOKENS_PER_MILLION


def calculate_breakdown(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> CostBreakdown:
    """Price uncached input, cached input, and output independently."""

    if model not in MODEL_PRICING:
        raise ValueError(f"Model {model!r} has no verified pricing.")
    _validate_tokens(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
    )
    if cached_input_tokens > input_tokens:
        raise ValueError("cached_input_tokens cannot exceed input_tokens.")
    pricing = MODEL_PRICING[model]
    uncached = input_tokens - cached_input_tokens
    input_cost = _token_cost(uncached, pricing.input_usd)
    cached_cost = _token_cost(cached_input_tokens, pricing.cached_input_usd)
    output_cost = _token_cost(output_tokens, pricing.output_usd)
    total = (input_cost + cached_cost + output_cost).quantize(
        USD_QUANTUM,
        ROUND_HALF_UP,
    )
    return CostBreakdown(
        model,
        input_tokens,
        cached_input_tokens,
        output_tokens,
        input_cost,
        cached_cost,
        output_cost,
        total,
    )


def usd_to_kes(
    cost_usd: Decimal,
    exchange_rate: Decimal = EXCHANGE_RATE,
    quantum: Decimal = KES_QUANTUM,
) -> Decimal:
    """Convert non-negative USD using the explicit dated planning rate."""

    if cost_usd < 0 or exchange_rate <= 0 or quantum <= 0:
        raise ValueError("Cost, exchange rate, and quantum must be valid.")
    return (cost_usd * exchange_rate).quantize(quantum, ROUND_HALF_UP)
