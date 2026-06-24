"""KAMIS(농산물유통정보) 채소류 도매가격 수집.

aT(한국농수산식품유통공사) Open API 연동.
출력: api/data/real/kamis_{crop_en}_daily.json

API 제약:
  - dailyPriceByCategoryList: 식량(category=100)만 지원, 채소 불가
  - dailySalesList: 채소(category=200) 지원, 최근 4포인트(오늘/1주/1개월/1년전) 반환

전략:
  1. dailySalesList 로 현재 가격 스냅샷 저장 (매일 실행하면 누적)
  2. 작목명 매칭으로 6개 작목 분리

사전 설정 (.env):
    KAMIS_CERT_KEY=<발급키>
    KAMIS_CERT_ID=<사용자ID> 또는 KAMIS_API_ID=<사용자ID>

사용:
    python scripts/fetch_kamis_price.py --all
    python scripts/fetch_kamis_price.py --crop 딸기
"""
import argparse, json, os, time
import urllib.request, urllib.parse
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_OUT_DIR = _ROOT / "api" / "data" / "real"

# ── 작목 코드표: en 키 + 이름 매칭 키워드 ─────────────────────────────────────
CROP_META = {
    # ── 기존 온실 6종 ───────────────────────────────────────────────────────
    "딸기":     {"en": "strawberry",    "keywords": ["딸기"]},
    "방울토마토": {"en": "cherry_tomato", "keywords": ["방울토마토", "방울 토마토"]},
    "완숙토마토": {"en": "tomato",        "keywords": ["완숙토마토", "완숙 토마토", "토마토"]},
    "참외":     {"en": "korean_melon",  "keywords": ["참외"]},
    "파프리카":  {"en": "paprika",       "keywords": ["파프리카"]},
    "오이":     {"en": "cucumber",      "keywords": ["오이"]},
    # ── 추가 노지·제주 8종 ─────────────────────────────────────────────────
    "콩":       {"en": "soybean",       "keywords": ["콩", "대두"]},
    "무":       {"en": "radish",        "keywords": ["무"]},
    "배추":     {"en": "cabbage",       "keywords": ["배추", "알배기배추"]},
    "마늘":     {"en": "garlic",        "keywords": ["마늘", "깐마늘"]},
    "양파":     {"en": "onion",         "keywords": ["양파"]},
    "고추":     {"en": "pepper",        "keywords": ["고추", "풋고추", "붉은고추", "고춧가루"]},
    "가지":     {"en": "eggplant",      "keywords": ["가지"]},
    "감귤":     {"en": "citrus",        "keywords": ["감귤", "한라봉", "천혜향"]},
    "양배추":   {"en": "headed_cabbage","keywords": ["양배추"]},
}

# 매칭 순서: 긴 이름 우선 (방울토마토 > 토마토, 알배기배추 > 배추)
_MATCH_ORDER = [
    "방울토마토", "완숙토마토", "양배추", "배추",
    "딸기", "참외", "파프리카", "오이",
    "마늘", "양파", "고추", "무", "콩", "가지", "감귤",
]

_KAMIS_BASE = "https://www.kamis.or.kr/service/price/xml.do"


def _get_creds():
    key = os.environ.get("KAMIS_CERT_KEY", os.environ.get("KAMIS_API_KEY", "")).strip()
    uid = os.environ.get("KAMIS_CERT_ID", os.environ.get("KAMIS_API_ID", "")).strip()
    return key, uid


def _match_crop(item_name: str) -> str | None:
    """KAMIS 품목명에서 작목 키 반환. 매칭 불가 시 None."""
    n = item_name.replace(" ", "")
    for crop in _MATCH_ORDER:
        for kw in CROP_META[crop]["keywords"]:
            if kw.replace(" ", "") in n:
                return crop
    return None


