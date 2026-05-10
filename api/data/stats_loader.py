"""
api/data/stats_loader.py

기초자료에서 추출된 JSON 통계를 로드하고 API 전반에서 사용할
정규화된 파라미터를 제공하는 단일 진입점.

scripts/extract_rda_stats.py    → price_stats.json, yield_stats.json, farm_registry.json
scripts/extract_cost_params.py  → cost_params.json
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).parent


# ── JSON 로더 (파일 없으면 빈 dict, 앱 기동 시 1회 캐싱) ─────────────────────

@lru_cache(maxsize=None)
def _load(filename: str) -> dict:
    path = _DATA_DIR / filename
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _price_data()   -> dict: return _load("price_stats.json")
def _yield_data()   -> dict: return _load("yield_stats.json")
def _cost_data()    -> dict: return _load("cost_params.json")
def _farm_registry() -> dict: return _load("farm_registry.json")


# ── 품목명 정규화 ─────────────────────────────────────────────────────────────
# 대시보드에서 영문 crop 코드를 한글 품목명으로 변환
# 수익 예측이 통계적으로 유효한 5개 작목 (농진청 5년 패널 n≥60 기준)
SUPPORTED_CROPS: list[str] = ["딸기", "방울토마토", "완숙토마토", "참외", "오이"]

CROP_KO: dict[str, str] = {
    "strawberry":    "딸기",
    "cherry_tomato": "방울토마토",
    "tomato":        "완숙토마토",
    "melon":         "참외",
    "cucumber":      "오이",
    # 한글 입력도 그대로 통과
    "딸기": "딸기", "방울토마토": "방울토마토", "완숙토마토": "완숙토마토",
    "참외": "참외", "오이": "오이",
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

# 데이터셋에 없는 품목을 위한 기본값 (원/kg)
_PRICE_DEFAULTS: dict[str, float] = {
    "딸기":      9800.0,
    "방울토마토": 4000.0,
    "완숙토마토": 2800.0,
    "참외":      3200.0,
    "오이":      1900.0,
}


def get_price_krw_kg(crop: str, percentile: str = "mean") -> float:
    """
    품목별 kg당 판매단가 반환.
    percentile: "mean" | "median" | "p25" | "p75"
    데이터 없으면 기본값 사용.
    """
    crop_ko = normalize_crop(crop)
    by_crop = _price_data().get("by_crop", {})
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
    "딸기":      3.2,   # kg/m²/작기
    "방울토마토": 15.0,
    "완숙토마토": 20.0,
    "참외":      17.0,
    "오이":      18.0,
}


def get_yield_kg_m2(crop: str, percentile: str = "avg") -> float:
    """
    품목별 작기당 kg/m² 수확량 반환.
    percentile: "avg" | "median" | "p25" | "p75"
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
    return float(stats.get(key_map.get(percentile, "avg_kg_m2_season"), stats["avg_kg_m2_season"]))


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
    price    = get_price_krw_kg(crop, price_pct)
    yield_m2 = get_yield_kg_m2(crop)
    total_kg = yield_m2 * area_m2

    # 비용: 수익의 약 38% (농가경영정보 기준 전기+비료+기타 비중)
    cost_ratio    = 0.38
    gross_revenue = total_kg * price
    estimated_cost = gross_revenue * cost_ratio

    return {
        "predicted_yield_kg":  round(total_kg, 1),
        "yield_per_m2":        round(yield_m2, 2),
        "price_krw_kg":        round(price, 0),
        "gross_revenue_krw":   round(gross_revenue, 0),
        "estimated_cost_krw":  round(estimated_cost, 0),
        "net_profit_krw":      round(gross_revenue - estimated_cost, 0),
        "data_source":         "rda_5yr_panel_2018_2022",
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

# 환경 파라미터 변경 → 수확량 변화율 (통계 기반 초기값, Phase 3에서 ML 모델로 교체)
_ENV_YIELD_SENSITIVITY: dict[str, dict] = {
    # param: {delta_unit: yield_change_ratio_per_unit}
    # 딸기 기준, 5년 패널 환경-수확량 상관 추정
    "temp_internal":  {"delta_1c_up": 0.012},   # 1°C 올리면 수확량 1.2% 증가 (최적 구간 기준)
    "humidity_int":   {"delta_5pct_up": 0.008}, # 5% 올리면 0.8% 증가
    "co2_ppm":        {"delta_100ppm_up": 0.025}, # 100ppm 올리면 2.5% 증가
    "solar_rad":      {"delta_50wm2_up": 0.015}, # 50W/m² 올리면 1.5% 증가
    "ec_dsm":         {"delta_0.5_up": 0.018},   # 0.5 dS/m 올리면 1.8% 증가
}


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

    sensitivity = _ENV_YIELD_SENSITIVITY.get(param, {})

    # 가장 적합한 감도 키 선택
    yield_ratio = 0.0
    for key, ratio in sensitivity.items():
        parts = key.split("_")
        if len(parts) >= 2:
            try:
                unit_delta = float(parts[1].replace("c", "").replace("pct", "").replace("ppm", "")
                                            .replace("wm2", "").replace("m2", ""))
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

# Phase 2에서 생육 데이터 조인 후 실측값으로 업데이트 예정
GDD_PARAMS: dict[str, dict] = {
    "딸기":      {"base_temp_c": 6.0,  "gdd_to_first_harvest": 450, "gdd_per_flush": 180, "season_weeks": 26},
    "방울토마토": {"base_temp_c": 10.0, "gdd_to_first_harvest": 600, "gdd_per_flush": 200, "season_weeks": 34},
    "완숙토마토": {"base_temp_c": 10.0, "gdd_to_first_harvest": 650, "gdd_per_flush": 220, "season_weeks": 34},
    "참외":      {"base_temp_c": 12.0, "gdd_to_first_harvest": 700, "gdd_per_flush": 240, "season_weeks": 20},
    "오이":      {"base_temp_c": 12.0, "gdd_to_first_harvest": 400, "gdd_per_flush": 150, "season_weeks": 20},
}


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
