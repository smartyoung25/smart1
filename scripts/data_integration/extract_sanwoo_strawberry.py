"""SANWOO_Farm 영농일지(2022-23) → 딸기 월별 수확량 추출 스크립트.

출처: 영농 일지_ver1.png (632 PNG 파일)
농가: SANWOO_Farm (삼우농장 추정)
작목: 딸기 (2022년 9월 정식, 2023년 5월 종료 예상)

수확기록 형식 (발견된 패턴):
  "1번동 수확함_출하 33Box, 상 1Box, 스치 1kg 1Box"
  "전동 수확함_회박스 7개, 스치 1kg 20Box, 지박스 4개, 출하_상 6Box"

박스별 무게 추정:
  회박스: 250~300g (회딸기용 소용량, ~250g 사용)
  스치 1kg 박스: 1000g
  지박스(地): 250~300g (~250g 사용)
  상박스 (상품): 500g
  일반 박스 (무기재 기준): 500g

출력: scripts/data_integration/sanwoo_strawberry_harvest_2022.csv
"""

from __future__ import annotations
import re
import sys
from pathlib import Path
from collections import defaultdict

import pandas as pd

JOURNAL_DIR = Path(
    r"D:\이암허브\2025 구교영\2.스마트농업\1.농진청(빅데이터AI수익성향상)"
    r"\5.연구\데이터수집\영농 일지_ver1.png (1)\영농 일지_ver1.png"
)

ROOT = Path(__file__).parent.parent.parent

# ─── 박스 무게 매핑 (kg) ─────────────────────────────────────────────────────
BOX_WEIGHTS: dict[str, float] = {
    "회박스":  0.250,
    "지박스":  0.250,
    "스치 1kg": 1.000,
    "1kg":     1.000,
    "상박스":  0.500,
    "상":      0.500,
    "Box":     0.500,   # 기본 박스
}

# ─── 수확 기록 추출 정규식 ────────────────────────────────────────────────────
# 패턴: "수확함" 또는 "수확" + "출하" 가 있는 줄
_HARVEST_LINE_RE = re.compile(
    r"(?:수확함?|수확_?출하|출하)[^0-9]*"
    r"(?P<boxes>[\d]+)\s*(?P<unit>회박스|지박스|스치 1kg|1kg박스?|상박스?|Box|박스|개)",
    re.IGNORECASE,
)

# 날짜 패턴 (일지 상단: "XX월 XX일 요일 날씨...")
_DATE_RE = re.compile(
    r"(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일",
)


def _parse_page_text(text: str) -> tuple[str | None, float]:
    """
    페이지 텍스트에서 (날짜 문자열, 총 수확량 kg)을 추출.
    날짜는 페이지 첫 줄에서 추출, 수확량은 모든 수확 관련 줄 합산.
    """
    lines = text.strip().splitlines()

    # 날짜 추출 (첫 줄에서)
    date_str = None
    for line in lines[:3]:
        m = _DATE_RE.search(line)
        if m:
            month = int(m.group("month"))
            day   = int(m.group("day"))
            date_str = f"{month:02d}-{day:02d}"
            break

    # 수확량 추출
    total_kg = 0.0
    for line in lines:
        if not re.search(r"수확|출하", line):
            continue
        # 모든 수량 × 단위 패턴 추출
        for qty_m in re.finditer(
            r"(\d+(?:\.\d+)?)\s*(회박스|지박스|스치\s*1kg|1kg\s*박스?|상박스?|Box|박스|개)",
            line, re.IGNORECASE,
        ):
            qty  = float(qty_m.group(1))
            unit = qty_m.group(2).strip()
            # 단위 정규화
            if "회박스" in unit:
                weight = 0.250
            elif "지박스" in unit:
                weight = 0.250
            elif re.search(r"스치|1kg", unit):
                weight = 1.000
            elif "상박스" in unit or unit == "상":
                weight = 0.500
            else:
                weight = 0.500   # 기본
            total_kg += qty * weight

    return date_str, total_kg