def _parse_price(s: str) -> float | None:
    """'62,409' → 62409.0. 파싱 불가 시 None."""
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _fetch_category(category_code: str) -> list[dict]:
    """KAMIS dailySalesList 단일 카테고리 호출. price 리스트 반환."""
    key, uid = _get_creds()
    if not key or not uid:
        return []
    params = {
        "action": "dailySalesList",
        "p_cert_key": key,
        "p_cert_id": uid,
        "p_returntype": "json",
        "p_product_cls_code": "01",
        "p_category_code": category_code,
        "p_convert_kg_yn": "Y",
    }
    url = _KAMIS_BASE + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=12) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        return raw.get("price", [])
    except Exception as e:
        print(f"  KAMIS API 오류 (category={category_code}): {e}")
        return []


def _fetch_all_crops() -> dict[str, list[dict]]:
    """
    채소류(200) + 과일류(400) 조회 → 작목별 오늘 가격 리스트 반환.
    딸기는 과일류(400)에 속함.
    """
    today = date.today().isoformat()
    result: dict[str, list[dict]] = {k: [] for k in CROP_META}

    for cat_code in ("200", "400", "300"):  # 채소 + 과일 + 특용작물(마늘·양파·고추 포함)
        for it in _fetch_category(cat_code):
            if not isinstance(it, dict):
                continue
            name = it.get("productName", "") or it.get("item_name", "")
            crop = _match_crop(name)
            if not crop:
                continue
            p = _parse_price(it.get("dpr1", ""))
            if p and p > 0:
                result[crop].append({"date": today, "price_krw_kg": p})
        time.sleep(0.3)

    return result


def _load_existing(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"source": "kamis_api", "prices": {}}


def fetch_crop(crop_ko: str, all_data: dict[str, list[dict]]) -> int:
    """단일 작목 가격을 JSON에 병합 저장. 반환: 신규 날짜 수."""
    if crop_ko not in CROP_META:
        print(f"  미지원 작목: {crop_ko}")
        return 0

    en = CROP_META[crop_ko]["en"]
    out_path = _OUT_DIR / f"kamis_{en}_daily.json"
    existing = _load_existing(out_path)
    prices: dict = existing.get("prices", {})

    rows = all_data.get(crop_ko, [])
    if not rows:
        print(f"  [{crop_ko}] 매칭 데이터 없음 (KAMIS 품목명 불일치 가능)")
        return 0

    new_count = 0
    for row in rows:
        dt = row["date"]
        if dt not in prices:
            prices[dt] = row["price_krw_kg"]
            new_count += 1
        else:
            # 같은 날짜면 갱신
            prices[dt] = row["price_krw_kg"]

    existing["prices"] = dict(sorted(prices.items()))
    existing["updated_at"] = datetime.now().isoformat()
    existing["crop_ko"] = crop_ko
    existing["unit"] = "원/kg (가락시장 도매, kg환산)"
    existing["note"] = "dailySalesList: 매일 실행 시 일별 누적. 역사적 데이터는 수동 CSV 가져오기 필요."

    out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [{crop_ko}] 신규 {new_count}건 저장 → 누적 {len(prices)}일 ({out_path.name})")
    return new_count


def main():
    # .env 로드
    env_path = _ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    parser = argparse.ArgumentParser(description="KAMIS 채소 도매가격 수집 (dailySalesList)")
    parser.add_argument("--crop", help="작목명 (한국어)")
    parser.add_argument("--all", action="store_true", help="전체 작목")
    args = parser.parse_args()

    key, uid = _get_creds()
    if not key or not uid:
        print("오류: KAMIS_CERT_KEY / KAMIS_API_ID 미설정 (.env 확인)")
        return

    crops = list(CROP_META.keys()) if args.all else ([args.crop] if args.crop else [])
    if not crops:
        parser.error("--crop 또는 --all 필요")

    print("KAMIS dailySalesList (채소200 + 과일400) 호출 중...")
    all_data = _fetch_all_crops()

    if not any(all_data.values()):
        print("  응답에서 작목 매칭 실패.")
        return

    total = 0
    for c in crops:
        total += fetch_crop(c, all_data)
        time.sleep(0.1)

    print(f"\n완료: 전체 신규 {total}건 저장")
    if total > 0:
        print("팁: cron/스케줄러로 매일 실행하면 일별 가격 누적 수집됩니다.")


if __name__ == "__main__":
    main()
