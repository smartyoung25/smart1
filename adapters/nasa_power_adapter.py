"""NASA POWER API 어댑터 — 글로벌 태양복사량·기온 이력 데이터.

무료, 등록 불필요. 전세계 0.5°×0.625° 해상도, 1984년~현재.
한국 스마트팜 위치 기준 위도 36.5, 경도 127.5 기본값.

주요 파라미터:
    ALLSKY_SFC_SW_DWN  전천일사량 (W/m²) → ET₀ Hargreaves 보완
    T2M                2m 기온 (°C) → 외기온도 기준
    T2M_MAX / T2M_MIN  일최고·최저기온 (°C)
    PRECTOTCORR        강수량 (mm/day)
    RH2M               2m 상대습도 (%)

NASA POWER LARC Documentation: https://power.larc.nasa.gov/docs/
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
_TIMEOUT  = 30          # seconds
_MAX_DAYS = 366         # 단일 요청 최대 기간

# 한국 스마트팜 기본 좌표 (중부 지방 기준)
_KR_LAT_DEFAULT = 36.5
_KR_LON_DEFAULT = 127.5

# NASA POWER 파라미터 → 내부 컬럼명 매핑
_PARAM_MAP = {
    "ALLSKY_SFC_SW_DWN": "solar_rad",    # W/m²
    "T2M":               "temp_external", # °C
    "T2M_MAX":           "temp_ext_max",  # °C
    "T2M_MIN":           "temp_ext_min",  # °C
    "PRECTOTCORR":       "precip_mm",     # mm/day
    "RH2M":              "humidity_ext",  # %
    "WS2M":              "wind_speed",    # m/s
}


def fetch_nasa_power(
    lat: float = _KR_LAT_DEFAULT,
    lon: float = _KR_LON_DEFAULT,
    start: Optional[date] = None,
    end: Optional[date] = None,
    parameters: Optional[list[str]] = None,
) -> list[dict]:
    """NASA POWER API에서 일별 기상 데이터를 조회한다.

    Args:
        lat: 위도 (기본: 한국 중부 36.5)
        lon: 경도 (기본: 한국 중부 127.5)
        start: 조회 시작일 (기본: 30일 전)
        end: 조회 종료일 (기본: 오늘)
        parameters: 조회 파라미터 목록 (기본: 전체)

    Returns:
        list of dict: [{"date": "YYYYMMDD", "solar_rad": ..., "temp_external": ..., ...}]
        빈 리스트: API 오류 또는 네트워크 실패
    """
    if end is None:
        end = date.today()
    if start is None:
        start = end - timedelta(days=30)
    if parameters is None:
        parameters = list(_PARAM_MAP.keys())

    # 최대 기간 분할 (API 제한)
    results: list[dict] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=_MAX_DAYS - 1), end)
        chunk = _fetch_chunk(lat, lon, cur, chunk_end, parameters)
        results.extend(chunk)
        cur = chunk_end + timedelta(days=1)

    return results


def _fetch_chunk(
    lat: float,
    lon: float,
    start: date,
    end: date,
    parameters: list[str],
) -> list[dict]:
    """단일 청크(≤366일) 요청."""
    params = {
        "parameters": ",".join(parameters),
        "community":  "AG",       # Agriculture community
        "longitude":  lon,
        "latitude":   lat,
        "start":      start.strftime("%Y%m%d"),
        "end":        end.strftime("%Y%m%d"),
        "format":     "JSON",
    }
    try:
        resp = requests.get(_BASE_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("[nasa_power] API 요청 실패: %s", e)
        return []
    except Exception as e:
        logger.warning("[nasa_power] 응답 파싱 실패: %s", e)
        return []

    properties = data.get("properties", {})
    param_data  = properties.get("parameter", {})
    if not param_data:
        logger.warning("[nasa_power] 빈 응답 (좌표: %.2f, %.2f)", lat, lon)
        return []

    # 날짜 집합 구성
    first_param = next(iter(param_data.values()), {})
    dates = sorted(first_param.keys())

    rows = []
    for d in dates:
        row: dict = {"date": d}
        for nasa_key, col_name in _PARAM_MAP.items():
            if nasa_key in param_data:
                val = param_data[nasa_key].get(d)
                # NASA POWER 결측: -999
                row[col_name] = float(val) if val is not None and float(val) > -990 else None
        rows.append(row)

    logger.info("[nasa_power] %d건 수신 (%.2f°N, %.2f°E, %s~%s)",
                len(rows), lat, lon, start, end)
    return rows


def get_monthly_avg(
    lat: float = _KR_LAT_DEFAULT,
    lon: float = _KR_LON_DEFAULT,
    year: int = 2024,
    month: int = 1,
) -> dict:
    """특정 월 평균값 조회 (M1/M2 학습 피처 보강용).

    Returns:
        dict: {"solar_rad": float, "temp_external": float, ...}
              실패 시 빈 dict
    """
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    start = date(year, month, 1)
    end   = date(year, month, last_day)

    rows = fetch_nasa_power(lat, lon, start, end)
    if not rows:
        return {}

    # 컬럼별 평균 (None 제외)
    result: dict[str, float] = {}
    import statistics
    for col in ["solar_rad", "temp_external", "temp_ext_max", "temp_ext_min",
                "precip_mm", "humidity_ext", "wind_speed"]:
        vals = [r[col] for r in rows if r.get(col) is not None]
        if vals:
            result[col] = round(statistics.mean(vals), 3)

    return result


def calc_et0_hargreaves_nasa(
    lat: float = _KR_LAT_DEFAULT,
    lon: float = _KR_LON_DEFAULT,
    target_date: Optional[date] = None,
) -> Optional[float]:
    """NASA POWER 데이터 기반 Hargreaves-Samani ET₀ 계산 (mm/day).

    ET₀ = 0.0023 × (T_mean + 17.8) × (T_max - T_min)^0.5 × Ra
    Ra (외계복사량): NASA solar_rad에서 추정

    Returns:
        ET₀ (mm/day) 또는 None (데이터 없음)
    """
    if target_date is None:
        target_date = date.today()

    rows = fetch_nasa_power(lat, lon, target_date, target_date,
                            ["T2M", "T2M_MAX", "T2M_MIN", "ALLSKY_SFC_SW_DWN"])
    if not rows:
        return None

    r = rows[0]
    t_mean = r.get("temp_external")
    t_max  = r.get("temp_ext_max")
    t_min  = r.get("temp_ext_min")
    ra     = r.get("solar_rad")  # W/m² → MJ/m²/day 변환 필요

    if any(v is None for v in [t_mean, t_max, t_min, ra]):
        return None

    # W/m² → MJ/m²/day: × 0.0864 (= 3600×24/1,000,000)
    ra_mj = ra * 0.0864
    td = t_max - t_min
    if td < 0:
        return None

    et0 = 0.0023 * (t_mean + 17.8) * (td ** 0.5) * ra_mj
    return round(max(0.0, et0), 3)
