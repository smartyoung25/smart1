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

_SEASON_DAYS = 150
_TEMP_RANGE  = 15.0
_HUM_RANGE   = 50.0
_CO2_RANGE   = 1600.0
_EC_RANGE    = 2.0

_COST_PER_UNIT_FALLBACK: dict[str, float] = {
    "temp_internal": 800.0,
    "humidity_int":  50.0,
    "co2_ppm":       0.5,
    "solar_rad":     0.0,
    "ec_dsm":        200.0,
}


@lru_cache(maxsize=None)
def _load_cost_rates(crop_ko: str = "딸기", ref_area_m2: float = 1000.0) -> dict[str, float]:
    if not _INCOME_SURVEY_PATH.exists():
        logger.warning("[profit_optimizer] income_survey.json not found -- using fallback")
        return dict(_COST_PER_UNIT_FALLBACK)
    try:
        survey = json.loads(_INCOME_SURVEY_PATH.read_text(encoding="utf-8"))
        default_crop = "딸기"
        costs = survey.get(crop_ko, survey.get(default_crop, {})).get("cost_per_m2", {})
    except Exception as e:
        logger.warning("[profit_optimizer] income_survey.json load failed: %s", e)
        return dict(_COST_PER_UNIT_FALLBACK)

    utility    = float(costs.get("utility",    450.0))
    fertilizer = float(costs.get("fertilizer", 180.0))
    daily_util = utility    * ref_area_m2 / _SEASON_DAYS
    daily_fert = fertilizer * ref_area_m2 / _SEASON_DAYS
    rates = {
        "temp_internal": round(daily_util / _TEMP_RANGE, 1),
        "humidity_int":  round(daily_util / _HUM_RANGE,  1),
        "co2_ppm":       round(daily_util / _CO2_RANGE,  3),
        "solar_rad":     0.0,
        "ec_dsm":        round(daily_fert / _EC_RANGE,   1),
    }
    logger.info("[profit_optimizer] cost rates loaded (crop=%s): %s", crop_ko, rates)
    return rates


def _get_cost_rates(crop_ko: str, area_m2: float) -> dict[str, float]:
    bucket = round(area_m2 / 500) * 500
    return _load_cost_rates(crop_ko, float(bucket))


@dataclass
class Recommendation:
    rank: int
    action_ko: str
    profit_delta: float
    revenue_delta: float
    cost_delta: float
    confidence: float
    canonical_changes: dict[str, float]
    tier_action: str


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
    cost_rates = _get_cost_rates(crop_ko, area_m2)
    total = 0.0
    for var, new_val in candidate.changes.items():
        current_val = current.values.get(var, new_val)
        delta = abs(new_val - current_val)
        cost_rate = cost_rates.get(var, 0.0)
        total += delta * cost_rate * horizon_days
    return total


