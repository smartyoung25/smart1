"""SANWOO_Farm 영농일지 전체 OCR 및 딸기 수확량 자동 추출.

사전 설치:
    pip install pytesseract Pillow
    # Tesseract OCR 엔진 설치 (Windows):
    # https://github.com/UB-Mannheim/tesseract/wiki 에서 다운로드
    # 한국어 tessdata (kor.traineddata) → C:/tools/tessdata/

수행 결과:
    - scripts/data_integration/sanwoo_strawberry_harvest_full.csv  (일별 수확기록)
    - scripts/data_integration/sanwoo_strawberry_monthly.csv        (월별 집계)
"""

from __future__ import annotations
import os, re, sys
from pathlib import Path

# ── Tesseract / TESSDATA 설정 (import 전에 환경변수 설정) ──────────────────────
os.environ.setdefault("TESSDATA_PREFIX", r"C:\tools\tessdata")

ROOT = Path(__file__).parent.parent.parent

JOURNAL_DIR = Path(
    r"D:\이암허브\2025 구교영\2.스마트농업\1.농진청(빅데이터AI수익성향상)"
    r"\5.연구\데이터수집\영농 일지_ver1.png (1)\영농 일지_ver1.png"
)

# ─── OCR 후처리: 한글 음절 사이 공백 제거 ────────────────────────────────────
_HAN_RE = re.compile(r"([가-힣ㄱ-ㅎㅏ-ㅣ])\s+([가-힣ㄱ-ㅎㅏ-ㅣ])")

def _clean_ocr(text: str) -> str:
    """Tesseract 가 한글 음절 사이에 삽입하는 공백을 제거.

    'kor' 모델은 글자 사이에 공백을 넣는 경향이 있어
    '수 확 함' → '수확함', '출 하' → '출하' 로 변환.
    반복 적용으로 연속 음절도 처리.
    """
    prev = None
    while prev != text:
        prev = text
        text = _HAN_RE.sub(r"\1\2", text)
    return text


# ─── 날짜 / 수확량 정규식 ─────────────────────────────────────────────────────
# 날짜: 공백 허용 ("1월 8 일", "1월8일" 모두 매칭)
_DATE_RE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")

# 수확/출하 키워드 (공백 제거 후 적용)
_HARVEST_RE = re.compile(r"수확|출하")

# 수량×단위 패턴: 앞에 OCR 노이즈 알파벳(S, B 등) 허용, 단위명 내 공백 허용
_QTY_UNIT_RE = re.compile(
    r"[A-Za-z]?(\d+(?:\.\d+)?)\s*"
    r"(회박스|지박스|스치\s*1kg|1kg\s*박스?|상박스?|박스|개|Box)",
    re.IGNORECASE,
)


def _line_to_kg(line: str) -> float:
    """한 줄에서 수확량(kg)을 파싱."""
    total = 0.0
    for m in _QTY_UNIT_RE.finditer(line):
        qty  = float(m.group(1))
        unit = m.group(2).strip()
        if "회박스" in unit:
            w = 0.25
        elif "지박스" in unit:
            w = 0.25
        elif re.search(r"스치|1kg", unit, re.IGNORECASE):
            w = 1.0
        elif "상박스" in unit:
            w = 0.5
        else:
            w = 0.5   # 기본 박스
        total += qty * w
    return total


