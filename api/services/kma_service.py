"""기상청 ASOS 일별 기상 데이터 서비스.

API: https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList
인증: 공공데이터포털 서비스키 (serviceKey)

농가별 최인접 ASOS 관측소 매핑 → 최근 1일 데이터 조회 → 1시간 캐시.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

# ── 공공데이터포털 서비스키 (환경변수 KMA_SERVICE_KEY 에서 동적 로드) ──────────────
def _get_service_key() -> str:
    """호출 시점마다 os.environ을 재조회 — load_dotenv() 타이밍 문제 회피."""
    return os.environ.get("KMA_SERVICE_KEY", "")

_BASE_URL = "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"

# ── 농가 → ASOS 관측소 ID 매핑 ───────────────────────────────────────────────
# 관측소 번호: https://www.kma.go.kr/ASOS (종관기상관측)
FARM_STATION: dict[str, int] = {
    "farm_001": 189,   # 동서 오이 농장 (경남 창녕군) → 합천 189
    "farm_002": 127,   # 청풍 토마토 (충북 청풍) → 충주 127
    "farm_003": 140,   # 한솔 딸기 (전북 군산) → 군산 140
    "farm_004": 136,   # 대원 토마토 (경북 상주) → 상주 136
    "farm_005": 108,   # 농가 E → 서울 108 (기본)
}

# ── 인메모리 캐시 (farm_id → {data, fetched_at}) ───────────────────────────
_cache: dict[str, dict] = {}
_cache_lock = Lock()
_CACHE_TTL_SECONDS = 3600   # 1시간


def _is_fresh(farm_id: str) -> bool:
    entry = _cache.get(farm_id)
    if not entry:
        return False
    age = (datetime.now(tz=timezone.utc) - entry["fetched_at"]).total_seconds()
    return age < _CACHE_TTL_SECONDS


def _fetch_asos(station_id: int, obs_date: date) -> Optional[dict]:
    """ASOS API 호출 → item dict 1건 반환 (최신 1일)."""
    svc_key = _get_service_key()
    if not svc_key:
        logger.warning("[kma_service] KMA_SERVICE_KEY 미설정 — ASOS 조회 비활성화")
        return None
    date_str = obs_date.strftime("%Y%m%d")
    params = urllib.parse.urlencode({
        "serviceKey": svc_key,
        "pageNo": 1,
        "numOfRows": 1,
        "dataType": "JSON",
        "dataCd": "ASOS",
        "dateCd": "DAY",
        "startDt": date_str,
        "endDt": date_str,
        "stnIds": station_id,
    })
    url = f"{_BASE_URL}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        result_code = body["response"]["header"]["resultCode"]
        if result_code != "00":
            logger.warning("[kma_service] ASOS resultCode=%s station=%s", result_code, station_id)
            return None
        items = body["response"]["body"]["items"]["item"]
        return items[0] if items else None
    except Exception as exc:
        logger.error("[kma_service] ASOS fetch error station=%s: %s", station_id, exc)
        return None


def get_latest_weather(farm_id: str) -> Optional[dict]:
    """농가 ID → 최근 ASOS 기상 데이터 dict (캐시 우선).

    Returns:
        ASOS item dict or None (API 오류 or 관측소 미등록)
    """
    with _cache_lock:
        if _is_fresh(farm_id):
            logger.debug("[kma_service] cache hit farm=%s", farm_id)
            return _cache[farm_id]["data"]

    station_id = FARM_STATION.get(farm_id)
    if station_id is None:
        logger.warning("[kma_service] no station mapping for farm=%s", farm_id)
        return None

    # 어제 날짜 (오늘 데이터는 당일 오후 이전에는 미확정)
    yesterday = date.today() - timedelta(days=1)
    item = _fetch_asos(station_id, yesterday)

    # 어제 데이터 없으면 이틀 전 시도
    if item is None:
        two_days_ago = date.today() - timedelta(days=2)
        logger.info("[kma_service] retry with %s station=%s", two_days_ago, station_id)
        item = _fetch_asos(station_id, two_days_ago)

    with _cache_lock:
        _cache[farm_id] = {
            "data": item,
            "fetched_at": datetime.now(tz=timezone.utc),
        }

    if item:
        logger.info(
            "[kma_service] fetched ASOS farm=%s station=%s date=%s avgTa=%s",
            farm_id, station_id, item.get("tm"), item.get("avgTa"),
        )
    return item


def get_solar_irrigation_schedule(
    farm_id: str,
    trigger_mj_m2: float = 2.0,
    supply_ml_per_trigger: float = 250.0,
    min_irrigations: int = 2,
    max_irrigations: int = 12,
) -> dict:
    """KMA ASOS 일사량 기반 내일 관수 스케줄 예측 (Priva 일사비례 방식).

    Priva 일사비례 관수 원칙:
      - 누적 일사량 trigger_mj_m2 (기본 2 MJ/m²) 도달 시 1회 관수
      - 전일 sumGsr(MJ/m²)을 내일 예보값으로 사용 (단순 지속성 예측)
      - 첫 관수: 일출 후 30분, 마지막 관수: 일몰 2시간 전까지

    Args:
        farm_id:               농가 ID (FARM_STATION 매핑)
        trigger_mj_m2:         관수 트리거 일사량 임계값 (MJ/m²)
        supply_ml_per_trigger: 1회 관수량 (ml/slab)
        min_irrigations:       최소 관수 횟수 (흐린 날 보호)
        max_irrigations:       최대 관수 횟수 (맑은 날 제한)

    Returns:
        dict with keys:
          daily_gsr_mj_m2       - 전일 누적 일사량 (MJ/m²)
          solar_rad_avg_wm2     - 평균 일사량 추정 (W/m²)
          n_irrigations         - 권장 관수 횟수
          total_supply_ml       - 권장 총 공급량 (ml/slab)
          first_irrigation      - 첫 관수 예상 시각 "HH:MM"
          last_irrigation       - 마지막 관수 예상 시각 "HH:MM"
          trigger_mj_m2         - 사용된 트리거 임계값
          obs_date              - 참조 날짜 (어제)
          source                - 데이터 출처
          note                  - 상태 메모
    """
    import math as _math
    import datetime as _dt

    item = get_latest_weather(farm_id)
    today = _dt.date.today()

    # ── 일사량 파싱 ──────────────────────────────────────────────────────────
    gsr_mj: Optional[float] = None
    solar_avg: Optional[float] = None
    if item:
        try:
            raw_gsr = float(item.get("sumGsr", 0) or 0)
            if raw_gsr > 0:
                gsr_mj    = round(raw_gsr, 2)
                solar_avg = round(raw_gsr * 11.574, 1)  # MJ/m²/day → W/m² 일평균
        except (TypeError, ValueError):
            pass
        if gsr_mj is None:
            try:
                peak = float(item.get("hr1MaxIcsr", 0) or 0)
                if peak > 0:
                    solar_avg = round(peak * 0.40, 1)
                    # W/m² 일평균 → MJ/m²/day (역산)
                    gsr_mj = round(solar_avg / 11.574, 2)
            except (TypeError, ValueError):
                pass

    # 데이터 없을 때 계절 평균 fallback (한국 스마트팜 기준)
    if gsr_mj is None:
        month = today.month
        _MONTHLY_GSR = {
            1: 7.5, 2: 9.8, 3: 12.5, 4: 15.0, 5: 16.5, 6: 15.8,
            7: 13.2, 8: 14.0, 9: 13.0, 10: 11.5, 11: 8.5, 12: 7.0
        }
        gsr_mj    = _MONTHLY_GSR.get(month, 12.0)
        solar_avg = round(gsr_mj * 11.574, 1)
        note      = f"ASOS 데이터 없음 — {month}월 계절 평균 사용"
        source    = "seasonal_average"
    else:
        note   = f"전일({item.get('tm','?')}) ASOS 실측값 기반 단순 지속성 예측"
        source = "kma_asos_yesterday"

    # ── 관수 횟수 산출 ────────────────────────────────────────────────────────
    n_raw = gsr_mj / trigger_mj_m2
    n_irr = max(min_irrigations, min(max_irrigations, round(n_raw)))

    # ── 관수 시각 분포 계산 ───────────────────────────────────────────────────
    # 일출/일몰 시각 추정 (한국 36.5°N 기준)
    month_now = today.month
    _SUNRISE_H = {1: 7.5, 2: 7.1, 3: 6.5, 4: 5.7, 5: 5.2, 6: 5.0,
                  7: 5.2, 8: 5.5, 9: 6.0, 10: 6.4, 11: 7.0, 12: 7.5}
    _SUNSET_H  = {1: 17.5, 2: 18.2, 3: 18.8, 4: 19.5, 5: 20.0, 6: 20.3,
                  7: 20.2, 8: 19.7, 9: 18.8, 10: 18.0, 11: 17.3, 12: 17.2}
    sunrise = _SUNRISE_H.get(month_now, 6.5)
    sunset  = _SUNSET_H.get(month_now, 18.5)

    # 첫 관수: 일출 + 30분, 마지막 관수: 일몰 - 2시간
    first_h = sunrise + 0.5
    last_h  = sunset  - 2.0
    last_h  = max(first_h + 1.0, last_h)

    def _hm(h: float) -> str:
        return f"{int(h):02d}:{int(round((h % 1) * 60)):02d}"

    total_supply = round(n_irr * supply_ml_per_trigger, 0)

    return {
        "daily_gsr_mj_m2":       gsr_mj,
        "solar_rad_avg_wm2":     solar_avg,
        "n_irrigations":         n_irr,
        "total_supply_ml":       total_supply,
        "supply_per_trigger_ml": supply_ml_per_trigger,
        "first_irrigation":      _hm(first_h),
        "last_irrigation":       _hm(last_h),
        "trigger_mj_m2":         trigger_mj_m2,
        "obs_date":              item.get("tm") if item else None,
        "station_id":            FARM_STATION.get(farm_id),
        "source":                source,
        "note":                  note,
    }


def get_weather_summary(farm_id: str) -> dict:
    """환경 엔드포인트용 요약 dict 반환.

    {
      "temp_external":  float | None,
      "humidity_ext":   float | None,
      "solar_rad_est":  float | None,   # W/m² 추정
      "soil_temp":      float | None,
      "wind_speed_ext": float | None,
      "obs_date":       str | None,
      "station_id":     int | None,
      "source":         "kma_asos",
    }
    """
    item = get_latest_weather(farm_id)
    if item is None:
        return {
            "temp_external": None, "humidity_ext": None,
            "solar_rad_est": None, "soil_temp": None,
            "wind_speed_ext": None, "obs_date": None,
            "station_id": FARM_STATION.get(farm_id),
            "source": "kma_asos",
        }

    def _f(key: str) -> Optional[float]:
        try:
            v = float(item[key])
            return v if v != 0.0 or item[key] != "" else None
        except (KeyError, TypeError, ValueError):
            return None

    # 일사량 추정 (hr1MaxIcsr 우선, 없으면 sumGsr 환산)
    solar: Optional[float] = None
    peak = _f("hr1MaxIcsr")
    if peak and peak > 0:
        solar = round(peak * 0.40, 1)
    else:
        gsr = _f("sumGsr")
        if gsr and gsr > 0:
            solar = round(gsr * 11.574, 1)

    return {
        "temp_external":  _f("avgTa"),
        "humidity_ext":   _f("avgRhm"),
        "solar_rad_est":  solar,
        "soil_temp":      _f("avgTs"),
        "wind_speed_ext": _f("avgWs"),
        "obs_date":       item.get("tm"),
        "station_id":     FARM_STATION.get(farm_id),
        "source":         "kma_asos",
    }
