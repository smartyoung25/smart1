"""
api/data/stats_loader.py

기초자료에서 추출된 JSON 통계를 로드하고 API 전반에서 사용할
정규화된 파라미터를 제공하는 단일 진입점.

scripts/extract_rda_stats.py    → price_stats.json, yield_stats.json, farm_registry.json
scripts/extract_cost_params.py  → cost_params.json
scripts/extract_env_stats.py    → env_stats.json  (환경-수확량 상관계수, 최적범위)
scripts/extract_growth_stats.py → growth_stats.json (GDD 파라미터)
scripts/extract_income_survey.py → income_survey.json (경영비 단가)
"""

from __future__ import annotations

import json
import math
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_DATA_DIR = Path(__file__).parent


# ── JSON 로더 (파일 없으면 빈 dict, 앱 기동 시 1회 캐싱) ─────────────────────

@lru_cache(maxsize=None)
def _load(filename: str) -> dict:
    path = _DATA_DIR / filename
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[stats_loader] %s 로드 실패: %s", filename, e)
        return {}


def _price_data()    -> dict: return _load("price_stats.json")
def _yield_data()    -> dict: return _load("yield_stats.json")
def _cost_data()     -> dict: return _load("cost_params.json")
def _farm_registry() -> dict: return _load("farm_registry.json")
def _env_stats()     -> dict: return _load("env_stats.json")
def _growth_stats()  -> dict: return _load("growth_stats.json")
def _income_survey() -> dict: return _load("income_survey.json")


# ── 품목명 정규화 ─────────────────────────────────────────────────────────────
# 대시보드에서 영문 crop 코드를 한글 품목명으로 변환
# 수익 예측이 통계적으로 유효한 작목 (농진청 5년 패널 n≥60 기준, 파프리카 추가)
SUPPORTED_CROPS: list[str] = ["딸기", "방울토마토", "완숙토마토", "참외", "오이", "파프리카"]

CROP_KO: dict[str, str] = {
    "strawberry":    "딸기",
    "cherry_tomato": "방울토마토",
    "tomato":        "완숙토마토",
    "melon":         "참외",
    "cucumber":      "오이",
    "paprika":       "파프리카",
    # 한글 입력도 그대로 통과
    "딸기": "딸기", "방울토마토": "방울토마토", "완숙토마토": "완숙토마토",
    "참외": "참외", "오이": "오이", "파프리카": "파프리카",
}


def normalize_crop(crop: str) -> str:
    """영문 또는 한글 품목명 → 데이터셋 한글 키로 정규화.
    '딸기(설향)' 같이 품종명이 붙은 경우도 작목 키에 매핑한다.
    """
    # 1. 완전 일치
    exact = CROP_KO.get(crop)
    if exact:
        return exact
    # 2. 부분 일치 — "딸기(설향)" → "딸기" 등 품종명 포함 케이스
    for key, val in CROP_KO.items():
        if crop.startswith(key):
            return val
    return crop


# ── 가격 조회 ─────────────────────────────────────────────────────────────────

# 데이터셋에 없는 품목을 위한 기본값 (원/kg) — 2024 KAMIS/농진청 트렌드 기반
_PRICE_DEFAULTS: dict[str, float] = {
    "딸기":      12500.0,
    "방울토마토":  4800.0,
    "완숙토마토":  3200.0,
    "참외":       3850.0,
    "오이":       2200.0,
    "파프리카":   4100.0,
}


def get_price_krw_kg(crop: str, percentile: str = "mean") -> float:
    """품목별 kg당 판매단가 반환.

    조회 우선순위:
      1. KAMIS 캐시 (kamis_price_cache.json — 당일 도매가격)
      2. RDA 5년 패널 통계 (price_stats.json)
      3. 하드코딩 기본값

    percentile: "mean" | "median" | "p25" | "p75"
    (KAMIS 캐시 사용 시 percentile은 무시됨 — 단일 도매가격)
    """
    crop_ko = normalize_crop(crop)

    # ① KAMIS 당일 캐시 우선
    try:
        from pipeline.kamis_fetcher import get_cached_price
        kamis_price = get_cached_price(crop_ko)
        if kamis_price is not None:
            return kamis_price
    except Exception:
        pass   # pipeline 패키지 없는 환경(테스트 등)에서는 무시

    pdata = _price_data()

    # ② price_stats.json 내 최신 연평균 단일 값 (2024 추정치 — mean 전용)
    if percentile == "mean":
        flat = pdata.get("price_krw_kg", {}).get(crop_ko)
        if flat is not None:
            return float(flat)

    # ③ RDA 패널 통계 by_crop
    by_crop = pdata.get("by_crop", {})
    stats = by_crop.get(crop_ko)
    if not stats:
        return _PRICE_DEFAULTS.get(crop_ko, 3000.0)

    key_map = {
        "mean":   "mean_krw_kg",
        "median": "median_krw_kg",
        "p25":    "p25_krw_kg",
        "p75":    "p75_krw_kg",
    }
    return float(stats.get(key_map.get(percentile, "mean_krw_kg"), stats["mean_krw_kg"]))


