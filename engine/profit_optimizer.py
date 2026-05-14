"""Profit optimization engine.

For a given farm and time horizon, finds environment adjustments that
maximize net profit delta (predicted revenue gain minus operating cost delta).

Returns at most MAX_RECOMMENDATIONS ranked by profit_delta descending.

AI model stubs (M2_yield_predict, kamis_price_forecast) are defined as
injectable callables so real models can be plugged in without changing this file.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional
import logging

from engine.farm_tier import FarmTier
from engine.what_if_simulator import Candidate, EnvState, generate_candidates

logger = logging.getLogger(__name__)

MAX_RECOMMENDATIONS = 5

_INCOME_SURVEY_PATH = Path(__file__).parent.parent / "api" / "data" / "income_survey.json"

# Season assumptions for converting annual cost → per-unit-per-day rate
_SEASON_DAYS = 150          # typical growing season length (days)
_TEMP_RANGE  = 15.0         # typical temp adjustment range (°C) used to scale rate
_HUM_RANGE   = 50.0         # typical humidity range (%)
_CO2_RANGE   = 1600.0       # typical CO2 range (ppm)
_EC_RANGE    = 2.0          # typical EC range (dS/m)

# Fallback cost rates (원 per unit-change per day, per 1000m² reference area)
_COST_PER_UNIT_FALLBACK: dict[str, float] = {
    "temp_internal": 800.0,
    "humidity_int":  50.0,
    "co2_ppm":       0.5,
    "solar_rad":     0.0,
    "ec_dsm":        200.0,
}


@lru_cache(maxsize=None)
def _load_cost_rates(crop_ko: str = "딸기", ref_area_m2: float = 1000.0) -> dict[str, float]:
    """income_survey.json에서 작목별 비용 단가 파생.

    utility(수도광열비) → temp/humidity 단가,
    fertilizer → ec 단가로 스케일링.
    파일 없으면 하드코딩 폴백 사용.
    """
    if not _INCOME_SURVEY_PATH.exists():
        logger.warning("[profit_optimizer] income_survey.json 없음 — 폴백 사용")
        return dict(_COST_PER_UNIT_FALLBACK)

    try:
        survey = json.loads(_INCOME_SURVEY_PATH.read_text(encoding="utf-8"))
        costs = survey.get(crop_ko, survey.get("딸기", {})).get("cost_per_m2", {})
    except Exception as e:
        logger.warning("[profit_optimizer] income_survey.json 로드 실패: %s", e)
        return dict(_COST_PER_UNIT_FALLBACK)

    utility    = float(costs.get("utility",    450.0))   # 원/m²/season
    fertilizer = float(costs.get("fertilizer", 180.0))   # 원/m²/season

    # 원/(unit·day) = 연간비용/m² × 면적 / (계절일수 × 조정범위)
    daily_util  = utility    * ref_area_m2 / _SEASON_DAYS
    daily_fert  = fertilizer * ref_area_m2 / _SEASON_DAYS

    rates = {
        "temp_internal": round(daily_util / _TEMP_RANGE, 1),
        "humidity_int":  round(daily_util / _HUM_RANGE,  1),
        "co2_ppm":       round(daily_util / _CO2_RANGE,  3),
        "solar_rad":     0.0,
        "ec_dsm":        round(daily_fert / _EC_RANGE,   1),
    }
    logger.info("[profit_optimizer] 비용단가 로드 (crop=%s): %s", crop_ko, rates)
    return rates


def _get_cost_rates(crop_ko: str, area_m2: float) -> dict[str, float]:
    """lru_cache는 float 인수를 수용하지 않으므로 대표 면적 버킷화."""
    bucket = round(area_m2 / 500) * 500  # 500m² 단위 반올림
    return _load_cost_rates(crop_ko, float(bucket))


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
    crop_ko: str = "딸기",
    area_m2: float = 1000.0,
) -> float:
    """Estimate operating cost change for the proposed adjustment over horizon_days."""
    cost_rates = _get_cost_rates(crop_ko, area_m2)
    total = 0.0
    for var, new_val in candidate.changes.items():
        current_val = current.values.get(var, new_val)
        delta = abs(new_val - current_val)
        cost_rate = cost_rates.get(var, 0.0)
        total += delta * cost_rate * horizon_days
    return total


def optimize(
    farm_id: str,
    tier: FarmTier,
    current_env: EnvState,
    horizon_days: int = 30,
    area_m2: float = 1000.0,
    crop_ko: str = "딸기",
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
        import datetime as _dt
        _cur_month = _dt.date.today().month

        # ① 4-Stage FourStagePipeline 우선 시도
        try:
            from models.pipeline_assembler import get_pipeline as _get_pipeline
            from api.services.model_loader import normalize_crop as _norm_crop
            _crop_norm = _norm_crop(crop_ko)
            _pipeline  = _get_pipeline(_crop_norm)

            def yield_predict_fn(env: dict) -> tuple[float, float]:
                env_current = {
                    "temp_internal_mean": env.get("temp_internal", 20.0),
                    "humidity_int_mean":  env.get("humidity_int", 70.0),
                    "co2_ppm_mean":       env.get("co2_ppm", 800.0),
                    "solar_rad_mean":     env.get("solar_rad", 100.0),
                    "soil_temp_mean":     env.get("soil_temp", 18.0),
                    "gdd_monthly":        max(0, env.get("temp_internal", 20.0) - 10.0) * 30.0,
                }
                try:
                    result = _pipeline.predict(
                        env_current=env_current,
                        month=_cur_month,
                        area_m2=area_m2,
                        temp_external=env.get("temp_external", 5.0),
                    )
                    return max(0.0, result.yield_kg_m2), result.confidence
                except Exception:
                    temp = env.get("temp_internal", 22.0)
                    return baseline_yield_kg_m2 + max(0.0, 0.008 * (temp - 20.0)), 0.45

        except Exception:
            # ② 레거시 model_loader 시도
            try:
                from api.services.model_loader import predict_revenue_per_m2 as _ml_pred
                from api.services.model_loader import normalize_crop as _norm_crop
                _crop_norm = _norm_crop(crop_ko)

                def yield_predict_fn(env: dict) -> tuple[float, float]:
                    env_feat = {
                        "temp_internal_mean":  env.get("temp_internal", 20.0),
                        "humidity_int_mean":   env.get("humidity_int", 70.0),
                        "co2_ppm_mean":        env.get("co2_ppm", 800.0),
                        "solar_rad_mean":      env.get("solar_rad", 100.0),
                        "soil_temp_mean":      env.get("soil_temp", 18.0),
                        "gdd_monthly":         max(0, env.get("temp_internal", 20.0) - 10.0) * 30.0,
                    }
                    rev_pm2 = _ml_pred(_crop_norm, env_feat, month=_cur_month)
                    if rev_pm2 is not None and rev_pm2 > 0:
                        _PRICE_PER_KG = {
                            "딸기": 9_799, "방울토마토": 3_956, "완숙토마토": 2_758,
                            "참외": 3_142, "파프리카": 4_000, "오이": 1_845,
                        }
                        price_kg = _PRICE_PER_KG.get(_crop_norm, 3_000)
                        return max(0.0, rev_pm2 / price_kg), 0.75
                    temp = env.get("temp_internal", 22.0)
                    return baseline_yield_kg_m2 + max(0.0, 0.008 * (temp - 20.0)), 0.45

            except Exception:
                # ③ 최종 폴백 — 온도 기반 단순 스텁
                def yield_predict_fn(env: dict) -> tuple[float, float]:
                    temp = env.get("temp_internal", 22.0)
                    bonus = max(0.0, 0.01 * (temp - 20.0))
                    return baseline_yield_kg_m2 + bonus, 0.6

    if price_forecast_fn is None:
        # stats_loader의 실데이터 단가 사용
        try:
            from api.data.stats_loader import get_price_krw_kg
            def price_forecast_fn() -> float:
                return get_price_krw_kg(crop_ko)
        except Exception:
            def price_forecast_fn() -> float:
                return 3_000.0

    price = price_forecast_fn()
    candidates = generate_candidates(current_env)
    results: list[Recommendation] = []

    for candidate in candidates:
        env_with_change = dict(current_env.values)
        env_with_change.update(candidate.changes)

        predicted_yield, confidence = yield_predict_fn(env_with_change)
        revenue_delta = (predicted_yield - baseline_yield_kg_m2) * price * area_m2
        cost_delta = _compute_cost_delta(candidate, current_env, horizon_days, crop_ko, area_m2)
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
