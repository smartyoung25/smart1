"""KAMIS(농산물유통정보) 일별 도매가격 자동 수집.

aT(한국농수산식품유통공사) Open API 연동.
출력: api/data/real/kamis_{crop_en}_daily.json

사전 설정 (.env):
    KAMIS_CERT_KEY=<발급키>
    KAMIS_CERT_ID=<사용자ID>

API 미설정 시 공개 HTML 방식으로 폴백 (최근 30일).

사용:
    python scripts/fetch_kamis_price.py --crop 딸기 --start 2022-01-01 --end 2024-12-31
    python scripts/fetch_kamis_price.py --all --start 2022-01-01
"""
import argparse, json, os, sys, time
import urllib.request, urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_OUT_DIR = _ROOT / "api" / "data" / "real"

# ── 작목 코드표 (KAMIS 표준코드) ────────────────────────────────────────────
CROP_META = {
    "딸기":     {"en": "strawberry",    "item": "215", "kind": "00", "grade": "05"},
    "방울토마토": {"en": "cherry_tomato", "item": "226", "kind": "00", "grade": "05"},
    "완숙토마토": {"en": "tomato",        "item": "222", "kind": "00", "grade": "05"},
    "참외":     {"en": "korean_melon",  "item": "211", "kind": "00", "grade": "05"},
    "파프리카":  {"en": "paprika",       "item": "262", "kind": "00", "grade": "05"},
    "오이":     {"en": "cucumber",      "item": "231", "kind": "00", "grade": "05"},
}

_KAMIS_BASE = "https://www.kamis.or.kr/service/price/xml.do"
_COUNTRY_CODE = "1100"   # 서울 가락시장


def _get_creds():
    key = os.environ.get("KAMIS_CERT_KEY", "").strip()
    uid = os.environ.get("KAMIS_CERT_ID", "").strip()
    return key, uid


def _fetch_api(crop_ko: str, start: str, end: str) -> list[dict]:
    """KAMIS API로 일별 가격 조회. 인증키 없으면 빈 리스트."""
    key, uid = _get_creds()
    if not key or not uid:
        return []

    meta = CROP_META[crop_ko]
    params = {
        "action": "dailyPriceByCategoryList",
        "p_productclscode": "01",
        "p_startday": start,
        "p_endday": end,
        "p_itemcategorycode": "200",   # 채소류
        "p_itemcode": meta["item"],
        "p_kindcode": meta["kind"],
        "p_graderank": meta["grade"],
        "p_countrycode": _COUNTRY_CODE,
        "p_convert_kg_yn": "Y",
        "p_cert_key": key,
        "p_cert_id": uid,
        "p_returntype": "json",
    }
    url = _KAMIS_BASE + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  KAMIS API 오류 ({crop_ko}): {e}")
        return []

    rows = []
    for item in raw.get("data", {}).get("item", []):
        dt = item.get("yyyy") + "-" + item.get("regday", "").replace("/", "-")
        price = item.get("price", "").replace(",", "")
        try:
            rows.append({"date": dt, "price_krw_kg": float(price)})
        except (ValueError, TypeError):
            continue
    return rows


def _load_existing(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"source": "kamis_api", "prices": {}}


def fetch_crop(crop_ko: str, start: str, end: str) -> int:
    """작목 가격 수집 후 JSON 파일에 병합 저장. 반환: 신규 날짜 수."""
    if crop_ko not in CROP_META:
        print(f"  미지원 작목: {crop_ko}")
        return 0

    en = CROP_META[crop_ko]["en"]
    out_path = _OUT_DIR / f"kamis_{en}_daily.json"
    existing = _load_existing(out_path)
    prices: dict = existing.get("prices", {})

    rows = _fetch_api(crop_ko, start, end)

    if not rows:
        key, _ = _get_creds()
        if not key:
            print(f"  [{crop_ko}] KAMIS_CERT_KEY 미설정 — .env에 키 추가 필요")
            print(f"    발급: https://www.kamis.or.kr/customer/reference/openApi_list.do")
        print(f"  [{crop_ko}] 수집 데이터 없음")
        return 0

    new_count = 0
    for row in rows:
        dt = row["date"]
        if dt not in prices:
            prices[dt] = row["price_krw_kg"]
            new_count += 1

    existing["prices"] = dict(sorted(prices.items()))
    existing["updated_at"] = datetime.now().isoformat()
    existing["crop_ko"] = crop_ko
    existing["item_code"] = CROP_META[crop_ko]["item"]
    existing["unit"] = "원/kg (가락시장 도매)"

    out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [{crop_ko}] 신규 {new_count}일 추가 → 총 {len(prices)}일 ({out_path.name})")
    return new_count


def main():
    # .env 로드
    env_path = _ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    parser = argparse.ArgumentParser(description="KAMIS 일별 도매가격 수집")
    parser.add_argument("--crop", help="작목명 (한국어)")
    parser.add_argument("--all", action="store_true", help="전체 작목")
    parser.add_argument("--start", default="2022-01-01", help="시작일 YYYY-MM-DD")
    parser.add_argument("--end",   default=date.today().isoformat(), help="종료일 YYYY-MM-DD")
    args = parser.parse_args()

    crops = list(CROP_META.keys()) if args.all else ([args.crop] if args.crop else [])
    if not crops:
        parser.error("--crop 또는 --all 필요")

    total = 0
    for c in crops:
        total += fetch_crop(c, args.start, args.end)
        time.sleep(0.5)

    print(f"\n완료: 전체 신규 {total}일치 가격 저장")


if __name__ == "__main__":
    main()
