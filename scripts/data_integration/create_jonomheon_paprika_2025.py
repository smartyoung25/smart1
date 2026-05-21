"""조남헌 파프리카 생육데이터(2025) → 학습용 ZIP 생성 스크립트.

출처: 카카오톡 사진 25장 (주간 생육 조사 양식)
농가: 조남헌, 강원 철원군
정식: 2025-03-09, 면적: 6611m² (2000평), 19000주, 5.7주/m²
품종: 비날레스 (빨간 파프리카)

수확수(개/주/주차)를 이용한 생산량 추정:
  총출하량(kg) = 수확수 × 19000주 × 0.175kg/개
  이 추정은 합리적 참고값이나 실제 출하 기록 확보 시 교체 권장.

출력: C:/smart_farm/기초자료/.../스마트팜_2025.zip
       생육_파프리카_조남헌_2025.csv
       생산_파프리카_조남헌_2025.csv
       재배정보_파프리카_조남헌_2025.csv
"""

from __future__ import annotations
import io, sys, zipfile
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "기초자료" / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터"

# ─── 농가 메타 ──────────────────────────────────────────────────────────────
FARM_NAME   = "조남헌"
FARM_DO     = "강원"
FARM_SIGUN  = "철원군"
CROP        = "파프리카"
VARIETY     = "비날레스"
JAKSIK      = 1
PLANT_DATE  = "2025-03-09"
TOTAL_AREA  = 6611   # m² (2000평)
PLANT_AREA  = 6611   # m²
DENSITY     = 5.7    # stems/m²
TOTAL_STEMS = 19000
AVG_FRUIT_WT= 0.175  # kg  (빨간 파프리카 평균 과중)

# ─── 생육 조사 데이터 (25주 전체 실측 — 이미지 독해 기반) ──────────────────────
# 컬럼: 조사일자, 초장(cm), 엽수(개), 개화마디, 착과마디, 수확수(개/주)
# ※ Photo 05(05-12), 06(05-20), 07(05-27), 08(06-04), 11(06-24) = 현장 이미지 독해값
#   나머지 20주 = 이전 세션에서 추출한 실측값
_RAW = [
    # ── 4월 (5주) ──────────────────────────────────────────────────────────────
    ("2025-04-07", 65.9,  4.0,  1.7,  0.4, 0.0),
    ("2025-04-15", 83.1,  7.5,  3.0,  1.8, 0.0),
    ("2025-04-21", 94.9, 10.0,  4.6,  3.6, 0.0),
    ("2025-04-28",109.8, 11.9,  6.0,  5.0, 0.0),
    # ── 5월 (5주) ──────────────────────────────────────────────────────────────
    ("2025-05-07",121.7, 11.1,  7.8,  6.8, 0.0),
    ("2025-05-12",124.5, 13.0,  8.0,  6.5, 0.0),  # Photo 05 실측
    ("2025-05-20",131.9, 14.0,  9.0,  7.0, 0.0),  # Photo 06 실측
    ("2025-05-27",140.0, 17.8,  9.5,  8.0, 0.0),  # Photo 07 실측
    # ── 6월 (4주) ──────────────────────────────────────────────────────────────
    ("2025-06-04",151.1, 21.0, 11.5,  8.5, 0.0),  # Photo 08 실측
    ("2025-06-10",160.2, 24.0, 12.6,  8.7, 0.0),
    ("2025-06-17",168.8, 26.6, 14.0, 10.4, 0.4),
    ("2025-06-24",174.3, 28.5, 14.5, 11.0, 0.3),  # Photo 11 실측
    # ── 7월 (5주) ──────────────────────────────────────────────────────────────
    ("2025-07-01",181.3, 31.8, 15.8, 12.4, 0.2),
    ("2025-07-08",187.1, 33.2, 18.1, 16.7, 0.3),
    ("2025-07-15",198.0, 36.0, 19.2, 17.2, 0.6),
    ("2025-07-22",207.4, 39.4, 20.7, 18.4, 0.6),
    ("2025-07-29",223.5, 43.3, 22.0, 20.4, 0.6),
    # ── 8월 (4주) ──────────────────────────────────────────────────────────────
    ("2025-08-05",234.9, 47.2, 23.8, 22.8, 0.2),
    ("2025-08-12",245.5, 50.0, 24.9, 23.8, 0.3),
    ("2025-08-19",256.7, 52.8, 26.4, 25.4, 0.1),
    ("2025-08-26",266.3, 56.4, 27.8, 26.3, 0.0),
    # ── 9월 (4주) ──────────────────────────────────────────────────────────────
    ("2025-09-02",280.7, 59.2, 29.5, 28.4, 0.0),
    ("2025-09-09",292.6, 61.7, 31.0, 30.2, 0.4),
    ("2025-09-16",301.1, 63.6, 31.0, 31.2, 0.9),
    ("2025-09-23",306.8, 66.0, 33.4, 32.4, 0.2),
]

def _build_growth_rows() -> list[tuple]:
    """25주 전체 실측값 반환 (보간 없음)."""
    return list(_RAW)


