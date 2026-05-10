"""기상청 ASOS 일별 기상 데이터 서비스.

API: https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList
인증: 공공데이터포털 서비스키 (serviceKey)

농가별 최인접 ASOS 관측소 매핑 → 최근 1일 데이터 조회 → 1시간 캐시.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

# ── 공공데이터포털 서비스키 ─────────────────────────────────────────────────────
_SERVICE_KEY = "4b29046adc7addec95af1d13878fc4d2c6c26ed3b094ebf5a29a596a54755a96"
_BASE_URL = "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"

# ── 농가 → ASOS 관측소 ID 매핑 ───────────────────────────────────────────────
# 관측소 번호: https://www.kma.go.kr/ASOS (종관기상관측)
FARM_STATION: dict[str, int] = {
    "farm_001": 155,   # 이암허브 (경남 이암면) → 마산 155
    "farm_002": 127,   # 청풍 토마토 (충북 청풍) → 충주 127
    "farm_003": 140,   # 한솔 딸기 (전북) → 군산 140
    "farm_004": 143,   # 대원 파프리카 → 대구 143
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
    date_str = obs_date.strftime("%Y%m%d")
    params = urllib.parse.urlencode({
        "serviceKey": _SERVICE_KEY,
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
