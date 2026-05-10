"""Profit optimization engine.

For a given farm and time horizon, finds environment adjustments that
maximize net profit delta (predicted revenue gain minus operating cost delta).

Returns at most MAX_RECOMMENDATIONS ranked by profit_delta descending.

AI model stubs (M2_yield_predict, kamis_price_forecast) are defined as
injectable callables so real models can be plugged in without changing this file.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional
import logging

from engine.farm_tier import FarmTier
from engine.what_if_simulator import Candidate, EnvState, generate_candidates

logger = logging.getLogger(__name__)

MAX_RECOMMENDATIONS = 5

# Cost coefficients per unit change (placeholder values; loaded from 운영비용.csv in prod)
_COST_PER_UNIT: dict[str, float] = {
    "temp_internal": 800.0,    # ₩ per °C·day heating/cooling
    "humidity_int":  50.0,     # ₩ per %·day humidifier/dehumidifier
    "co2_ppm":       0.5,      # ₩ per ppm·day CO₂ enrichment
    "solar_rad":     0.0,      # natural light — no direct cost
    "ec_dsm":        200.0,    # ₩ per dS/m·day nutrient solution adjustment
}


@dataclass
class Recommendation:
    rank: int
    action_ko: str              # Korean description e.g. "내부 온도 +2°C"
    profit_delta: float         # net profit change in ₩ over horizon_days
    revenue_delta: float
    cost_delta: float
    confidence: float           # 0–1, from M2 model
    canonical_changes: dict[str, float]   # variable → new absolute value
    tier_action: str            # "checklist" | "approval_required" | "auto"


def _tier_action(tier: FarmTier) -> str:
    if tier == FarmTier.MANUAL:
        return "checklist"
    if tier == FarmTier.SEMI_AUTO:
        return "approval_required"
    return "auto"


def _compute_cost_delta(
    candidate: Candidate,
    current: EnvState,
    horizon_days: int,
) -> float:
    """Estimate operating cost change for the proposed adjustment over horizon_days."""
    total = 0.0
    for var, new_val in candidate.changes.items():
        current_val = current.values.get(var, new_val)
        delta = abs(new_val - current_val)
        cost_rate = _COST_PER_UNIT.get(var, 0.0)
        total += delta * cost_rate * horizon_days
    return total


def optimize(
    farm_id: str,
    tier: FarmTier,
    current_env: EnvState,
    horizon_days: int = 30,
    area_m2: float = 1000.0,
    yield_predict_fn: Optional[Callable[[dict], tuple[float, float]]] = None,
    price_forecast_fn: Optional[Callable[[], float]] = None,
    baseline_yield_kg_m2: float = 0.5,
) -> list[Recommendation]:
    """Find top-N environment adjustments that maximise profit.

    Args:
        farm_id:              farm identifier
        tier:                 automation tier
        current_env:          current canonical environment values
        horizon_days:         planning horizon for profit calculation
        area_m2:              greenhouse area
        yield_predict_fn:     callable(env_dict) → (yield_kg_m2, confidence_0_to_1)
                              If None, a simple stub is used.
        price_forecast_fn:    callable() → kamis_price ₩/kg
                              If None, 3000 ₩/kg is used.
        baseline_yield_kg_m2: current expected yield without any change
    """
    if yield_predict_fn is None:
        def yield_predict_fn(env: dict) -> tuple[float, float]:
            # stub: small positive response to temperature in optimal range
            temp = env.get("temp_internal", 22.0)
            bonus = max(0.0, 0.01 * (temp - 20.0))
            return baseline_yield_kg_m2 + bonus, 0.6

    if price_forecast_fn is None:
        def price_forecast_fn() -> float:
            return 3000.0  # ₩/kg placeholder

    price = price_forecast_fn()
    candidates = generate_candidates(current_env)
    results: list[Recommendation] = []

    for candidate in candidates:
        env_with_change = dict(current_env.values)
        env_with_change.update(candidate.changes)

        predicted_yield, confidence = yield_predict_fn(env_with_change)
        revenue_delta = (predicted_yield - baseline_yield_kg_m2) * price * area_m2
        cost_delta = _compute_cost_delta(candidate, current_env, horizon_days)
        profit_delta = revenue_delta - cost_delta

        results.append(Recommendation(
            rank=0,
            action_ko=candidate.description_ko,
            profit_delta=profit_delta,
            revenue_delta=revenue_delta,
            cost_delta=cost_delta,
            confidence=confidence,
            canonical_changes=candidate.changes,
            tier_action=_tier_action(tier),
        ))

    results.sort(key=lambda r: r.profit_delta, reverse=True)
    top = results[:MAX_RECOMMENDATIONS]
    for i, rec in enumerate(top, start=1):
        rec.rank = i
    logger.info(
        "[profit_optimizer] farm=%s top_profit_delta=₩%.0f",
        farm_id,
        top[0].profit_delta if top else 0,
    )
    return top
