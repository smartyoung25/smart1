"""생산 CSV에서 월별 실제 단가 추출 → price_stats.json monthly_trend 추가.

생산_YYYY.CSV의 `판매금액 / 총출하량` = 실제 kg당 단가
출하일자.month × 품목별로 집계 → price_stats.json에 monthly_trend 섹션 추가

실행:
  python scripts/extract_monthly_price.py
"""
from __future__ import annotations

import io
import json
import logging
import warnings
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

ROOT      = Path(__file__).parent.parent
DATA_DIR  = ROOT / "기초자료" / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터"
PRICE_FILE = ROOT / "api" / "data" / "price_stats.json"
YEARS     = [2018, 2019, 2020, 2021, 2022]

CROPS_KO = ["딸기", "방울토마토", "완숙토마토", "참외", "파프리카"]


def load_production_all() -> pd.DataFrame:
    """전 연도 생산 CSV 로드 → 품목·출하월·단가 컬럼 포함."""
    frames = []
    for year in YEARS:
        zp = DATA_DIR / f"스마트팜_{year}.zip"
        if not zp.exists():
            logger.warning("ZIP 없음: %s", zp)
            continue
        with zipfile.ZipFile(zp) as zf:
            for info in zf.infolist():
                if not info.filename.lower().endswith(".csv"):
                    continue
                try:
                    raw = zf.read(info.filename)
                    df = pd.read_csv(io.BytesIO(raw), encoding="euc-kr",
                                     low_memory=False)
                    if "출하일자" not in df.columns or "총출하량" not in df.columns:
                        continue
                    if "품목" not in df.columns:
                        continue
                    df["year"] = year
                    df["month"] = pd.to_datetime(
                        df["출하일자"], errors="coerce").dt.month
                    df["총출하량"] = pd.to_numeric(df["총출하량"], errors="coerce")
                    df["판매금액"] = pd.to_numeric(
                        df.get("판매금액", 0), errors="coerce").fillna(0)
                    frames.append(df[["품목", "year", "month", "총출하량", "판매금액"]])
                except Exception:
                    pass

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def compute_monthly_price(prod: pd.DataFrame, crop_ko: str) -> dict:
    """작목별 월별 단가 통계 계산."""
    dc = prod[prod["품목"].astype(str).str.strip() == crop_ko].copy()
    dc = dc.dropna(subset=["month", "총출하량"])
    dc = dc[dc["총출하량"] > 0]
    if dc.empty:
        return {}

    # 행별 단가 계산 (거래 단위 단가)
    dc["price_per_kg"] = dc["판매금액"] / dc["총출하량"]
    dc = dc[dc["price_per_kg"] > 0]  # 0원 거래 제거

    result = {}
    for month in range(1, 13):
        m_data = dc[dc["month"] == month]["price_per_kg"].dropna()
        if len(m_data) < 5:
            continue
        # IQR 필터링 (이상치 제거)
        q1, q3 = m_data.quantile(0.25), m_data.quantile(0.75)
        iqr = q3 - q1
        m_data = m_data[(m_data >= q1 - 1.5*iqr) & (m_data <= q3 + 1.5*iqr)]
        result[str(month)] = {
            "median_krw_kg": round(float(m_data.median()), 0),
            "mean_krw_kg":   round(float(m_data.mean()), 0),
            "p25_krw_kg":    round(float(m_data.quantile(0.25)), 0),
            "p75_krw_kg":    round(float(m_data.quantile(0.75)), 0),
            "n":             int(len(m_data)),
        }

    return result


def main():
    logger.info("생산 CSV 로드 중...")
    prod = load_production_all()
    if prod.empty:
        logger.error("생산 데이터 없음 — 스킵")
        return

    logger.info("  전체 거래 기록: %d행", len(prod))

    # 기존 price_stats.json 로드
    if PRICE_FILE.exists():
        stats = json.loads(PRICE_FILE.read_text(encoding="utf-8"))
    else:
        stats = {}

    # monthly_trend 섹션 추가/갱신
    monthly_trend: dict[str, dict] = stats.get("monthly_trend", {})

    for crop_ko in CROPS_KO:
        monthly = compute_monthly_price(prod, crop_ko)
        if not monthly:
            logger.warning("  %s: 월별 단가 계산 불가 (데이터 부족)", crop_ko)
            continue

        monthly_trend[crop_ko] = monthly
        medians = {int(m): v["median_krw_kg"] for m, v in monthly.items()}
        logger.info("  %s: %d개월 단가 추출 (최저 %d원/kg @ %d월, 최고 %d원/kg @ %d월)",
                    crop_ko, len(monthly),
                    min(medians.values()), min(medians, key=medians.get),
                    max(medians.values()), max(medians, key=medians.get))

    stats["monthly_trend"] = monthly_trend
    stats["monthly_trend_note"] = "판매금액/총출하량 기반 실제 단가 월별 분해 (2018~2022)"

    PRICE_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    logger.info("price_stats.json 갱신 완료 → monthly_trend 추가")


if __name__ == "__main__":
    main()