def _check_sensitivity(
    yield_fn: Callable[[dict], tuple[float, float]],
    baseline_env: dict,
    candidates: list[Candidate],
    threshold: float = 1e-4,
) -> bool:
    """Return True if yield_fn is sensitive to env changes.

    Samples up to 5 candidates and checks whether any predicted yield
    differs from the baseline by more than `threshold` kg/m2.
    Detects flat (non-discriminating) models.
    """
    try:
        base_yield, _ = yield_fn(baseline_env)
        sample = candidates[:5]
        for cand in sample:
            env_test = dict(baseline_env)
            env_test.update(cand.changes)
            pred_yield, _ = yield_fn(env_test)
            if abs(pred_yield - base_yield) > threshold:
                return True
        return False
    except Exception:
        return True   # assume sensitive if we can't check


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
    """Find top-N environment adjustments that maximise profit."""
    if yield_predict_fn is None:
        import datetime as _dt
        _cur_month = _dt.date.today().month

        # Block 0: M2 trained model (highest priority)
        try:
            from models.m2_yield import predict_yield as _m2_predict

            # Crop-specific agronomic constants (used by v3 features)
            _BASE_TEMP = {"strawberry": 5.0, "cherry_tomato": 10.0, "tomato": 10.0,
                          "melon": 10.0, "paprika": 10.0}
            _OPT_MAX   = {"strawberry": 25.0, "cherry_tomato": 30.0, "tomato": 30.0,
                          "melon": 30.0, "paprika": 28.0}
            _CROP_EN   = {"strawberry": "strawberry", "cherry_tomato": "cherry_tomato",
                          "tomato": "tomato", "melon": "melon", "paprika": "paprika",
                          "딸기": "strawberry", "방울토마토": "cherry_tomato",
                          "완숙토마토": "tomato", "참외": "melon", "파프리카": "paprika"}
            _crop_en_key = _CROP_EN.get(crop_ko, "tomato")
            _base_t  = _BASE_TEMP.get(_crop_en_key, 10.0)
            _opt_max = _OPT_MAX.get(_crop_en_key, 30.0)
            _SEASON_DAYS_EST = 180.0

            def _env_to_season(env: dict) -> dict:
                t    = env.get("temp_internal", 20.0)
                sol  = env.get("solar_rad", 150.0)
                co2  = env.get("co2_ppm", 500.0)
                hum  = env.get("humidity_int", 75.0)
                # GDD approximation: assume constant daily temp over season
                _gdd_day    = max(0.0, t - _base_t)
                _gdd_season = _gdd_day * _SEASON_DAYS_EST
                # Fraction-based stress approximations (point estimate → binary proxy)
                _cold_frac  = 1.0 if t < _base_t else 0.0
                _heat_frac  = 1.0 if t > _opt_max else 0.0
                return {
                    # v2 features
                    "temp_internal_mean_mean":  t,
                    "temp_internal_max_mean":   t + 3.0,
                    "temp_internal_min_mean":   t - 3.0,
                    "humidity_int_mean_mean":   hum,
                    "co2_ppm_mean_mean":        co2,
                    "solar_rad_mean_mean":      sol,
                    "solar_rad_sum_mean":       sol * 8.0,
                    "gdd_max":                  _gdd_season,
                    "days":                     _SEASON_DAYS_EST,
                    "season_num":               1.0,
                    "year":                     float(_dt.date.today().year),
                    "ship_days":                30.0,
                    # v3 new features (approximated from single point-in-time env reading)
                    "gdd_recomputed":           _gdd_season,
                    "temp_range_mean":          6.0,   # fixed typical diurnal range
                    "cold_day_count":           _cold_frac * _SEASON_DAYS_EST,
                    "heat_stress_days":         _heat_frac * _SEASON_DAYS_EST,
                    "solar_rad_cumsum":         sol * 8.0 * _SEASON_DAYS_EST,
                    "co2_ppm_std":              0.0,   # unknown at inference time
                    "temp_std_daily":           0.0,   # unknown at inference time
                    "gdd_per_day":              _gdd_day,
                    "cold_day_frac":            _cold_frac,
                    "heat_stress_frac":         _heat_frac,
                    # std features (unknown at inference time, use 0)
                    "temp_internal_mean_std":   0.0,
                    "humidity_int_mean_std":    0.0,
                    "solar_rad_mean_std":       0.0,
                    "solar_rad_sum_std":        0.0,
                    "gdd_cumsum_std":           0.0,
                }

            _m2_baseline = _m2_predict(crop_ko, _env_to_season(dict(current_env.values)), area_m2)
            _baseline_yield_m2 = max(0.01, _m2_baseline["yield_kg_m2"])

            def _m2_fn(env: dict) -> tuple[float, float]:
                r = _m2_predict(crop_ko, _env_to_season(env), area_m2)
                return max(0.0, r["yield_kg_m2"]), 0.72

            # Sensitivity check: skip M2 if it returns the same yield for all candidates
            _probe_candidates = generate_candidates(current_env, max_simultaneous=1, crop_ko=crop_ko)
            if _check_sensitivity(_m2_fn, dict(current_env.values), _probe_candidates):
                yield_predict_fn   = _m2_fn
                baseline_yield_kg_m2 = _baseline_yield_m2
                logger.info("[profit_optimizer] M2 model active: baseline=%.3f kg/m2", _baseline_yield_m2)
            else:
                logger.warning(
                    "[profit_optimizer] M2 insensitive for crop=%s -- falling back to pipeline", crop_ko
                )

        except Exception as _e:
            logger.warning("[profit_optimizer] M2 model failed: %s -- trying pipeline", _e)

        # Block 1: FourStagePipeline (only when M2 inactive)
        if yield_predict_fn is None:
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
                # Block 2: legacy model_loader
                try:
                    from api.services.model_loader import predict_revenue_per_m2 as _ml_pred
                    from api.services.model_loader import normalize_crop as _norm_crop2
                    _crop_norm2 = _norm_crop2(crop_ko)

                    _PRICE_PER_KG = {
                        "딸기": 9799,
                        "방울토마토": 3956,
                        "완숙토마토": 2758,
                        "참외": 3142,
                        "파프리카": 4000,
                        "오이": 1845,
                    }

                    def yield_predict_fn(env: dict) -> tuple[float, float]:
                        env_feat = {
                            "temp_internal_mean":  env.get("temp_internal", 20.0),
                            "humidity_int_mean":   env.get("humidity_int", 70.0),
                            "co2_ppm_mean":        env.get("co2_ppm", 800.0),
                            "solar_rad_mean":      env.get("solar_rad", 100.0),
                            "soil_temp_mean":      env.get("soil_temp", 18.0),
                            "gdd_monthly":         max(0, env.get("temp_internal", 20.0) - 10.0) * 30.0,
                        }
                        rev_pm2 = _ml_pred(_crop_norm2, env_feat, month=_cur_month)
                        if rev_pm2 is not None and rev_pm2 > 0:
                            price_kg = _PRICE_PER_KG.get(_crop_norm2, 3000)
                            return max(0.0, rev_pm2 / price_kg), 0.75
                        temp = env.get("temp_internal", 22.0)
                        return baseline_yield_kg_m2 + max(0.0, 0.008 * (temp - 20.0)), 0.45

                except Exception:
                    # Block 3: final temperature-based stub
                    def yield_predict_fn(env: dict) -> tuple[float, float]:
                        temp = env.get("temp_internal", 22.0)
                        bonus = max(0.0, 0.01 * (temp - 20.0))
                        return baseline_yield_kg_m2 + bonus, 0.6

    if price_forecast_fn is None:
        try:
            from api.data.stats_loader import get_price_krw_kg
            def price_forecast_fn() -> float:
                return get_price_krw_kg(crop_ko)
        except Exception:
            def price_forecast_fn() -> float:
                return 3000.0

    price      = price_forecast_fn()
    candidates = generate_candidates(current_env, max_simultaneous=2, crop_ko=crop_ko)
    results: list[Recommendation] = []

    for candidate in candidates:
        env_with_change = dict(current_env.values)
        env_with_change.update(candidate.changes)

        predicted_yield, confidence = yield_predict_fn(env_with_change)
        revenue_delta = (predicted_yield - baseline_yield_kg_m2) * price * area_m2
        cost_delta    = _compute_cost_delta(candidate, current_env, horizon_days, crop_ko, area_m2)
        profit_delta  = revenue_delta - cost_delta

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
        "[profit_optimizer] farm=%s model=%s candidates=%d top_delta=KRW%.0f",
        farm_id,
        "M2" if confidence == 0.72 else "pipeline",
        len(candidates),
        top[0].profit_delta if top else 0,
    )
    return top
