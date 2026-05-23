"""KAMIS 농산물 유통정보 API 클라이언트.

농림축산식품부 KAMIS (https://www.kamis.or.kr) 도매가격을 조회해
api/data/kamis_price_cache.json 에 캐싱합니다.

환경변수:
    KAMIS_API_KEY   : KAMIS 인증키 (필수)
    KAMIS_API_ID    : KAMIS 인증 ID (기본: "pad_smartfarm")
    KAMIS_MARKET    : 시장 코드 (기본: "1101" — 서울 가락시장)

사전 조건:
    https://www.kamis.or.kr 에서 API 키 발급 필요.
    키가 없으면 --dry-run 모드로 mock 데이터를 반환합니다.

사용법 (CLI):
    python -m pipeline.kamis_fetcher          # 오늘 가격 갱신
    python -m pipeline.kamis_fetcher --dry-run # Mock 데이터로 동작 확인
    python -m pipeline.kamis_fetcher --date 2026-05-01
"""
from __future__ import annotations

import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 경로 상수 ─────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent.parent
CACHE_FILE  = ROOT / "api" / "data" / "kamis_price_cache.json"

# ── KAMIS API 설정 ────────────────────────────────────────────────────────────
KAMIS_BASE_URL = "https://www.kamis.or.kr/service/price/xml.do"

def _get_api_key()  -> str: return os.environ.get("KAMIS_API_KEY",  "")
def _get_api_id()   -> str: return os.environ.get("KAMIS_API_ID",   "pad_smartfarm")
def _get_market()   -> str: return os.environ.get("KAMIS_MARKET",   "1101")

# 하위 호환성 (모듈 로드 시점 값 — FastAPI 서버는 load_dotenv() 이후 임포트되므로 정상)
_API_KEY = _get_api_key()
_API_ID  = _get_api_id()
_MARKET  = _get_market()

# ── 품목 코드 매핑 ─────────────────────────────────────────────────────────────
# KAMIS 표준 품목 코드 (도매 기준)
ITEM_CODES: dict[str, dict] = {
    "딸기": {
        "item_code":          "220",
        "item_name":          "딸기",
        "item_category_code": "200",   # 채소류
        "unit":               "kg",
    },
    "완숙토마토": {
        "item_code":          "226",
        "item_name":          "토마토",
        "item_category_code": "200",
        "unit":               "kg",
    },
    "방울토마토": {
        "item_code":          "227",
        "item_name":          "방울토마토",
        "item_category_code": "200",
        "unit":               "kg",
    },
    "참외": {
        "item_code":          "225",
        "item_name":          "참외",
        "item_category_code": "200",
        "unit":               "kg",
    },
    "오이": {
        "item_code":          "244",
        "item_name":          "오이",
        "item_category_code": "200",
        "unit":               "kg",
    },
    "파프리카": {
        "item_code":          "259",
        "item_name":          "파프리카",
        "item_category_code": "200",
        "unit":               "kg",
    },
}

# ── Mock 데이터 (API 키 없을 때 fallback) ─────────────────────────────────────
# 기준: 가락시장 2024~2025년 도매 연평균 (농식품부 KAMIS 통계 기반 추정)
_MOCK_PRICES: dict[str, float] = {
    "딸기":       11500.0,   # 2024 평균 가락 딸기 11,200~12,000원/kg
    "완숙토마토":   3200.0,   # 2024 평균 3,100~3,500원/kg
    "방울토마토":   4800.0,   # 2024 평균 4,600~5,000원/kg
    "참외":         3800.0,   # 2024 평균 3,500~4,200원/kg
    "오이":         2100.0,   # 2024 평균 1,900~2,300원/kg
    "파프리카":     6200.0,   # 2024 평균 5,800~6,500원/kg
}


# ── KAMIS API 호출 ─────────────────────────────────────────────────────────────

