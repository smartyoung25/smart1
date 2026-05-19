"""STEP 5-C: M4 Prophet 가격 모델 학습

생산_2018~2022.csv 월별 평균 판매단가(원/kg) -> Prophet 학습
출력: models/artifacts/{crop_en}/price_prophet.pkl
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pickle
import logging
from pathlib import Path

import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).parent.parent
DATA_BASE = BASE_DIR / "기초자료" / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터"
ART_DIR   = BASE_DIR / "models" / "artifacts"

CROP_MAP = {
    "딸기":       "strawberry",
    "방울토마토": "cherry_tomato",
    "완숙토마토": "tomato",
    "참외":       "melon",
    "오이":       "cucumber",
}

# 작목별 파인튜닝 설정 (기본값 아래, 특수 케이스만 오버라이드)
CROP_CFG = {
    # crop_ko: {min_n, sigma_mult, cp_scale}
    "완숙토마토": {"min_n": 10, "sigma_mult": 2.0, "cp_scale": 0.10},
}
DEFAULT_CFG = {"min_n": 3, "sigma_mult": 3.0, "cp_scale": 0.05}

MIN_MONTHS   = 12
INTERVAL_W   = 0.80

# ── 1. 원본 CSV 로드 ──────────────────────────────────────────────────────────
logger.info("생산 CSV 로드 중...")
dfs = []
for year in range(2018, 2023):
    p = DATA_BASE / f"스마트팜_{year}" / f"생산_{year}" / f"생산_{year}.csv"
    if not p.exists():
        logger.warning("  파일 없음: %s", p)
        continue
    df = pd.read_csv(p, encoding="cp949", low_memory=False,
                     usecols=["품목", "출하일자", "총출하량", "판매금액"])
    dfs.append(df)

raw = pd.concat(dfs, ignore_index=True)
raw["date"] = pd.to_datetime(raw["출하일자"], errors="coerce")
raw = raw.dropna(subset=["date"])
raw = raw[raw["총출하량"] > 0]
raw["unit_price"] = raw["판매금액"] / raw["총출하량"]
raw = raw[raw["unit_price"].between(100, 200_000)]
logger.info("총 %d행 로드, 기간: %s ~ %s", len(raw), raw["date"].min().date(), raw["date"].max().date())

raw["month"] = raw["date"].dt.to_period("M").dt.to_timestamp()
monthly = (
    raw.groupby(["품목", "month"])
    .agg(y=("unit_price", "mean"), n=("unit_price", "count"))
    .reset_index()
)

# ── 2. 작목별 Prophet 학습 ────────────────────────────────────────────────────
from prophet import Prophet

results = {}

for crop_ko, crop_en in CROP_MAP.items():
    cfg = {**DEFAULT_CFG, **CROP_CFG.get(crop_ko, {})}
    logger.info("── %s (%s) Prophet 학습 (min_n=%d sigma=%.1f cp=%.2f) ──",
                crop_ko, crop_en, cfg["min_n"], cfg["sigma_mult"], cfg["cp_scale"])

    series = (monthly[(monthly["품목"] == crop_ko) & (monthly["n"] >= cfg["min_n"])]
              [["month", "y"]].rename(columns={"month": "ds"})
              .sort_values("ds").copy())

    if len(series) < MIN_MONTHS:
        logger.warning("  데이터 부족(%d개월) -- 스킵", len(series))
        continue

    # 이상치 제거
    mu, sigma = series["y"].mean(), series["y"].std()
    series = series[series["y"].between(mu - cfg["sigma_mult"]*sigma,
                                         mu + cfg["sigma_mult"]*sigma)]

    logger.info("  학습 데이터: %d개월 (%s ~ %s), 평균 %.0f원/kg",
                len(series), series["ds"].min().date(), series["ds"].max().date(),
                series["y"].mean())

    # hold-out MAPE (마지막 6개월)
    train_eval = series.iloc[:-6]
    test_eval  = series.iloc[-6:]
    if len(train_eval) >= MIN_MONTHS and len(test_eval) > 0:
        m_eval = Prophet(yearly_seasonality=True, weekly_seasonality=False,
                         daily_seasonality=False, interval_width=INTERVAL_W,
                         changepoint_prior_scale=cfg["cp_scale"])
        m_eval.fit(train_eval)
        fc_eval = m_eval.predict(test_eval[["ds"]])
        mape = float(np.abs((test_eval["y"].values - fc_eval["yhat"].values)
                            / test_eval["y"].values).mean() * 100)
    else:
        mape = 99.0

    gate_pass = mape <= 25.0
    logger.info("  검증 MAPE: %.1f%%  gate=%s", mape, "PASS" if gate_pass else "FAIL")

    # 전체 데이터로 최종 모델 학습
    m = Prophet(yearly_seasonality=True, weekly_seasonality=False,
                daily_seasonality=False, interval_width=INTERVAL_W,
                changepoint_prior_scale=cfg["cp_scale"])
    m.fit(series)

    art_path = ART_DIR / crop_en / "price_prophet.pkl"
    art_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "prophet":    m,
        "freq":       "MS",
        "crop_ko":    crop_ko,
        "crop_en":    crop_en,
        "n_train":    len(series),
        "train_from": str(series["ds"].min().date()),
        "train_to":   str(series["ds"].max().date()),
        "train_mape": round(mape, 2),
        "gate_passed": gate_pass,
        "mean_price": round(series["y"].mean(), 0),
    }
    with open(art_path, "wb") as f:
        pickle.dump(bundle, f)
    logger.info("  저장: %s", art_path)

    results[crop_ko] = {
        "crop_en": crop_en, "n_months": len(series),
        "mape": round(mape, 2), "gate": gate_pass,
        "mean_price": round(series["y"].mean(), 0)
    }

# ── 3. 요약 ──────────────────────────────────────────────────────────────────
print()
print("=" * 62)
print("M4 Prophet 학습 결과")
print("=" * 62)
print(f"{'작목':<12} {'n개월':>6} {'MAPE':>8} {'게이트':>8} {'평균단가':>10}")
print("-" * 62)
for crop_ko, r in results.items():
    gate_str = "PASS" if r["gate"] else "FAIL"
    print(f"{crop_ko:<12} {r['n_months']:>6} {r['mape']:>7.1f}% {gate_str:>8} {r['mean_price']:>9,.0f}원")
print("=" * 62)
print(f"저장: models/artifacts/{{crop_en}}/price_prophet.pkl")
