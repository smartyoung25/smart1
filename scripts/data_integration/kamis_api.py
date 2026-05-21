"""KAMIS 농산물유통정보 가격 API 클라이언트.

농산물 가격 데이터를 수익 최적화 엔진에 공급.

API 정보:
  제공처: 한국농수산식품유통공사(aT)
  URL:    https://www.kamis.or.kr/customer/reference/openapi_list.do
  인증:   무료 회원가입 후 API 키 발급

환경변수 설정:
  KAMIS_API_KEY=your_api_key   # .env 파일에 추가

사용법:
  from scripts.data_integration.kamis_api import KamisPriceClient
  client = KamisPriceClient(api_key="your_key")
  price = client.get_current_price("딸기")           # 현재 도매가 (원/kg)
  monthly = client.get_monthly_prices("파프리카", year=2025)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

logger = logging.getLogger(__name__)

# KAMIS 품목 코드
_CROP_CODES = {
    "딸기":       "223",
    "방울토마토": "242",
    "완숙토마토": "241",
    "참외":       "225",
    "파프리카":   "247",
    "토마토":     "241",
}
# 도매 단위 → kg 환산 계수
_UNIT_TO_KG = {
    "kg":  1.0,
    "10kg": 10.0,
    "4kg":  4.0,
    "2kg":  2.0,
    "1kg":  1.0,
    "500g": 0.5,
    "300g": 0.3,
}
_KAMIS_BASE = "http://www.kamis.or.kr/service/price/xml.do"
_KAMIS_MONTHLY = "http://www.kamis.or.kr/service/price/xml.do"


class KamisPriceClient:
    """KAMIS 가격 API 클라이언트.

    API 키 없이도 캐시된 가격 테이블을 사용 (stub 모드).
    API 키가 있으면 실시간 가격 조회.
    """

    # 작목별 기본 도매가 (원/kg) — API 키 없을 때 사용하는 stub 가격
    _STUB_PRICES: dict[str, float] = {
        "딸기":       12000.0,   # 도매 기준 약 12,000원/kg
        "방울토마토":  4500.0,
        "완숙토마토":  2800.0,
        "참외":        3500.0,
        "파프리카":    4200.0,
    }
    # 연도별 물가 보정 계수 (2020=1.0 기준)
    _INFLATION = {2020: 1.00, 2021: 1.05, 2022: 1.12, 2023: 1.18, 2024: 1.22, 2025: 1.25}

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        cache_ttl_days: int = 1,
    ):
        self.api_key = api_key or os.getenv("KAMIS_API_KEY")
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_ttl_days = cache_ttl_days
        self._stub_mode = not bool(self.api_key)
        if self._stub_mode:
            logger.debug("[KAMIS] API 키 없음 — stub 가격 사용 (KAMIS_API_KEY 환경변수 설정 필요)")

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def get_current_price(
        self,
        crop_ko: str,
        unit: str = "kg",
    ) -> float:
        """현재 도매가격 조회 (원/kg).

        Args:
            crop_ko: 한국어 작목명
            unit: 반환 단위 ('kg' 고정, 내부에서 환산)

        Returns:
            가격 (원/kg)
        """
        if self._stub_mode:
            return self._stub_price(crop_ko)

        try:
            today = date.today().strftime("%Y-%m-%d")
            data = self._call_api(
                action="dailySalesList",
                p_itemcategorycode="200",
                p_itemcode=_CROP_CODES.get(crop_ko, "241"),
                p_kindcode="01",
                p_productrankcode="04",    # 상품
                p_countrycode="",
                p_marketcode="110001",     # 서울 가락시장
                p_startday=today,
                p_endday=today,
                p_convert_kg_yn="Y",       # kg 단위 환산 요청
            )
            price = self._parse_price(data)
            if price > 0:
                logger.debug("[KAMIS] %s 현재가: %.0f원/kg", crop_ko, price)
                return price
        except Exception as e:
            logger.warning("[KAMIS] API 오류(%s), stub 사용: %s", crop_ko, e)

        return self._stub_price(crop_ko)

    def get_monthly_prices(
        self,
        crop_ko: str,
        year: Optional[int] = None,
    ) -> pd.DataFrame:
        """연간 월별 가격 추이 조회.

        Returns:
            DataFrame: month(1~12), price_krw_per_kg, year
        """
        year = year or date.today().year

        if self._stub_mode:
            return self._stub_monthly(crop_ko, year)

        try:
            data = self._call_api(
                action="monthlySalesList",
                p_itemcategorycode="200",
                p_itemcode=_CROP_CODES.get(crop_ko, "241"),
                p_year=str(year),
                p_convert_kg_yn="Y",
            )
            return self._parse_monthly(data, crop_ko, year)
        except Exception as e:
            logger.warning("[KAMIS] 월별 조회 오류(%s), stub 사용: %s", crop_ko, e)
            return self._stub_monthly(crop_ko, year)

    def get_price_series(
        self,
        crop_ko: str,
        start_year: int = 2020,
        end_year: Optional[int] = None,
    ) -> pd.DataFrame:
        """다년도 월별 가격 시계열 반환.

        Returns:
            DataFrame: year, month, price_krw_per_kg
        """
        end_year = end_year or date.today().year
        frames = []
        for y in range(start_year, end_year + 1):
            df = self.get_monthly_prices(crop_ko, y)
            if not df.empty:
                frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def enrich_production(
        self,
        df_prod: pd.DataFrame,
        crop_ko: str,
    ) -> pd.DataFrame:
        """생산 DataFrame에 가격 컬럼 추가.

        df_prod 필수 컬럼: year, month, yield_kg
        추가 컬럼: price_krw_per_kg, revenue_krw
        """
        if df_prod.empty:
            return df_prod

        result = df_prod.copy()
        min_year = int(result["year"].min()) if "year" in result.columns else 2020
        max_year = int(result["year"].max()) if "year" in result.columns else date.today().year
        price_df = self.get_price_series(crop_ko, min_year, max_year)

        if not price_df.empty and "year" in result.columns and "month" in result.columns:
            result = result.merge(
                price_df[["year", "month", "price_krw_per_kg"]],
                on=["year", "month"], how="left",
            )
        else:
            result["price_krw_per_kg"] = self.get_current_price(crop_ko)

        result["price_krw_per_kg"] = result["price_krw_per_kg"].fillna(
            self._stub_price(crop_ko)
        )
        if "yield_kg" in result.columns:
            result["revenue_krw"] = result["yield_kg"] * result["price_krw_per_kg"]

        return result

    # ── 내부 메서드 ───────────────────────────────────────────────────────────

    def _stub_price(self, crop_ko: str) -> float:
        """API 키 없을 때 기본 가격 반환 (최신 물가 보정 적용)."""
        base = self._STUB_PRICES.get(crop_ko, 5000.0)
        current_year = date.today().year
        inflator = self._INFLATION.get(current_year,
                                        list(self._INFLATION.values())[-1])
        return base * inflator

    def _stub_monthly(self, crop_ko: str, year: int) -> pd.DataFrame:
        """계절성 반영 stub 월별 가격 (실측 기반 근사)."""
        base = self._stub_price(crop_ko)
        # 작목별 계절성 지수 (1.0 = 평균)
        seasonal = {
            "딸기": [1.6, 1.4, 1.1, 0.9, 0.7, 0.5, 0.5, 0.6, 0.9, 1.2, 1.5, 1.7],
            "방울토마토": [1.3, 1.2, 1.0, 0.9, 0.8, 0.7, 0.9, 1.1, 1.0, 0.9, 1.1, 1.2],
            "완숙토마토": [1.2, 1.1, 1.0, 0.9, 0.8, 0.8, 0.9, 1.0, 0.9, 0.9, 1.0, 1.1],
            "참외": [0.6, 0.7, 0.9, 1.3, 1.6, 1.5, 1.2, 1.0, 0.9, 0.7, 0.6, 0.6],
            "파프리카": [1.2, 1.2, 1.1, 1.0, 0.9, 0.8, 0.8, 0.9, 1.0, 1.1, 1.2, 1.2],
        }
        factors = seasonal.get(crop_ko, [1.0] * 12)
        return pd.DataFrame({
            "year":  [year] * 12,
            "month": list(range(1, 13)),
            "price_krw_per_kg": [round(base * f, 0) for f in factors],
            "source": "stub_seasonal",
        })

    def _call_api(self, action: str, **params) -> dict:
        """KAMIS API 호출 → JSON 반환."""
        params.update({
            "action": action,
            "p_cert_key": self.api_key,
            "p_cert_id":  "7000000",     # 공공 ID
            "p_returntype": "json",
        })
        url = f"{_KAMIS_BASE}?{urlencode(params)}"

        # 캐시 확인
        if self.cache_dir:
            cache_key = abs(hash(url)) % 100000
            cache_path = self.cache_dir / f"kamis_{cache_key}.json"
            if cache_path.exists():
                age = (datetime.now() -
                       datetime.fromtimestamp(cache_path.stat().st_mtime)).days
                if age < self.cache_ttl_days:
                    return json.loads(cache_path.read_text(encoding="utf-8"))

        with urlopen(url, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)

        # 캐시 저장
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        return data

    def _parse_price(self, data: dict) -> float:
        try:
            items = data["data"]["item"]
            if isinstance(items, list):
                item = items[0]
            else:
                item = items
            price_str = str(item.get("price", "0")).replace(",", "")
            return float(price_str) if price_str.replace(".", "").isdigit() else 0.0
        except (KeyError, IndexError, TypeError):
            return 0.0

    def _parse_monthly(self, data: dict, crop_ko: str, year: int) -> pd.DataFrame:
        try:
            items = data["data"]["item"]
            if not isinstance(items, list):
                items = [items]
            rows = []
            for item in items:
                m = int(item.get("month", 0))
                p_str = str(item.get("price", "0")).replace(",", "")
                p = float(p_str) if p_str.replace(".", "").isdigit() else 0.0
                if m > 0 and p > 0:
                    rows.append({"year": year, "month": m, "price_krw_per_kg": p})
            return pd.DataFrame(rows)
        except (KeyError, TypeError):
            return pd.DataFrame()


# ── 편의 함수 ─────────────────────────────────────────────────────────────────

_default_client: Optional[KamisPriceClient] = None


def get_price(crop_ko: str) -> float:
    """현재 가격 (원/kg) — 기본 클라이언트 사용."""
    global _default_client
    if _default_client is None:
        _default_client = KamisPriceClient()
    return _default_client.get_current_price(crop_ko)


def get_monthly_price_df(crop_ko: str, start_year: int = 2020) -> pd.DataFrame:
    """다년도 월별 가격 DataFrame."""
    global _default_client
    if _default_client is None:
        _default_client = KamisPriceClient()
    return _default_client.get_price_series(crop_ko, start_year)