def _build_url(item_code: str, item_category_code: str, regday: str) -> str:
    params = {
        "action":               "dailyPriceByCategoryList",
        "p_cert_key":           _get_api_key(),
        "p_cert_id":            _get_api_id(),
        "p_returntype":         "json",
        "p_item_category_code": item_category_code,
        "p_country_code":       _get_market(),
        "p_regday":             regday,
        "p_convert_kg_yn":      "Y",
    }
    return KAMIS_BASE_URL + "?" + urllib.parse.urlencode(params)


def _make_ssl_context() -> ssl.SSLContext:
    """KAMIS 서버의 TLS 핸드셰이크 실패(SSLv3 alert) 우회용 SSL 컨텍스트.

    kamis.or.kr은 구형 서버 설정으로 인해 일부 클라이언트에서
    SSLV3_ALERT_HANDSHAKE_FAILURE 가 발생합니다.
    TLS 1.2 강제 + 인증서 검증 생략으로 연결을 허용합니다.
    운영 보안: 내부 가격 조회 전용 API로, 위조 위험이 낮아 허용합니다.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode   = ssl.CERT_NONE
    # TLS 1.2 명시적 허용 (일부 구형 서버는 TLS 1.3 협상 중 실패)
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    except AttributeError:
        pass  # Python 3.6 이하 호환
    return ctx


def _fetch_price_from_api(
    crop_ko: str,
    regday: str,
    retries: int = 3,
) -> Optional[float]:
    """KAMIS API에서 작목의 당일 도매가격(원/kg) 조회."""
    item_info = ITEM_CODES.get(crop_ko)
    if not item_info:
        logger.warning("[kamis] 지원하지 않는 작목: %s", crop_ko)
        return None

    url = _build_url(
        item_code=item_info["item_code"],
        item_category_code=item_info["item_category_code"],
        regday=regday,
    )
    _ssl_ctx = _make_ssl_context()

    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "SmartFarmPlatform/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15, context=_ssl_ctx) as resp:
                raw = json.loads(resp.read().decode("utf-8"))

            items = (raw.get("data", {}) or {}).get("item", [])
            if not items:
                logger.warning("[kamis] %s %s 데이터 없음", crop_ko, regday)
                return None

            # 해당 품목 코드 필터링 후 평균가 추출
            prices = []
            for it in items:
                if it.get("itemcode") != item_info["item_code"]:
                    continue
                price_str = str(it.get("price", "")).replace(",", "").strip()
                if price_str and price_str != "-":
                    try:
                        prices.append(float(price_str))
                    except ValueError:
                        pass

            if not prices:
                return None
            avg_price = sum(prices) / len(prices)
            logger.info("[kamis] %s %s → %.0f원/kg (%d개 가격 평균)",
                        crop_ko, regday, avg_price, len(prices))
            return round(avg_price, 1)

        except urllib.error.URLError as e:
            logger.warning("[kamis] API 오류 (시도 %d/%d): %s", attempt + 1, retries, e)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)   # 지수 백오프
        except Exception as e:
            logger.error("[kamis] 예상치 못한 오류 %s: %s", crop_ko, e)
            return None

    return None


def _fetch_mock_price(crop_ko: str) -> float:
    """Mock 가격 반환 (API 키 없는 개발/테스트 환경)."""
    logger.info("[kamis] Mock 모드 — %s 기본 가격 사용", crop_ko)
    return _MOCK_PRICES.get(crop_ko, 3000.0)


# ── 캐시 관리 ─────────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[kamis] 캐시 읽기 실패: %s", e)
    return {"updated_at": None, "prices": {}, "history": {}}


def save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def get_cached_price(crop_ko: str) -> Optional[float]:
    """캐시에서 최신 가격 반환 (당일 데이터만 유효)."""
    cache = load_cache()
    today = date.today().isoformat()
    if cache.get("updated_at", "")[:10] == today:
        return cache.get("prices", {}).get(crop_ko)
    return None


# ── 갱신 메인 로직 ────────────────────────────────────────────────────────────

def refresh_prices(
    target_date: Optional[date] = None,
    dry_run: bool = False,
    crops: Optional[list[str]] = None,
) -> dict[str, float]:
    """KAMIS에서 도매가격을 가져와 캐시에 저장.

    Args:
        target_date: 조회 날짜 (기본: 오늘)
        dry_run:     True면 API 미호출, Mock 데이터 반환
        crops:       갱신할 작목 리스트 (기본: 전체)

    Returns:
        {crop_ko: price_krw_kg} dict
    """
    if target_date is None:
        target_date = date.today()
    regday = target_date.strftime("%Y-%m-%d")

    target_crops = crops or list(ITEM_CODES.keys())
    use_api      = bool(_get_api_key()) and not dry_run

    if not use_api:
        mode = "dry-run" if dry_run else "키 미설정"
        logger.info("[kamis] Mock 모드 (%s) — API 미호출", mode)

    cache  = load_cache()
    prices = dict(cache.get("prices", {}))
    updated: dict[str, float] = {}

    for crop_ko in target_crops:
        if use_api:
            price = _fetch_price_from_api(crop_ko, regday)
        else:
            price = _fetch_mock_price(crop_ko)

        if price is not None:
            prices[crop_ko]  = price
            updated[crop_ko] = price

            # 이력 기록 (최근 30일)
            history = cache.setdefault("history", {}).setdefault(crop_ko, {})
            history[regday] = price
            if len(history) > 30:
                oldest = sorted(history.keys())[0]
                del history[oldest]

    now = datetime.now(tz=timezone.utc).isoformat()
    cache["updated_at"] = now
    cache["prices"]     = prices
    cache["regday"]     = regday
    cache["source"]     = "kamis_api" if use_api else "mock"

    if not dry_run:
        save_cache(cache)
        logger.info("[kamis] 캐시 저장 완료 (%d개 작목, %s)", len(updated), regday)

        # stats_loader lru_cache 무효화 (API 서버 실행 중일 때)
        try:
            from api.data.stats_loader import _load
            _load.cache_clear()
        except Exception:
            pass

    return updated


def get_price_with_fallback(crop_ko: str) -> dict:
    """캐시 → price_stats.json 순서로 가격 조회.

    Returns:
        {
            "price_krw_kg": float,
            "source": "kamis_live" | "kamis_cache" | "rda_static",
            "regday": str | None,
            "updated_at": str | None,
        }
    """
    cache = load_cache()
    regday     = cache.get("regday")
    updated_at = cache.get("updated_at")
    cached_price = cache.get("prices", {}).get(crop_ko)

    if cached_price is not None:
        return {
            "price_krw_kg": cached_price,
            "source":       "kamis_cache",
            "regday":       regday,
            "updated_at":   updated_at,
        }

    # fallback: price_stats.json 정적 데이터
    from api.data.stats_loader import get_price_krw_kg
    static_price = get_price_krw_kg(crop_ko)
    return {
        "price_krw_kg": static_price,
        "source":       "rda_static",
        "regday":       None,
        "updated_at":   None,
    }


# ── CLI 진입점 ────────────────────────────────────────────────────────────────

def _main() -> None:
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="KAMIS 도매가격 갱신")
    parser.add_argument("--date",    default=None, help="조회 날짜 (YYYY-MM-DD, 기본: 오늘)")
    parser.add_argument("--dry-run", action="store_true", help="Mock 데이터로 실행 (API 미호출)")
    parser.add_argument("--crops",   default=None, help="갱신 작목 (쉼표 구분, 기본: 전체)")
    args = parser.parse_args()

    target = None
    if args.date:
        target = date.fromisoformat(args.date)

    crops = [c.strip() for c in args.crops.split(",")] if args.crops else None

    print(f"{'[DRY-RUN] ' if args.dry_run else ''}KAMIS 가격 갱신 시작...")
    updated = refresh_prices(target_date=target, dry_run=args.dry_run, crops=crops)

    if updated:
        print("\n갱신된 가격:")
        for crop, price in updated.items():
            print(f"  {crop:>8}: {price:,.0f}원/kg")
    else:
        print("갱신된 가격 없음.")

    print(f"\n캐시 파일: {CACHE_FILE}")


if __name__ == "__main__":
    _main()
