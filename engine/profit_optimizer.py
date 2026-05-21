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

# ── 야간소실률 기준값 (Priva 표준) ────────────────────────────────────────────
_NL_NORMAL_MIN = 3.0    # 야간소실률 정상 하한 (%)
_NL_NORMAL_MAX = 7.0    # 야간소실률 정상 상한 (%)

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


def _night_loss_recommendations(
    nl_pct: float,
    crop_ko: str,
    tier: FarmTier,
    area_m2: float = 1000.0,
    horizon_days: int = 30,
    cost_rates: Optional[dict] = None,
) -> list[Recommendation]:
    """야간소실률(nl_pct) 이탈 시 야간 환경 권고 Recommendation 생성.

    야간소실률 > 7% (과증산):
      → 야간 온도 -2℃ 권고: 에너지 절감(heating cost 감소) + 증산 억제
    야간소실률 < 3% (증산 부족):
      → 야간 습도 조정 또는 환기 개선 권고

    profit_delta:
      - 과증산 케이스: 난방비 절감분 (temp_cost_rate × 2℃ × horizon_days)
      - 증산 부족 케이스: 작물 스트레스 완화에 따른 정성적 수익 개선 (보수적 추정)
    """
    if _NL_NORMAL_MIN <= nl_pct <= _NL_NORMAL_MAX:
        return []

    recs: list[Recommendation] = []
    temp_rate = (cost_rates or {}).get("temp_internal", _COST_PER_UNIT_FALLBACK["temp_internal"])

    if nl_pct > _NL_NORMAL_MAX:
        # 야간 과증산: 온도 2℃ 낮춤 → 난방비 절감 + 증산 억제
        temp_delta   = 2.0
        energy_save  = temp_rate * temp_delta * horizon_days
        excess       = round(nl_pct - _NL_NORMAL_MAX, 1)
        recs.append(Recommendation(
            rank=0,
            action_ko=(
                f"야간 온도 2℃ 낮춤 — 야간소실률 {nl_pct:.1f}% > {_NL_NORMAL_MAX:.0f}% 기준 "
                f"(과증산 {excess}%p 초과). 난방비 절감 + 수분 스트레스 완화 기대"
            ),
            profit_delta=round(energy_save, 0),
            revenue_delta=0.0,
            cost_delta=round(-energy_save, 0),
            confidence=0.65,
            canonical_changes={"temp_internal": -temp_delta},
            tier_action=_tier_action(tier),
        ))
    else:
        # 야간 소실 부족: 뿌리압 저하 → 주간 흡수 능률 하락 → 간접 수익 손실
        # 보수 추정: 0.5% 수익 개선 가능
        deficit     = round(_NL_NORMAL_MIN - nl_pct, 1)
        revenue_est = round(area_m2 * 0.5 * 3000 * 0.005, 0)   # 0.5kg/m² × 3000원/kg × 0.5%
        recs.append(Recommendation(
            rank=0,
            action_ko=(
                f"야간 습도 조정·환기 점검 — 야간소실률 {nl_pct:.1f}% < {_NL_NORMAL_MIN:.0f}% 기준 "
                f"(증산 부족 {deficit}%p). 야간 통풍 또는 온도 소폭 상향으로 뿌리압 회복 유도"
            ),
            profit_delta=round(revenue_est, 0),
            revenue_delta=round(revenue_est, 0),
            cost_delta=0.0,
            confidence=0.55,
            canonical_changes={"humidity_int": -5.0},   # 야간 습도 5% 낮춤 (절대값 아닌 델타)
            tier_action=_tier_action(tier),
        ))

    return recs


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
    month: Optional[int] = None,
) -> list[Recommendation]:
    """Find top-N environment adjustments that maximise profit.

    Args:
        month: 현재 월 (1~12). None이면 today 기준. 작기단계 후보 생성에 사용.
    """
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

            # 작기 임계이벤트 설정 (train_stage2_yield.py와 동일)
            _FLOWER_MONTHS = {
                "strawberry": [11,12,1], "cherry_tomato": [3,4,5],
                "tomato": [3,4,5], "melon": [4,5], "paprika": [3,4,5],
            }
            _FRUIT_MONTHS = {
                "strawberry": [1,2,3], "cherry_tomato": [4,5,6],
                "tomato": [4,5,6], "melon": [5,6], "paprika": [4,5,6],
            }
            _COLD_THRESH = {
                "strawberry": 8.0, "cherry_tomato": 12.0, "tomato": 12.0,
                "melon": 14.0, "paprika": 12.0,
            }
            _HEAT_THRESH = {
                "strawberry": 25.0, "cherry_tomato": 32.0, "tomato": 32.0,
                "melon": 35.0, "paprika": 30.0,
            }
            _VPD_OPT = {
                "strawberry": (0.6, 1.0), "cherry_tomato": (0.8, 1.4),
                "tomato": (0.8, 1.4), "melon": (0.7, 1.2), "paprika": (0.8, 1.2),
            }
            _cold_thr = _COLD_THRESH.get(_crop_en_key, 10.0)
            _heat_thr = _HEAT_THRESH.get(_crop_en_key, 32.0)
            _vpd_lo, _vpd_hi = _VPD_OPT.get(_crop_en_key, (0.7, 1.2))
            _n_flower_m = len(_FLOWER_MONTHS.get(_crop_en_key, [3,4,5]))
            _n_fruit_m  = len(_FRUIT_MONTHS.get(_crop_en_key, [4,5,6]))
            _SEASON_MONTHS = 12.0

            # 논문 기반 과학 피처 상수 (train_stage2_yield._add_science_features와 동일)
            _OPT_TEMP_RANGE = {
                "strawberry": (15.0, 20.0), "cherry_tomato": (18.0, 25.0),
                "tomato": (18.0, 25.0), "melon": (22.0, 30.0), "paprika": (18.0, 26.0),
            }
            _OPT_RH_RANGE = {
                "strawberry": (55.0, 75.0), "cherry_tomato": (60.0, 80.0),
                "tomato": (60.0, 80.0), "melon": (60.0, 75.0), "paprika": (60.0, 80.0),
            }
            _TRUSS_INTERVAL = {"cherry_tomato": 8.5, "tomato": 7.0}
            import math as _math_sci
            _KR_LAT = _math_sci.radians(36.5)
            def _dl_hours(month: float) -> float:
                """월 중순 천문 일장 (한국 36.5°N)."""
                doy = int(month) * 30 - 15
                decl = _math_sci.radians(23.45) * _math_sci.sin(_math_sci.radians(360/365*(doy-81)))
                cos_ha = max(-1.0, min(1.0, -_math_sci.tan(_KR_LAT) * _math_sci.tan(decl)))
                return 2.0 * _math_sci.degrees(_math_sci.acos(cos_ha)) / 15.0
            _opt_tl, _opt_th = _OPT_TEMP_RANGE.get(_crop_en_key, (18.0, 25.0))
            _opt_rl, _opt_rh_v = _OPT_RH_RANGE.get(_crop_en_key, (60.0, 80.0))

            def _env_to_season(env: dict) -> dict:
                t    = env.get("temp_internal", 20.0)
                sol  = env.get("solar_rad", 150.0)
                co2  = env.get("co2_ppm", 500.0)
                hum  = env.get("humidity_int", 75.0)
                ec   = env.get("ec_dsm", 2.0)
                # GDD approximation: assume constant daily temp over season
                _gdd_day    = max(0.0, t - _base_t)
                _gdd_season = _gdd_day * _SEASON_DAYS_EST
                # Stress fractions (0 or 1, scaled by number of critical months)
                _cold_frac  = 1.0 if t < _cold_thr else 0.0
                _heat_frac  = 1.0 if t > _heat_thr else 0.0
                # VPD 계산 (Tetens 공식)
                import math as _math
                _svp = 0.6108 * _math.exp(17.27 * t / (t + 237.3))
                _vpd = max(0.0, _svp * (1.0 - hum / 100.0))
                _vpd_out = 1.0 if (_vpd < _vpd_lo or _vpd > _vpd_hi) else 0.0

                return {
                    # ── stage2 포맷 C 피처 (train_stage2_yield.py와 동일 이름) ─────────
                    "temp_internal_mean":       t,
                    "temp_internal_std":        0.0,
                    "humidity_int_mean":        hum,
                    "humidity_int_std":         0.0,
                    "co2_ppm_mean":             co2,
                    "co2_ppm_std":              0.0,
                    "solar_rad_mean":           sol,
                    "solar_rad_std":            0.0,
                    "ec_dsm_mean":              ec,
                    "ec_dsm_std":               0.0,
                    "gdd_annual":               _gdd_season,
                    # 임계이벤트 피처 (현재 온도로부터 추정)
                    "flower_temp_mean":         t,
                    "flower_cold_months":       _cold_frac * _n_flower_m,
                    "vpd_flower_mean":          _vpd,
                    "fruit_temp_mean":          t,
                    "fruit_heat_months":        _heat_frac * _n_fruit_m,
                    "dli_annual":               sol * 0.0115 * _SEASON_MONTHS,
                    "vpd_out_months":           _vpd_out * _SEASON_MONTHS,
                    "vpd_annual_mean":          _vpd,
                    # 편차 피처 (추론 시점에서는 0 → imputer가 중앙값으로 대체)
                    "temp_internal_mean_farm_dev":  0.0,
                    "humidity_int_mean_farm_dev":   0.0,
                    "co2_ppm_mean_farm_dev":        0.0,
                    "solar_rad_mean_farm_dev":      0.0,
                    # 상호작용 피처
                    "temp_co2_interact":        t * co2 / 10000.0,
                    "dli_temp_interact":        sol * 0.0115 * _SEASON_MONTHS * t / 100.0,
                    "stress_combined":          _cold_frac * _n_flower_m + _heat_frac * _n_fruit_m,
                    # ── 논문 기반 과학 피처 (Phase 2) ──────────────────────────────
                    # CO₂ Michaelis-Menten 포화 응답 (Km=250 ppm, C3 식물)
                    "co2_mm_response":          co2 / (co2 + 250.0),
                    # 최적 범위 체류 비율 (현재 환경값 기반 근사 — 추론 시 점 추정)
                    "pct_time_optimal_temp":    1.0 if _opt_tl <= t <= _opt_th else 0.3,
                    "pct_time_optimal_rh":      1.0 if _opt_rl <= hum <= _opt_rh_v else 0.3,
                    "pct_time_cold_stress":     1.0 if t < _opt_tl else 0.0,
                    "pct_time_heat_stress":     1.0 if t > _opt_th else 0.0,
                    # 토마토 전용 PAR/화방 피처
                    "cumulative_par_mj":        sol * 0.0115 * 0.217 * 8.0 * 30.4 if _crop_en_key in ("cherry_tomato","tomato") else 0.0,
                    "truss_count_estimate":     _gdd_season / _TRUSS_INTERVAL.get(_crop_en_key, 7.5),
                    "par_yield_efficiency":     1.0,
                    # 딸기 전용 일장 피처 (이식월 9월 기준)
                    "daylength_plant_month":    _dl_hours(9.0) if _crop_en_key == "strawberry" else 12.0,
                    "sd_induction_index":       max(0.0, 14.5 - _dl_hours(9.0)) if _crop_en_key == "strawberry" else 0.0,
                    "sd_month_fraction":        0.67 if _crop_en_key == "strawberry" else 0.0,
                    # 파프리카 진동 프록시
                    "harvest_month_cv":         0.2,
                    # 연도 정규화 (최신 연도 → 1.0에 가까움)
                    "year_norm":                1.0,
                    "n_harvest_months":         8.0,
                    # 면적 피처는 m2_yield.py에서 area_m2로 계산
                    # ── 구버전 v2/v3 피처 (포맷 A/B 호환성 유지) ─────────────────────
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
                    "gdd_recomputed":           _gdd_season,
                    "temp_range_mean":          6.0,
                    "cold_day_count":           _cold_frac * _SEASON_DAYS_EST,
                    "heat_stress_days":         _heat_frac * _SEASON_DAYS_EST,
                    "solar_rad_cumsum":         sol * 8.0 * _SEASON_DAYS_EST,
                    "temp_std_daily":           0.0,
                    "gdd_per_day":              _gdd_day,
                    "cold_day_frac":            _cold_frac,
                    "heat_stress_frac":         _heat_frac,
                    "temp_internal_mean_std":   0.0,
                    "humidity_int_mean_std":    0.0,
                    "solar_rad_mean_std":       0.0,
                    "solar_rad_sum_std":        0.0,
                    "gdd_cumsum_std":           0.0,
                }

            # farm_id 전달: m2_yield.py 포맷 C에서 farm_encoding 조회에 사용
            _opt_farm_id = farm_id if farm_id else None
            _m2_baseline = _m2_predict(
                crop_ko, _env_to_season(dict(current_env.values)),
                area_m2, _opt_farm_id,
            )
            _baseline_yield_m2 = max(0.01, _m2_baseline["yield_kg_m2"])

            def _m2_fn(env: dict) -> tuple[float, float]:
                r = _m2_predict(crop_ko, _env_to_season(env), area_m2, _opt_farm_id)
                return max(0.0, r["yield_kg_m2"]), 0.72

            # Sensitivity check: skip M2 if it returns the same yield for all candidates
            # threshold=1e-5 (완화): 미세 변화도 감지, 낮은 R² 모델에서 폴백 방지
            _probe_candidates = generate_candidates(current_env, max_simultaneous=1, crop_ko=crop_ko)
            if _check_sensitivity(_m2_fn, dict(current_env.values), _probe_candidates,
                                  threshold=1e-5):
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
        # KAMIS API → stats_loader → stub 순으로 폴백
        try:
            from scripts.data_integration.kamis_api import get_price as _kamis_price
            def price_forecast_fn() -> float:
                try:
                    return _kamis_price(crop_ko)
                except Exception:
                    return 3000.0
        except ImportError:
            try:
                from api.data.stats_loader import get_price_krw_kg
                def price_forecast_fn() -> float:
                    return get_price_krw_kg(crop_ko)
            except Exception:
                def price_forecast_fn() -> float:
                    return 3000.0

    price      = price_forecast_fn()
    candidates = generate_candidates(
        current_env, max_simultaneous=2, crop_ko=crop_ko, month=month
    )
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

    # ── 야간소실률 → 야간 환경 권고 통합 ───────────────────────────────────────
    nl_pct = current_env.values.get("nl_pct")
    if nl_pct is not None:
        _cost_rates_for_nl = _get_cost_rates(crop_ko, area_m2)
        nl_recs = _night_loss_recommendations(
            nl_pct, crop_ko, tier, area_m2, horizon_days, _cost_rates_for_nl
        )
        if nl_recs:
            results.extend(nl_recs)
            logger.info(
                "[profit_optimizer] night-loss recs added: nl_pct=%.1f%% %s",
                nl_pct,
                "과증산" if nl_pct > _NL_NORMAL_MAX else "증산부족",
            )

    results.sort(key=lambda r: r.profit_delta, reverse=True)
    top = results[:MAX_RECOMMENDATIONS]
    for i, rec in enumerate(top, start=1):
        rec.rank = i

    # confidence 변수가 마지막 loop 이후 정의돼 있지 않을 수 있으므로 안전하게 참조
    _last_conf = top[0].confidence if top else 0.0
    logger.info(
        "[profit_optimizer] farm=%s candidates=%d nl_recs=%d top_delta=KRW%.0f",
        farm_id,
        len(candidates),
        len(nl_recs) if nl_pct is not None else 0,
        top[0].profit_delta if top else 0,
    )
    return top
