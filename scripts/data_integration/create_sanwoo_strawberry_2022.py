"""SANWOO_Farm 딸기 OCR 수확량 → 스마트팜_2023.zip 생성 스크립트.

전제:
    ocr_sanwoo_journal.py 를 먼저 실행해 월별 CSV 생성:
      - scripts/data_integration/sanwoo_strawberry_monthly.csv

동작:
    1. 월별 수확량 CSV 로드
    2. RDA 포맷 생산+재배정보 CSV 생성 (품목=딸기, 농가명=SANWOO)
    3. 스마트팜_2023.zip 생성 (crop_config.py SUPP_YEARS=[...,2023] 와 연동)
    4. 딸기 M2 캐시 삭제 (재학습 강제)
    5. crop_config.py YEARS / SUPP_YEARS 에 2023 추가 안내

농가 메타:
    농가명: SANWOO (삼우농장)
    위치: 미상 (경상 추정)
    작목: 딸기, 품종: 설향 (추정)
    정식: 2022-09-01, 면적: 4000 m2 (27,000주 / 6.75주/m2)
    수확기간: 2022-12 ~ 2023-05 → 주 수확연도 2023
"""

from __future__ import annotations
import io, sys, zipfile
from pathlib import Path

import pandas as pd

ROOT     = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "기초자료" / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터"
MONTHLY_CSV = ROOT / "scripts" / "data_integration" / "sanwoo_strawberry_monthly.csv"

FARM_NAME  = "SANWOO"
FARM_DO    = "경상"
FARM_SIGUN = "미상"
CROP       = "딸기"
VARIETY    = "설향"
JAKSIK     = 1
PLANT_DATE = "2022-09-01"
AREA_M2    = 4000


def make_production_csv(monthly: pd.DataFrame) -> pd.DataFrame:
    """월별 수확 집계 → RDA 생산 CSV."""
    cols = ["도", "시군", "품목", "작기", "농가명",
            "출하일자", "총출하량", "판매금액"]
    records = []
    for _, row in monthly.iterrows():
        yr  = int(row["year"])
        mo  = int(row["month"])
        kg  = float(row["harvest_kg"])
        last_day = (pd.Timestamp(yr, mo, 1) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        records.append({
            "도": FARM_DO, "시군": FARM_SIGUN, "품목": CROP,
            "작기": JAKSIK, "농가명": FARM_NAME,
            "출하일자": last_day, "총출하량": round(kg, 1), "판매금액": 0,
        })
    return pd.DataFrame(records, columns=cols)


def make_cultiv_csv() -> pd.DataFrame:
    """재배정보 CSV."""
    cols = ["연번", "연도", "작기", "지역(도)", "시군", "농가명",
            "온실종류", "온실유형", "품목", "품종",
            "총면적", "식부면적", "재식밀도", "정식일",
            "환경데이터", "생육데이터", "판매데이터"]
    return pd.DataFrame([{
        "연번": 1, "연도": 2023, "작기": JAKSIK,
        "지역(도)": FARM_DO, "시군": FARM_SIGUN, "농가명": FARM_NAME,
        "온실종류": "비닐", "온실유형": "단동",
        "품목": CROP, "품종": VARIETY,
        "총면적": AREA_M2, "식부면적": AREA_M2, "재식밀도": 6.75,
        "정식일": PLANT_DATE,
        "환경데이터": "무", "생육데이터": "무", "판매데이터": "OCR추출",
    }], columns=cols)


def main():
    # ── 월별 CSV 로드 ────────────────────────────────────────────────────────
    if not MONTHLY_CSV.exists():
        print(f"[ERROR] 월별 CSV 없음: {MONTHLY_CSV}")
        print("  먼저 실행: python scripts/data_integration/ocr_sanwoo_journal.py")
        sys.exit(1)

    monthly = pd.read_csv(MONTHLY_CSV, encoding="utf-8-sig")
    if "total_kg" not in monthly.columns and "harvest_kg" in monthly.columns:
        monthly = monthly.rename(columns={"harvest_kg": "total_kg"})
    monthly = monthly.rename(columns={"total_kg": "harvest_kg"})

    prod_df   = make_production_csv(monthly)
    cultiv_df = make_cultiv_csv()

    print("=== SANWOO_Farm 딸기 생산 데이터 (OCR 추출) ===")
    print(prod_df.to_string(index=False))
    total_kg = prod_df["총출하량"].sum()
    print(f"  합계: {total_kg:.1f} kg = {total_kg/AREA_M2:.3f} kg/m2 (4000m2 기준)")

    # ── 스마트팜_2023.zip 생성 ────────────────────────────────────────────────
    zip_path = DATA_DIR / "스마트팜_2023.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, df in [
            ("prod_strawberry_sanwoo_2023.csv",   prod_df),
            ("cultiv_strawberry_sanwoo_2023.csv", cultiv_df),
        ]:
            buf = io.BytesIO()
            df.to_csv(buf, index=False, encoding="euc-kr")
            zf.writestr(name, buf.getvalue())
            print(f"  [ZIP] {name}  ({len(df)}행)")
    print(f"\n[OK] ZIP 생성: {zip_path}")

    # ── crop_config.py 확인 ──────────────────────────────────────────────────
    cfg_path = ROOT / "models" / "crop_config.py"
    cfg_text = cfg_path.read_text(encoding="utf-8")
    years_line  = next((l for l in cfg_text.splitlines() if l.strip().startswith("YEARS")), "")
    supp_line   = next((l for l in cfg_text.splitlines() if l.strip().startswith("SUPP_YEARS")), "")
    if "2023" in years_line and "2023" in supp_line:
        print("[OK] crop_config.py - YEARS/SUPP_YEARS 에 2023 포함 확인")
    else:
        print("[WARN] crop_config.py 수동 업데이트 필요:")
        print("  YEARS      = [..., 2023, 2025]")
        print("  SUPP_YEARS = [2023, 2025]")

    # ── 딸기 M2 캐시 삭제 ────────────────────────────────────────────────────
    cache_dir = ROOT / ".cache" / "train_stage2"
    deleted = 0
    for pattern in ["s2_growth_딸기*", "s2_prod_딸기*",
                    "s2_env_딸기*", "s2_growth_strawberry*",
                    "s2_prod_strawberry*"]:
        for f in (cache_dir.glob(pattern) if cache_dir.exists() else []):
            f.unlink()
            deleted += 1
    if deleted:
        print(f"[OK] 딸기 캐시 {deleted}개 삭제")

    print("\n=== 다음 단계: 딸기 M2 재학습 ===")
    print("  python scripts/train_stage2_yield.py --crop 딸기 --no-cache")


if __name__ == "__main__":
    main()