def ocr_page(img_path: Path, lang: str = "kor+eng") -> str:
    """단일 이미지 OCR → 후처리 텍스트 반환."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        print("[ERROR] pytesseract/Pillow 미설치. 'pip install pytesseract Pillow' 실행 후 재시도.")
        sys.exit(1)

    pytesseract.pytesseract.tesseract_cmd = (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )
    img = Image.open(img_path)
    # PSM 3: 자동 페이지 분할 (레이아웃 분석 최소화), 손글씨 혼용에 적합
    raw = pytesseract.image_to_string(img, lang=lang, config="--psm 3")
    return _clean_ocr(raw)


def process_all() -> list[dict]:
    """전체 PNG OCR 및 수확 기록 추출."""
    png_files = sorted(JOURNAL_DIR.glob("*.png"))
    print(f"처리 대상: {len(png_files)}장")

    records: list[dict] = []
    no_date_cnt = 0

    for i, fpath in enumerate(png_files, 1):
        if i % 50 == 0:
            print(f"  진행: {i}/{len(png_files)}  (수확기록 누적: {len(records)}건)")

        try:
            text = ocr_page(fpath)
        except Exception as e:
            continue

        lines = [l for l in text.splitlines() if l.strip()]
        if not lines:
            continue

        # ── 날짜 추출: 첫 6줄 검색 ──────────────────────────────────────────
        date_str = None
        for line in lines[:6]:
            dm = _DATE_RE.search(line)
            if dm:
                m_val = int(dm.group(1))
                d_val = int(dm.group(2))
                if 1 <= m_val <= 12 and 1 <= d_val <= 31:
                    # 연도 추정: 9-12월 = 2022, 1-5월 = 2023
                    y = 2022 if m_val >= 9 else 2023
                    date_str = f"{y}-{m_val:02d}-{d_val:02d}"
                    break

        if date_str is None:
            no_date_cnt += 1
            continue

        # ── 수확량 추출 ──────────────────────────────────────────────────────
        day_kg = 0.0
        harvest_lines: list[str] = []
        for line in lines:
            if _HARVEST_RE.search(line):
                kg = _line_to_kg(line)
                if kg > 0:
                    day_kg += kg
                    harvest_lines.append(line.strip())

        # 이상값 필터: 4000m2 농가 일일 최대 수확량 250kg 초과 시 제외
        MAX_DAILY_KG = 250.0
        if 0 < day_kg <= MAX_DAILY_KG:
            records.append({
                "date":       date_str,
                "harvest_kg": round(day_kg, 2),
                "lines":      " | ".join(harvest_lines[:2]),
                "source":     fpath.name,
            })
        elif day_kg > MAX_DAILY_KG:
            pass  # OCR 오인식 이상값 무시

    print(f"  날짜 미인식: {no_date_cnt}장 / 수확기록 발견: {len(records)}건")
    return records


def main():
    import pandas as pd

    if not JOURNAL_DIR.exists():
        print(f"[ERROR] 영농일지 폴더 없음: {JOURNAL_DIR}")
        return

    print("=== SANWOO_Farm 영농일지 OCR 수확량 추출 ===")
    records = process_all()

    if not records:
        print("[WARNING] 수확 기록 없음 (OCR 인식 실패 또는 기록 없음)")
        print("  TIP: Tesseract 버전 / 한국어 팩 설치 확인")
        print("       C:/tools/tessdata/kor.traineddata 존재 여부 확인")
        return

    df = pd.DataFrame(records)
    df["date"]  = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.month
    df["year"]  = df["date"].dt.year

    # 같은 날 중복 합산
    df = (
        df.groupby("date")
        .agg({"harvest_kg": "sum", "month": "first", "year": "first",
              "lines": lambda x: " | ".join(x), "source": "first"})
        .reset_index()
        .sort_values("date")
    )

    print(f"\n수확 기록: {len(df)}일")
    with pd.option_context("display.max_colwidth", 80):
        print(df[["date", "harvest_kg", "lines"]].to_string(index=False))

    # ── 월별 집계 ────────────────────────────────────────────────────────────
    monthly = (
        df.groupby(["year", "month"])["harvest_kg"]
        .sum()
        .reset_index()
    )
    AREA_M2 = 4000.0   # 추정 면적 (27,000주 / 6.75주/m2)
    monthly["yield_per_m2"] = (monthly["harvest_kg"] / AREA_M2).round(4)
    print(f"\n월별 집계 (면적 {AREA_M2:.0f}m2 기준):")
    print(monthly.to_string(index=False))
    print(f"  연간 합계: {monthly['harvest_kg'].sum():.1f} kg"
          f" = {monthly['harvest_kg'].sum()/AREA_M2:.2f} kg/m2")

    # ── CSV 저장 ─────────────────────────────────────────────────────────────
    out_dir = ROOT / "scripts" / "data_integration"
    df.to_csv(out_dir / "sanwoo_strawberry_harvest_full.csv",
              index=False, encoding="utf-8-sig")
    monthly.to_csv(out_dir / "sanwoo_strawberry_monthly.csv",
                   index=False, encoding="utf-8-sig")
    print("\n[OK] CSV 저장 완료")
    print(f"  - {out_dir / 'sanwoo_strawberry_harvest_full.csv'}")
    print(f"  - {out_dir / 'sanwoo_strawberry_monthly.csv'}")

    # ── 다음 단계 안내 ────────────────────────────────────────────────────────
    print("\n=== 다음 단계: 딸기 M2 모델 통합 ===")
    print("1. SANWOO 학습 ZIP 생성:")
    print("   python scripts/data_integration/create_sanwoo_strawberry_2022.py")
    print("2. 딸기 M2 재학습:")
    print("   python scripts/train_stage2_yield.py --crop 딸기 --no-cache")


if __name__ == "__main__":
    main()