def get_price_stats(crop: str) -> dict:
    """품목 단가 통계 전체 반환."""
    crop_ko = normalize_crop(crop)
    by_crop = _price_data().get("by_crop", {})
    return by_crop.get(crop_ko, {"mean_krw_kg": _PRICE_DEFAULTS.get(crop_ko, 3000.0)})


def get_yearly_trend(crop: str) -> dict[str, dict]:
    """연도별 단가 추이 반환 (가격 예측용)."""
    crop_ko = normalize_crop(crop)
    return _price_data().get("yearly_trend", {}).get(crop_ko, {})


# ── 수확량 조회 ───────────────────────────────────────────────────────────────

_YIELD_DEFAULTS: dict[str, float] = {
    "딸기":       3.2,   # kg/m²/작기 — RDA 정상 범위 2~12, 통계 중앙값
    "방울토마토": 12.0,  # RDA 정상 범위 5~25, 보수적 중앙값
    "완숙토마토": 15.0,  # RDA 정상 범위 8~30, 보수적 중앙값
    "참외":        7.0,  # RDA 정상 범위 3~12 (구값 17.0은 상한 초과)
    "파프리카":   12.0,  # RDA 정상 범위 8~20, 중앙값
    "오이":       18.0,  # RDA 정상 범위 15~50
}


def get_yield_kg_m2(crop: str, percentile: str = "median") -> float:
    """
    품목별 작기당 kg/m² 수확량 반환.
    percentile: "median" | "avg" | "p25" | "p75"
    기본값을 median으로 사용 — avg는 면적 오기록 이상치로 inflate되어 있음
    """
    crop_ko = normalize_crop(crop)
    by_crop = _yield_data().get("by_crop", {})
    stats = by_crop.get(crop_ko)
    if not stats:
        return _YIELD_DEFAULTS.get(crop_ko, 10.0)

    key_map = {
        "avg":    "avg_kg_m2_season",
        "median": "median_kg_m2_season",
        "p25":    "p25_kg_m2_season",
        "p75":    "p75_kg_m2_season",
    }
    # median 우선, 없으면 avg로 폴백
    preferred = key_map.get(percentile, "median_kg_m2_season")
    return float(stats.get(preferred) or stats.get("avg_kg_m2_season", _YIELD_DEFAULTS.get(crop_ko, 10.0)))


def get_yield_stats(crop: str) -> dict:
    """품목 수확량 통계 전체 반환."""
    crop_ko = normalize_crop(crop)
    by_crop = _yield_data().get("by_crop", {})
    return by_crop.get(crop_ko, {"avg_kg_m2_season": _YIELD_DEFAULTS.get(crop_ko, 10.0)})


# ── 수익 계산 ─────────────────────────────────────────────────────────────────

def estimate_season_revenue(crop: str, area_m2: float, price_pct: str = "mean") -> dict:
    """
    면적과 품목으로 작기 수익 추정.
    Returns: {predicted_yield_kg, price_krw_kg, gross_revenue_krw, net_profit_krw}
    """
    crop_ko  = normalize_crop(crop)
    price    = get_price_krw_kg(crop, price_pct)
    yield_m2 = get_yield_kg_m2(crop)
    total_kg = yield_m2 * area_m2

    # 비용: income_survey.json 기반 원/m² 합산, 없으면 수익 대비 38% 폴백
    gross_revenue = total_kg * price

    survey_costs = _income_survey().get(crop_ko, {}).get("cost_per_m2", {})
    if survey_costs:
        estimated_cost = sum(survey_costs.values()) * area_m2
    else:
        estimated_cost = gross_revenue * 0.38

    return {
        "predicted_yield_kg":  round(total_kg, 1),
        "yield_per_m2":        round(yield_m2, 2),
        "price_krw_kg":        round(price, 0),
        "gross_revenue_krw":   round(gross_revenue, 0),
        "estimated_cost_krw":  round(estimated_cost, 0),
        "net_profit_krw":      round(gross_revenue - estimated_cost, 0),
        "data_source":         "rda_panel_2018_2025_estimated",
    }


# ── 비용 단가 조회 ────────────────────────────────────────────────────────────

def get_cost_rate(category: str, key: str = "avg_monthly_krw") -> float:
    """
    category: "electricity" | "fertilizer" | "labor" | "nutrients" | "other" | ...
    key: "avg_monthly_krw" | "median_monthly_krw"
    """
    monthly = _cost_data().get("monthly_costs_by_category", {})
    stats = monthly.get(category, {})
    return float(stats.get(key, 0.0))