def extract_from_images() -> pd.DataFrame:
    """PNG 이미지에서 텍스트 인식 없이 파일명 기반 스캔.

    실제 OCR 없이 이미지 파일을 직접 분석하는 것은 불가.
    이 함수는 수동 추출 데이터를 반환합니다.
    전체 OCR이 필요하면 pytesseract 또는 Google Cloud Vision 사용 권장.
    """
    # 수동 추출 데이터 (영농 일지에서 확인된 수확 기록)
    # Dec 11: 1번동 출하 33Box × 0.5kg = 16.5kg
    # Jan 20: 회박스 7개×0.25 + 스치1kg 20Box + 지박스4개×0.25 + 상6Box×0.5
    #        = 1.75 + 20 + 1.0 + 3.0 = 25.75 kg
    manual_records = [
        # (월, 일, 동, 수확량kg, 비고)
        (12, 11, "1번동",  16.5, "33Box×0.5kg"),
        (1,  20, "전동",   25.75, "회박스7+스치1kg20+지박스4+상6"),
    ]

    rows = []
    for month, day, dong, kg, note in manual_records:
        # 2022년 9월 정식 → 12월은 2022, 1-5월은 2023
        year = 2022 if month >= 9 else 2023
        rows.append({
            "date":  f"{year}-{month:02d}-{day:02d}",
            "month": month,
            "year":  year,
            "dong":  dong,
            "harvest_kg": kg,
            "note":  note,
        })
    return pd.DataFrame(rows)


def aggregate_monthly(df: pd.DataFrame,
                      farm_area_m2: float = 4000.0) -> pd.DataFrame:
    """일별 수확량 → 월별 집계 + yield_per_m2 계산."""
    if df.empty:
        return pd.DataFrame()
    monthly = (
        df.groupby(["year", "month"])["harvest_kg"]
        .sum()
        .reset_index()
        .rename(columns={"harvest_kg": "total_kg"})
    )
    monthly["yield_per_m2"] = monthly["total_kg"] / farm_area_m2
    return monthly


def main():
    print("=" * 60)
    print("SANWOO_Farm 영농일지 딸기 수확량 추출")
    print("=" * 60)
    print(f"일지 폴더: {JOURNAL_DIR}")

    if not JOURNAL_DIR.exists():
        print("[ERROR] 영농일지 폴더를 찾을 수 없습니다.")
        return

    png_files = sorted(JOURNAL_DIR.glob("*.png"))
    print(f"총 PNG 파일 수: {len(png_files)}")

    print("\n[중요] 이 스크립트는 수동 추출 데이터로 시작합니다.")
    print("       전체 632장 OCR을 위해서는 pytesseract 또는 Cloud Vision 필요.")
    print("       현재까지 수동 확인된 수확 기록:")

    df_manual = extract_from_images()
    print(df_manual.to_string(index=False))

    monthly = aggregate_monthly(df_manual, farm_area_m2=4000.0)
    if not monthly.empty:
        print("\n월별 집계 (농가 면적 4000m² 가정):")
        print(monthly.to_string(index=False))

    # CSV 저장
    out_path = ROOT / "scripts" / "data_integration" / "sanwoo_strawberry_harvest_2022.csv"
    df_manual.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] 저장: {out_path}")

    # 전략적 평가
    print("\n" + "=" * 60)
    print("딸기 M2 모델 활용 가능성 평가:")
    print("  - 확인된 수확 기록: 2일치 (Dec 11, Jan 20)")
    print("  - 전체 시즌 추정 필요 (Nov 2022 ~ May 2023, 약 7개월)")
    print("  - 일별 기록에서 월별 합계 추출 필요 (632장 OCR)")
    print("  - 결론: OCR 없이는 완전한 연간 수확량 추출 불가")
    print("")
    print("권장 접근법:")
    print("  Option A: 632장 OCR 자동화 (pytesseract)")
    print("    pip install pytesseract Pillow")
    print("    python scripts/data_integration/ocr_sanwoo_journal.py")
    print("")
    print("  Option B: AIHub #71523 (딸기/오이) 신청 - 대규모 공개 데이터")
    print("    → aihub.or.kr에서 신청 (무료, 승인 필요)")


if __name__ == "__main__":
    main()
