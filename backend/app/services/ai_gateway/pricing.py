"""Central model price registry (USD per 1M tokens, standard short-context).

Source: https://developers.openai.com/api/docs/pricing, fetched 2026-09-27.
Update here only — nothing else in the codebase contains a price.
Groq (free tier on this project) and local Ollama are tracked at $0.
"""

MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-6-luna": {"input_per_million": 0.10, "cached_input_per_million": 0.01, "output_per_million": 0.50},
    "gpt-6-sol": {"input_per_million": 2.00, "cached_input_per_million": 0.20, "output_per_million": 10.00},
    "gpt-5.6-luna": {"input_per_million": 0.20, "cached_input_per_million": 0.02, "output_per_million": 1.20},
    "gpt-5.6-sol": {"input_per_million": 4.00, "cached_input_per_million": 0.40, "output_per_million": 20.00},
}
PRICING_SOURCE = "developers.openai.com/api/docs/pricing (standard, short context), fetched 2026-09-27"


def estimate_cost_usd(model: str, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> float:
    p = MODEL_PRICING.get(model)
    if p is None:
        return 0.0
    uncached = max(0, input_tokens - cached_input_tokens)
    return round(
        (uncached * p["input_per_million"] + cached_input_tokens * p["cached_input_per_million"]
         + output_tokens * p["output_per_million"]) / 1_000_000,
        8,
    )
