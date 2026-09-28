"""OpenAI cost governor. All figures are the application's own tracked
estimates summed from ai_runs.estimated_cost_usd — never the authoritative
OpenAI account balance, which the inference API does not expose."""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select

from app.core.config import get_settings

NORMAL, SOFT, HARD = "normal", "soft_limit", "hard_limit"
BUDGET_EXHAUSTED = "OPENAI_DAILY_BUDGET_EXHAUSTED"
RESERVE_REACHED = "OPENAI_RESERVE_REACHED"


@dataclass
class BudgetState:
    spend_today_usd: float
    spend_total_usd: float
    state: str
    reason: str | None
    soft_limit_usd: float
    hard_limit_usd: float
    tracked_budget_remaining_usd: float

    def as_dict(self) -> dict:
        return {**self.__dict__, "label": "tracked estimate (not the OpenAI account balance)"}


def utc_day_start(now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def _sum_cost(since: dt.datetime | None) -> float:
    from app.core.database import AsyncSessionLocal
    from app.models.misc import AIRun

    stmt = select(func.coalesce(func.sum(AIRun.estimated_cost_usd), 0.0)).where(AIRun.provider == "openai")
    if since is not None:
        stmt = stmt.where(AIRun.created_at >= since)
    async with AsyncSessionLocal() as db:
        return float(await db.scalar(stmt) or 0.0)


async def get_openai_spend_today() -> float:
    return await _sum_cost(utc_day_start())


async def get_openai_spend_total() -> float:
    return await _sum_cost(None)


async def budget_state() -> BudgetState:
    s = get_settings()
    today, total = await get_openai_spend_today(), await get_openai_spend_total()
    remaining = s.OPENAI_STARTING_BUDGET_USD - total
    if remaining <= s.OPENAI_RESERVE_USD:
        state, reason = HARD, RESERVE_REACHED
    elif today >= s.OPENAI_DAILY_HARD_LIMIT_USD:
        state, reason = HARD, BUDGET_EXHAUSTED
    elif today >= s.OPENAI_DAILY_SOFT_LIMIT_USD:
        state, reason = SOFT, "OPENAI_DAILY_SOFT_LIMIT"
    else:
        state, reason = NORMAL, None
    return BudgetState(round(today, 6), round(total, 6), state, reason, s.OPENAI_DAILY_SOFT_LIMIT_USD,
                       s.OPENAI_DAILY_HARD_LIMIT_USD, round(remaining, 6))