def make_growth_csv() -> pd.DataFrame:
    """RDA 생육 CSV 포맷 생성."""
    cols = ["도", "시군", "품목", "작기", "농가명",
            "조사일자", "개체번호", "줄기번호",
            "초장", "생장길이", "엽수", "엽장", "엽폭",
            "줄기굵기", "화방높이", "개화마디", "착과마디"]

    growth_rows = _build_growth_rows()
    records = []
    prev_height = None
    for date, height, leaf, flw_node, frt_node, _ in growth_rows:
        growth_len = round(height - prev_height, 1) if prev_height is not None else float("nan")
        prev_height = height
        records.append({
            "도":      FARM_DO,
            "시군":    FARM_SIGUN,
            "품목":    CROP,
            "작기":    JAKSIK,
            "농가명":  FARM_NAME,
            "조사일자": date,
            "개체번호": 1,
            "줄기번호": 1,
            "초장":    height,
            "생장길이": growth_len,
            "엽수":    leaf,
            "엽장":    float("nan"),
            "엽폭":    float("nan"),
            "줄기굵기": float("nan"),
            "화방높이": float("nan"),
            "개화마디": flw_node,
            "착과마디": frt_node,
        })
    return pd.DataFrame(records, columns=cols)


def make_production_csv() -> pd.DataFrame:
    """수확수 기반 월별 생산량 추정 → RDA 생산 CSV 포맷.

    총출하량(kg) = 수확수(개/주) × 19,000주 × 0.175kg/개
    주의: 이 값은 현장 수확수 사진에서 역산한 추정값.
    """
    cols = ["도", "시군", "품목", "작기", "농가명",
            "출하일자", "총출하량", "판매금액"]

    growth_rows = _build_growth_rows()

    # 월별 수확수 합산
    monthly: dict[str, float] = {}
    for date_str, _, _, _, _, harv_n in growth_rows:
        dt  = pd.Timestamp(date_str)
        key = f"{dt.year}-{dt.month:02d}"
        monthly[key] = monthly.get(key, 0.0) + harv_n

    records = []
    for ym, n_per_stem in monthly.items():
        if n_per_stem <= 0:
            continue
        total_kg = round(n_per_stem * TOTAL_STEMS * AVG_FRUIT_WT, 1)
        # 출하일자: 월말 (말일 = 다음달 1일 - 1일)
        yr, mo = map(int, ym.split("-"))
        last_day = (pd.Timestamp(yr, mo, 1) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        records.append({
            "도":      FARM_DO,
            "시군":    FARM_SIGUN,
            "품목":    CROP,
            "작기":    JAKSIK,
            "농가명":  FARM_NAME,
            "출하일자": last_day,
            "총출하량": total_kg,
            "판매금액": 0,   # 가격 정보 미입수
        })
    return pd.DataFrame(records, columns=cols)


def make_cultiv_csv() -> pd.DataFrame:
    """재배정보 CSV — 면적·품종·정식일 등록."""
    cols = ["연번", "연도", "작기", "지역(도)", "시군", "농가명",
            "온실종류", "온실유형", "품목", "품종",
            "총면적", "식부면적", "재식밀도", "정식일",
            "환경데이터", "생육데이터", "판매데이터"]
    return pd.DataFrame([{
        "연번":     1,
        "연도":     2025,
        "작기":     JAKSIK,
        "지역(도)": FARM_DO,
        "시군":     FARM_SIGUN,
        "농가명":   FARM_NAME,
        "온실종류":  "유리",
        "온실유형":  "연동",
        "품목":     CROP,
        "품종":     VARIETY,
        "총면적":   TOTAL_AREA,
        "식부면적":  PLANT_AREA,
        "재식밀도":  DENSITY,
        "정식일":    PLANT_DATE,
        "환경데이터": "무",
        "생육데이터": "유",
        "판매데이터": "추정",
    }], columns=cols)


def main():
    growth_df = make_growth_csv()
    prod_df   = make_production_csv()
    cultiv_df = make_cultiv_csv()

    print("=== 생육 데이터 ===")
    print(growth_df[["조사일자", "초장", "엽수", "개화마디", "착과마디"]].to_string(index=False))

    print("\n=== 생산 추정 데이터 ===")
    print(prod_df.to_string(index=False))
    print(f"  ▶ 합계: {prod_df['총출하량'].sum():.0f} kg → {prod_df['총출하량'].sum()/PLANT_AREA:.2f} kg/m²")

    print("\n=== 재배정보 ===")
    print(cultiv_df.to_string(index=False))

    # ── ZIP 생성 ────────────────────────────────────────────────────────────
    # 파일명은 ASCII로 저장 (CP437 안전), 내용은 euc-kr 바이트
    zip_path = DATA_DIR / "스마트팜_2025.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for csv_name, df in [
            ("growth_paprika_jonomheon_2025.csv",    growth_df),
            ("prod_paprika_jonomheon_2025.csv",      prod_df),
            ("cultiv_paprika_jonomheon_2025.csv",    cultiv_df),
        ]:
            buf = io.BytesIO()
            df.to_csv(buf, index=False, encoding="euc-kr")
            zf.writestr(csv_name, buf.getvalue())   # raw euc-kr bytes

    print(f"\n[OK] ZIP 생성 완료: {zip_path}")

    # ── 파케이 캐시 삭제 (강제 재로드) ──────────────────────────────────────
    cache_dir = ROOT / ".cache" / "train_stage2"
    deleted = 0
    for pattern in ["s2_growth_파프리카*", "s2_prod_파프리카*",
                    "s2_env_파프리카*", "s2_growth_paprika*",
                    "s2_prod_paprika*"]:
        for f in cache_dir.glob(pattern) if cache_dir.exists() else []:
            f.unlink()
            deleted += 1
    print(f"[OK] 캐시 삭제: {deleted}개 파일 제거 (파프리카 재로드 강제)")


if __name__ == "__main__":
    main()