def get_electricity_rate() -> float:
    """전기 요금 (원/kWh). 경영정보 또는 KEPCO 기준값."""
    ref = _cost_data().get("reference_rates", {}).get("electricity", {})
    return float(ref.get("avg_rate_krw_kwh", 112.0))


def get_water_rate() -> float:
    """수도 요금 (원/m³). 경영정보 또는 지자체 기준값."""
    ref = _cost_data().get("reference_rates", {}).get("water", {})
    return float(ref.get("avg_rate_krw_m3", 620.0))


def get_labor_daily_rate() -> float:
    """인건비 일당 (원/일). 영농작업 데이터 기반."""
    labor = _cost_data().get("labor_daily_rate", {})
    return float(labor.get("avg_daily_krw", 120_000.0))


def get_grade_price(grade: str = "전체") -> float:
    """등급별 kg당 판매단가 (농정원 생산량 CSV 기반)."""
    grades = _cost_data().get("grade_prices_krw_kg", {})
    return float(grades.get(grade, {}).get("mean_krw_kg", 5000.0))


# ── What-if profit delta 계산 ──────────────────────────────────────────────────

# 환경 파라미터 변화 → 수확량 변화율 폴백 (env_stats.json 없을 때 사용)
_ENV_YIELD_SENSITIVITY_FALLBACK: dict[str, dict] = {
    "temp_internal":  {"delta_1c_up": 0.012},
    "humidity_int":   {"delta_5pct_up": 0.008},
    "co2_ppm":        {"delta_100ppm_up": 0.025},
    "solar_rad":      {"delta_50wm2_up": 0.015},
    "ec_dsm":         {"delta_0.5_up": 0.018},
}

# env 변수 단위 스텝 (Pearson r → 단위당 민감도 스케일링용)
_SENSITIVITY_UNIT: dict[str, tuple[str, float]] = {
    "temp_internal":  ("delta_1c_up",      1.0),
    "humidity_int":   ("delta_5pct_up",    5.0),
    "co2_ppm":        ("delta_100ppm_up",  100.0),
    "solar_rad":      ("delta_50wm2_up",   50.0),
}


def _build_sensitivity_from_corr(crop_ko: str) -> dict[str, dict]:
    """env_stats.json 수확량_상관 Pearson r → 단위당 수확량 변화율 변환.

    r을 직접 민감도로 쓰되 단위 스텝으로 스케일:
      yield_ratio_per_unit = |r| * 0.05 / unit_step
    (r=1.0 이면 스텝당 5% 반응 가정, 부호는 r의 부호 반영)
    """
    env = _env_stats()
    corr_map: dict[str, float] = env.get(crop_ko, {}).get("수확량_상관", {})
    if not corr_map:
        return {}

    sensitivity: dict[str, dict] = {}
    for var, (key, unit) in _SENSITIVITY_UNIT.items():
        r = corr_map.get(var)
        if r is None:
            continue
        # ★ per-step 변화율(폴백 _ENV_YIELD_SENSITIVITY_FALLBACK 와 동일 의미). 구: /unit → 이후
        #   compute_profit_delta 가 다시 /unit_delta 하여 CO₂·일사·습도 델타가 100·50·5배 축소됐다.
        ratio = round(r * 0.05, 6)   # 스텝(delta_1c/100ppm/50wm2/5pct)당 변화율
        sensitivity[var] = {key: ratio}

    return sensitivity


def get_env_yield_sensitivity(crop_ko: str = "딸기") -> dict[str, dict]:
    """작목별 환경-수확량 민감도 dict 반환.

    env_stats.json에 해당 작목 데이터가 있으면 실측 상관계수 기반,
    없으면 폴백 하드코딩 값 사용.
    """
    from_data = _build_sensitivity_from_corr(crop_ko)
    if not from_data:
        return dict(_ENV_YIELD_SENSITIVITY_FALLBACK)
    # 데이터에 없는 변수는 폴백으로 채움
    result = dict(_ENV_YIELD_SENSITIVITY_FALLBACK)
    result.update(from_data)
    return result


