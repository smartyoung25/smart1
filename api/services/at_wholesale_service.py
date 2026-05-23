"""aT 농수산물유통공사 도매시장 가격 서비스.

M3 매출 예측 보완 — 완숙토마토 등 gate 미통과 작목의 가격 정확도 향상.

API 폴백 체인:
  ① aT ARTA 도매시장 거래 현황 API (공공데이터포털)
       https://www.data.go.kr/data/15025285/openapi.do
       인증: DATA_GO_KR_SERVICE_KEY (기존 키)
       반환: 품목별 일별 경락가격 (평균/최고/최저)

  ② KAMIS 농산물유통정보 (기존 연동)
       pipeline/kamis_fetcher.py get_price_with_fallback()

  ③ FAO FAOSTAT 월별 농산물 가격 (국제 기준, 무료)
       https://www.fao.org/faostat/en/#data
       Key: 불필요

  ④ stats_loader 정적 데이터 (최종 폴백)

수확량 기준 클리핑 (M2 과적합 보정):
  USDA NASS API — 작목별 수확량 합리적 범위 제공
       https://quickstats.nass.usda.gov/api
       Key: 무료 발급 (quickstats.nass.usda.gov/api → Request API Key)

반환 형식:
    {
      "crop": str,
      "price_krw_kg": float,
      "price_source":  str,
      "price_history": list[dict],   # 최근 30일
      "wholesale": {
          "avg": float, "min": float, "max": float, "latest": float
      },
      "yield_bounds": {
          "lower_kg_m2": float,      # USDA 기반 합리적 하한
          "upper_kg_m2": float,      # USDA 기반 합리적 상한
          "reference": str,
      },
      "m3_correction_factor": float, # 가격 보정 계수 (KAMIS/aT 대비)
    }
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)
_lock = Lock()
_cache: dict[str, tuple[dict, float]] = {}


def _data_go_key() -> str:
    return os.environ.get("DATA_GO_KR_SERVICE_KEY_DECODED",
           os.environ.get("DATA_GO_KR_SERVICE_KEY", ""))


def _usda_key() -> str:
    return os.environ.get("USDA_NASS_API_KEY", "")


def _cached(key: str, ttl: int, fn):
    with _lock:
        if key in _cache:
            d, exp = _cache[key]
            if time.time() < exp:
                return d
    try:
        d = fn()
        if d:
            with _lock:
                _cache[key] = (d, time.time() + ttl)
        return d
    except Exception as e:
        logger.warning("[at_wholesale] cache miss %s: %s", key, e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# ① aT ARTA 도매시장 경락가격 API
# ══════════════════════════════════════════════════════════════════════════════

# 품목 코드 (aT 도매시장 표준 코드)
_AT_ITEM_CODES: dict[str, tuple[str, str]] = {
    "딸기":       ("02", "0201"),  # 과채류 → 딸기
    "방울토마토": ("06", "0603"),  # 과채류 → 방울토마토
    "완숙토마토": ("06", "0601"),  # 과채류 → 토마토
    "파프리카":   ("06", "0631"),  # 과채류 → 파프리카
    "참외":       ("06", "0611"),  # 과채류 → 참외
    "오이":       ("06", "0602"),  # 과채류 → 오이
}

# 주요 도매시장 코드 (aT 표준)
_AT_MARKET_CODES = {
    "가락동": "110001",   # 서울 가락동 농수산물도매시장
    "강서":   "110002",   # 서울 강서농산물도매시장
    "부산":   "210001",   # 부산 엄궁농수산물도매시장
    "대구":   "310001",   # 대구 북부농수산물도매시장
}


def at_get_wholesale_price(
    crop_ko: str,
    market_code: str = "110001",
    days_back: int = 30,
) -> Optional[dict]:
    """aT 도매시장 경락가격 조회.

    공공데이터포털 aT 도매시장 경락가격정보 API:
      https://www.data.go.kr/data/15025285/openapi.do

    Args:
        crop_ko:     작목명 (한국어)
        market_code: 도매시장 코드 (기본: 가락동)
        days_back:   조회 기간 (일)

    Returns:
        {
          "crop": str,
          "market": str,
          "history": [{"date": str, "avg_price": float, "unit": str}, ...],
          "stats": {"avg": float, "min": float, "max": float, "latest": float},
          "source": "at_arta",
        }
    """
    key = _data_go_key()
    if not key:
        return None

    codes = _AT_ITEM_CODES.get(crop_ko)
    if not codes:
        return None

    item_code_main, item_code = codes

    def _fetch():
        end_dt   = date.today()
        start_dt = end_dt - timedelta(days=days_back)
        params = urllib.parse.urlencode({
            "serviceKey": key,
            "p_product_cls_code": "01",        # 도매
            "p_item_category_code": item_code_main,
            "p_item_code": item_code,
            "p_unit": "1",                      # kg
            "p_convert_kg_yn": "Y",
            "p_start_day": start_dt.strftime("%Y%m%d"),
            "p_end_day": end_dt.strftime("%Y%m%d"),
            "p_product_cls_name": "",
            "p_country_code": "",
            "p_regday": "",
            "p_cert_key": key,
            "p_cert_id": os.environ.get("KAMIS_API_ID", "pad_smartfarm"),
            "p_returntype": "json",
        })
        # aT KAMIS API (KAMIS는 aT 운영 — 동일 엔드포인트 활용)
        url = f"http://www.kamis.or.kr/service/price/xml.do?action=periodProductList&{params}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        data = raw.get("data", {})
        items = data.get("item", [])
        if isinstance(items, dict):
            items = [items]

        history = []
        for item in items:
            price_str = str(item.get("price", "0")).replace(",", "")
            try:
                price = float(price_str)
                if price > 0:
                    history.append({
                        "date":      item.get("regday", ""),
                        "avg_price": round(price, 0),
                        "unit":      "원/kg",
                        "source":    "kamis_at",
                    })
            except ValueError:
                pass

        if not history:
            return None

        prices = [h["avg_price"] for h in history]
        return {
            "crop":    crop_ko,
            "market":  market_code,
            "history": sorted(history, key=lambda x: x["date"]),
            "stats": {
                "avg":    round(sum(prices) / len(prices), 0),
                "min":    min(prices),
                "max":    max(prices),
                "latest": prices[-1] if prices else 0,
            },
            "source": "kamis_at_periodList",
        }

    return _cached(f"at_{crop_ko}_{market_code}_{days_back}", 3600, _fetch)


# ══════════════════════════════════════════════════════════════════════════════
# ③ FAO FAOSTAT 국제 가격 (무료, 키 불필요)
# ══════════════════════════════════════════════════════════════════════════════

# 한국 FAOSTAT 작목 코드
_FAO_ITEM_CODES: dict[str, int] = {
    "딸기":       388,   # Strawberries
    "방울토마토": 388,   # (토마토로 대체)
    "완숙토마토": 388,   # Tomatoes
    "파프리카":   401,   # Chillies and peppers
    "참외":       567,   # Cantaloupes and other melons
    "오이":       397,   # Cucumbers and gherkins
}


def fao_get_price_trend(crop_ko: str) -> Optional[dict]:
    """FAO FAOSTAT 한국 농산물 가격 데이터 (최근 5년 평균).

    FAOSTAT Prices domain:
      https://www.fao.org/faostat/en/#data/PP

    Args:
        crop_ko: 작목명

    Returns:
        {
          "crop": str,
          "annual_price_usd_tonne": float,
          "price_trend": list[dict],
          "source": "fao_faostat",
        }
    """
    item_code = _FAO_ITEM_CODES.get(crop_ko)
    if not item_code:
        return None

    def _fetch():
        params = urllib.parse.urlencode({
            "area": "116",           # Korea, Republic of
            "item": str(item_code),
            "element": "5532",       # Producer price (USD/tonne)
            "year": "2019,2020,2021,2022,2023",
            "output_type": "json",
        })
        url = f"https://fenix.fao.org/faostat/api/v1/en/data/PP?{params}"
        with urllib.request.urlopen(url, timeout=12) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        records = raw.get("data", [])
        trend = []
        prices = []
        for rec in records:
            val = rec.get("Value")
            if val:
                try:
                    p = float(val)
                    trend.append({"year": rec.get("Year"), "price_usd_tonne": p})
                    prices.append(p)
                except ValueError:
                    pass

        if not prices:
            return None

        avg = sum(prices) / len(prices)
        # USD/tonne → KRW/kg (환율 약 1350 기준)
        krw_kg = round(avg * 1350 / 1000, 0)
        return {
            "crop": crop_ko,
            "annual_price_usd_tonne": round(avg, 1),
            "annual_price_krw_kg": krw_kg,
            "price_trend": sorted(trend, key=lambda x: x["year"]),
            "source": "fao_faostat",
        }

    return _cached(f"fao_{crop_ko}", 86400 * 30, _fetch)


# ══════════════════════════════════════════════════════════════════════════════
# ④ USDA NASS 수확량 기준 데이터 (M2 클리핑용)
# ══════════════════════════════════════════════════════════════════════════════

# 한국 수확량 합리적 범위 (FAO/RDA 기준 — USDA 폴백 전 하드코딩 기준)
_KR_YIELD_BOUNDS: dict[str, dict] = {
    "딸기":       {"lower": 2.0,  "upper": 12.0,  "unit": "kg/m²/시즌", "ref": "RDA 2022"},
    "방울토마토": {"lower": 5.0,  "upper": 25.0,  "unit": "kg/m²/시즌", "ref": "RDA 2022"},
    "완숙토마토": {"lower": 8.0,  "upper": 30.0,  "unit": "kg/m²/시즌", "ref": "RDA 2022"},
    "파프리카":   {"lower": 8.0,  "upper": 20.0,  "unit": "kg/m²/시즌", "ref": "RDA 2021"},
    "참외":       {"lower": 3.0,  "upper": 12.0,  "unit": "kg/m²/시즌", "ref": "RDA 2022"},
    "오이":       {"lower": 15.0, "upper": 50.0,  "unit": "kg/m²/시즌", "ref": "RDA 2022"},
}


def usda_get_yield_reference(crop_ko: str) -> Optional[dict]:
    """USDA NASS API를 통해 작목별 수확량 기준 조회.

    USDA NASS Quick Stats API:
      https://quickstats.nass.usda.gov/api
      키 발급: https://quickstats.nass.usda.gov/api → Request API Key (무료)

    M2 과적합 모델 보정: 예측값이 합리적 범위를 벗어날 경우 클리핑.

    Returns:
        {
          "crop": str,
          "lower_kg_m2": float,
          "upper_kg_m2": float,
          "reference": str,
          "source": "usda_nass" | "rda_static",
        }
    """
    # 한국 기준값 우선 반환 (USDA는 미국 기준이므로 참고용)
    bounds = _KR_YIELD_BOUNDS.get(crop_ko)
    if bounds:
        result = {
            "crop":        crop_ko,
            "lower_kg_m2": bounds["lower"],
            "upper_kg_m2": bounds["upper"],
            "unit":        bounds["unit"],
            "reference":   bounds["ref"],
            "source":      "rda_static",
        }

        # USDA 보강 시도 (키 있을 때)
        usda_key = _usda_key()
        if usda_key:
            usda = _fetch_usda_yield(crop_ko, usda_key)
            if usda:
                result["usda_yield_cwt_acre"] = usda.get("yield_cwt_acre")
                result["usda_year"] = usda.get("year")
                result["source"] = "rda_static+usda_nass"

        return result

    return None


def _fetch_usda_yield(crop_ko: str, api_key: str) -> Optional[dict]:
    """USDA NASS Quick Stats에서 작목별 수확량 조회 (참고용)."""
    # 작목 → USDA 명칭 매핑
    _usda_names = {
        "딸기": "STRAWBERRIES",
        "방울토마토": "TOMATOES",
        "완숙토마토": "TOMATOES",
        "파프리카": "PEPPERS",
        "참외": "CANTALOUPES",
        "오이": "CUCUMBERS",
    }
    commodity = _usda_names.get(crop_ko)
    if not commodity:
        return None

    def _fetch():
        params = urllib.parse.urlencode({
            "key":          api_key,
            "commodity_desc": commodity,
            "statisticcat_desc": "YIELD",
            "unit_desc":    "CWT / ACRE",
            "year__GE":     "2020",
            "format":       "JSON",
        })
        url = f"https://quickstats.nass.usda.gov/api/api_GET/?{params}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        items = raw.get("data", [])
        if not items:
            return None
        latest = max(items, key=lambda x: x.get("year", 0))
        return {
            "commodity": commodity,
            "yield_cwt_acre": float(latest.get("Value", "0").replace(",", "") or "0"),
            "year": latest.get("year"),
            "source": "usda_nass",
        }

    return _cached(f"usda_{crop_ko}", 86400 * 7, _fetch)


def clip_yield_prediction(
    crop_ko: str,
    predicted_kg_m2: float,
) -> tuple[float, bool]:
    """M2 예측값을 합리적 범위로 클리핑.

    방울토마토 CV MAPE=231% 같은 과적합 모델의 이상 예측을 방지.

    Returns:
        (clipped_value, was_clipped)
    """
    bounds = _KR_YIELD_BOUNDS.get(crop_ko)
    if not bounds:
        return predicted_kg_m2, False

    lower = bounds["lower"]
    upper = bounds["upper"]

    if predicted_kg_m2 < lower:
        logger.info("[at_wholesale] M2 클리핑: %.2f → %.2f (하한 %s)",
                    predicted_kg_m2, lower, crop_ko)
        return lower, True
    if predicted_kg_m2 > upper:
        logger.info("[at_wholesale] M2 클리핑: %.2f → %.2f (상한 %s)",
                    predicted_kg_m2, upper, crop_ko)
        return upper, True

    return predicted_kg_m2, False


# ══════════════════════════════════════════════════════════════════════════════
# 통합 도매가격 + 수확량 기준 조회
# ══════════════════════════════════════════════════════════════════════════════

def get_market_data(
    crop_ko: str,
    market_code: str = "110001",
    days_back: int = 30,
) -> dict:
    """도매가격 + 수확량 기준 통합 반환.

    M3 완숙토마토 gate 미통과 보완용.
    """
    result: dict = {
        "crop":          crop_ko,
        "source_chain":  [],
    }

    # ① aT 도매시장 경락가격
    at_data = at_get_wholesale_price(crop_ko, market_code, days_back)
    if at_data:
        result["price_krw_kg"]   = at_data["stats"]["latest"] or at_data["stats"]["avg"]
        result["price_source"]   = "at_arta_kamis"
        result["price_history"]  = at_data["history"]
        result["wholesale"]      = at_data["stats"]
        result["source_chain"].append("at_arta_kamis")
    else:
        # ② KAMIS 폴백
        try:
            from pipeline.kamis_fetcher import get_price_with_fallback  # type: ignore
            kamis = get_price_with_fallback(crop_ko)
            result["price_krw_kg"]  = kamis["price_krw_kg"]
            result["price_source"]  = kamis["source"]
            result["price_history"] = []
            result["wholesale"]     = {"avg": kamis["price_krw_kg"], "min": 0, "max": 0, "latest": kamis["price_krw_kg"]}
            result["source_chain"].append(f"kamis_{kamis['source']}")
        except Exception:
            # ③ stats_loader 최종 폴백
            from api.data.stats_loader import get_price_krw_kg  # type: ignore
            p = get_price_krw_kg(crop_ko)
            result["price_krw_kg"]  = p
            result["price_source"]  = "rda_static"
            result["price_history"] = []
            result["wholesale"]     = {"avg": p, "min": 0, "max": 0, "latest": p}
            result["source_chain"].append("rda_static")

    # FAO 국제 가격 (참고용)
    fao = fao_get_price_trend(crop_ko)
    if fao:
        result["fao_ref_price_krw_kg"] = fao.get("annual_price_krw_kg")
        result["source_chain"].append("fao_faostat")

    # 수확량 기준 (M2 클리핑용)
    yield_bounds = usda_get_yield_reference(crop_ko)
    if yield_bounds:
        result["yield_bounds"] = {
            "lower_kg_m2": yield_bounds["lower_kg_m2"],
            "upper_kg_m2": yield_bounds["upper_kg_m2"],
            "reference":   yield_bounds["reference"],
            "source":      yield_bounds["source"],
        }

    # M3 가격 보정 계수 (현재 가격 대비 연간 평균)
    if fao and result.get("price_krw_kg") and fao.get("annual_price_krw_kg"):
        ratio = result["price_krw_kg"] / fao["annual_price_krw_kg"]
        result["m3_correction_factor"] = round(max(0.5, min(2.0, ratio)), 3)
    else:
        result["m3_correction_factor"] = 1.0

    return result


# ══════════════════════════════════════════════════════════════════════════════
# 키 발급 안내
# ══════════════════════════════════════════════════════════════════════════════

AT_WHOLESALE_KEY_GUIDE = {
    "service": "aT 농수산물유통공사 도매시장 경락가격",
    "used_for": "M3 완숙토마토 가격 예측 보완 (gate 미통과 작목)",
    "cost": "무료 (기존 DATA_GO_KR_SERVICE_KEY 사용)",
    "get_key_url": "https://www.data.go.kr/data/15025285/openapi.do",
    "env_var": "DATA_GO_KR_SERVICE_KEY",
    "note": "이미 설정된 경우 즉시 사용 가능",
}

USDA_NASS_KEY_GUIDE = {
    "service": "USDA NASS Quick Stats API (미국 농업통계)",
    "used_for": "M2 수확량 예측 이상값 클리핑 기준",
    "cost": "완전 무료",
    "get_key_url": "https://quickstats.nass.usda.gov/api",
    "setup_steps": [
        "1. https://quickstats.nass.usda.gov/api 접속",
        "2. 'Request API Key' 버튼 클릭",
        "3. 이메일 입력 → 즉시 발급",
        "4. .env 에 USDA_NASS_API_KEY=your_key 추가",
    ],
    "env_var": "USDA_NASS_API_KEY",
    "note": "한국 기준값(RDA)이 이미 내장되어 있어 키 없이도 클리핑 동작함",
}
