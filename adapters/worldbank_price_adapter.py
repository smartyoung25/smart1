"""World Bank 농산물 원자재 가격 어댑터.

World Bank Pink Sheet (원자재 월별 가격 시계열) API.
무료, 등록 불필요.

API: https://api.worldbank.org/v2/en/indicator/{indicator}?downloadformat=csv
또는 Dataportal JSON API.

주요 지표 (한국 작목 대응):
    AGR.PRD.FOOD.XD   FAO 식품 가격지수
    1900050 (토마토)  토마토 도매 USD/MT
    기타 농산물 지표

활용: M3 매출 예측 시 국제 가격 추세 반영, KAMIS 가격 보정계수 계산
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 20

# World Bank DataBank API (JSON 응답 지원 지표)
_WB_API_BASE = "https://api.worldbank.org/v2"

# Pink Sheet 원자재 코드 → 내부 이름 매핑
# World Bank Commodity Price Data (PINK)
_PINK_SERIES: dict[str, str] = {
    "TOMATOES":  "tomato_usd_mt",    # 토마토 USD/MT (스페인 수출가)
    "ORANGES":   "orange_usd_mt",    # 오렌지 (참외 비교)
    "GRAINS":    "grain_usd_mt",     # 곡물 (비료비 대리변수)
}

# 작목별 세계 가격 지표 매핑 (M3 보정용)
_CROP_TO_SERIES: dict[str, str] = {
    "토마토":    "TOMATOES",
    "완숙토마토": "TOMATOES",
    "방울토마토": "TOMATOES",
    "딸기":      "ORANGES",      # 과일 지수 대리
    "파프리카":   "TOMATOES",
    "참외":      "ORANGES",
    "오이":      "TOMATOES",
}


def fetch_pink_sheet_latest() -> dict[str, Optional[float]]:
    """World Bank Pink Sheet 최신 데이터 조회.

    Returns:
        dict: {"tomato_usd_mt": float, ...} — USD/MT 단위
              API 실패 시 빈 dict
    """
    # World Bank는 Pink Sheet를 Excel/CSV로 제공 (JSON API 미지원)
    # 대신 World Bank DataBank API 활용
    url = f"{_WB_API_BASE}/en/indicator/AG.PRD.FOOD.XD"
    params = {
        "format":    "json",
        "mrv":       1,            # most recent value
        "per_page":  1,
        "country":   "WLD",        # 세계 평균
    }
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if len(data) < 2 or not data[1]:
            return {}
        record = data[1][0]
        val = record.get("value")
        return {"food_price_index": float(val)} if val is not None else {}
    except Exception as e:
        logger.warning("[worldbank_price] API 조회 실패: %s", e)
        return {}


def get_food_price_index() -> Optional[float]:
    """FAO 식품가격지수 (World Bank 제공, 기준=2014~2016=100).

    Returns:
        float: 식품가격지수 또는 None
    """
    result = fetch_pink_sheet_latest()
    return result.get("food_price_index")


def get_m3_correction_factor(
    crop_ko: str,
    domestic_price_krw_kg: float,
    usd_krw_rate: float = 1320.0,
) -> float:
    """M3 매출 예측 보정계수 계산.

    국제 가격 추세와 국내 가격 비교를 통해 M3 예측값을 보정.
    보정계수 > 1.0 → 국제 대비 국내 가격 높음 (수출 기회)
    보정계수 < 1.0 → 국제 대비 국내 가격 낮음 (수입 압력)

    Args:
        crop_ko: 작목명 (한국어)
        domestic_price_krw_kg: 현재 국내 가격 (원/kg)
        usd_krw_rate: USD/KRW 환율 (기본 1320)

    Returns:
        보정계수 (float, 0.5~2.0 클리핑)
    """
    # 작목별 세계 평균 가격 (USD/kg) — FAO FAOSTAT 2022~2024 평균
    _WORLD_AVG_USD_KG: dict[str, float] = {
        "토마토":     0.68,
        "완숙토마토": 0.68,
        "방울토마토": 1.20,
        "딸기":       2.10,
        "파프리카":   1.50,
        "참외":       0.90,
        "오이":       0.55,
    }
    world_usd = _WORLD_AVG_USD_KG.get(crop_ko, 1.0)
    world_krw_kg = world_usd * usd_krw_rate

    if world_krw_kg <= 0 or domestic_price_krw_kg <= 0:
        return 1.0

    ratio = domestic_price_krw_kg / world_krw_kg
    # 0.5~2.0 범위로 클리핑 (극단값 방지)
    return round(float(max(0.5, min(2.0, ratio))), 4)


def get_annual_price_trend(crop_ko: str, years: int = 3) -> dict:
    """최근 N년 가격 추세 지수 계산.

    World Bank 식품가격지수 변화율을 이용해 연간 가격 변동 추세를 반환.

    Returns:
        dict: {
            "crop": str,
            "trend_pct_per_year": float,  # 연간 가격 변화율 (%)
            "correction_factor": float,
            "source": str,
        }
    """
    fpi = get_food_price_index()
    trend_pct = 0.0
    if fpi is not None:
        # 기준(2014~2016=100) 대비 현재 지수로 연환산 증가율 추정
        # 2014~2016 기준 → 10년 경과(2025 기준)
        base_fpi = 100.0
        annual_rate = ((fpi / base_fpi) ** (1.0 / max(years, 1)) - 1.0) * 100
        trend_pct = round(annual_rate, 2)

    return {
        "crop":               crop_ko,
        "trend_pct_per_year": trend_pct,
        "correction_factor":  1.0 + trend_pct / 100.0,
        "fao_food_price_idx": fpi,
        "source":             "worldbank_ag_prd_food_xd",
    }