def compute_profit_delta(
    crop: str,
    area_m2: float,
    param: str,
    delta: float,
    current_price_krw_kg: float | None = None,
) -> dict:
    """
    환경 파라미터 delta 변경 시 예상 수익 증분 계산.

    Args:
        crop:   품목 (한글 또는 영문)
        area_m2: 재배 면적
        param:  변경 환경변수 (canonical name)
        delta:  변화량 (양수: 증가)
        current_price_krw_kg: 현재 단가 (None이면 데이터셋 평균 사용)

    Returns:
        {profit_delta_krw, yield_delta_kg, price_krw_kg, confidence}
    """
    crop_ko = normalize_crop(crop)
    price   = current_price_krw_kg or get_price_krw_kg(crop)
    base_yield_per_m2 = get_yield_kg_m2(crop)
    base_yield = base_yield_per_m2 * area_m2

    sensitivity = get_env_yield_sensitivity(crop_ko).get(param, {})

    # 가장 적합한 감도 키 선택
    yield_ratio = 0.0
    for key, ratio in sensitivity.items():
        parts = key.split("_")
        if len(parts) >= 2:
            try:
                # ★ 'c' 제거를 맨 끝으로 — 구: replace("c") 가 "5pct"의 c 를 지워 "pt"→ValueError→humidity 델타=0
                unit_delta = float(parts[1].replace("pct", "").replace("ppm", "")
                                            .replace("wm2", "").replace("m2", "").replace("c", ""))
                yield_ratio = ratio * (delta / unit_delta)
                break
            except ValueError:
                continue

    # 신뢰도: 데이터 샘플 수 기반 (n_farm_seasons)
    yield_stats = get_yield_stats(crop)
    n = yield_stats.get("n_farm_seasons", 0)
    confidence = min(0.95, 0.50 + n / 400.0)  # n=200 → 0.75, n=400 → 0.95

    yield_delta_kg   = base_yield * yield_ratio
    profit_delta_krw = yield_delta_kg * price

    return {
        "profit_delta_krw":  round(profit_delta_krw, 0),
        "yield_delta_kg":    round(yield_delta_kg, 2),
        "yield_delta_pct":   round(yield_ratio * 100, 2),
        "price_krw_kg":      round(price, 0),
        "confidence":        round(confidence, 3),
        "data_source":       "rda_5yr_sensitivity_estimate",
    }


# ── 품목별 면적 통계 조회 ─────────────────────────────────────────────────────

def get_area_stats(crop: str) -> dict:
    """재배정보 기반 품목별 면적 통계."""
    crop_ko = normalize_crop(crop)
    return _farm_registry().get("area_stats_by_crop", {}).get(crop_ko, {})


# ── GDD 파라미터 ──────────────────────────────────────────────────────────────

# 폴백 값 (growth_stats.json 없을 때 사용)
_GDD_PARAMS_FALLBACK: dict[str, dict] = {
    "딸기":      {"base_temp_c": 6.0,  "gdd_to_first_harvest": 450, "gdd_per_flush": 180, "season_weeks": 26},
    "방울토마토": {"base_temp_c": 10.0, "gdd_to_first_harvest": 600, "gdd_per_flush": 200, "season_weeks": 34},
    "완숙토마토": {"base_temp_c": 10.0, "gdd_to_first_harvest": 650, "gdd_per_flush": 220, "season_weeks": 34},
    "참외":      {"base_temp_c": 12.0, "gdd_to_first_harvest": 700, "gdd_per_flush": 240, "season_weeks": 20},
    "오이":      {"base_temp_c": 12.0, "gdd_to_first_harvest": 400, "gdd_per_flush": 150, "season_weeks": 20},
}


def _build_gdd_params() -> dict[str, dict]:
    """growth_stats.json GDD_보정 값으로 GDD 파라미터 딕트 구성.
    실측값이 있으면 반영, 없는 항목은 폴백 유지.
    """
    growth = _growth_stats()
    if not growth:
        return dict(_GDD_PARAMS_FALLBACK)
    result = {}
    for crop_ko, fallback in _GDD_PARAMS_FALLBACK.items():
        gdd_info = growth.get(crop_ko, {}).get("GDD_보정", {})
        fitted   = gdd_info.get("fitted_gdd_to_harvest")
        base     = gdd_info.get("base_temp_c")
        entry    = dict(fallback)
        if fitted:
            entry["gdd_to_first_harvest"] = fitted
        if base:
            entry["base_temp_c"] = base
        result[crop_ko] = entry
    return result


GDD_PARAMS: dict[str, dict] = _build_gdd_params()


def estimate_harvest_days(
    crop: str,
    current_temp_avg: float,
    accumulated_gdd: float = 0.0,
) -> int:
    """
    현재 평균 온도와 누적 GDD를 기반으로 첫 수확까지 예상 일수 계산.
    accumulated_gdd: 정식일 이후 현재까지 누적된 GDD (없으면 0)
    """
    crop_ko = normalize_crop(crop)
    params  = GDD_PARAMS.get(crop_ko, GDD_PARAMS["딸기"])

    base_temp    = params["base_temp_c"]
    target_gdd   = params["gdd_to_first_harvest"]
    remaining    = max(0.0, target_gdd - accumulated_gdd)
    daily_gdd    = max(0.0, current_temp_avg - base_temp)

    if daily_gdd < 0.5:
        return 999  # 온도 너무 낮음 → 추정 불가
    return math.ceil(remaining / daily_gdd)
