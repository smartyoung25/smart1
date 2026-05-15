"""A6: Prophet 가격 예측 모델 학습 — 작목별 저장.

생산 CSV(출하일자, 판매금액, 총출하량)에서 월별 가격 시계열 추출 →
Prophet 모델 학습 → models/artifacts/{crop_en}/price_prophet.pkl 저장.

실행:
  python scripts/train_prophet_price.py            # 전 작목
  python scripts/train_prophet_price.py --crop 딸기

활용 (API 추론):
  from models.m4_revenue import M4RevenueModel
  model = M4RevenueModel().load(artifact_dir / "price_prophet.pkl")
  mean_price, lower, upper = model.forecast_price(horizon_days=30)
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import pickle
import sys
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

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.crop_config import CROP_CONFIGS, DATA_DIR, YEARS, get_artifact_dir


CROP_EN = {
    "딸기":       "strawberry",
    "방울토마토": "cherry_tomato",
    "완숙토마토": "tomato",
    "참외":       "melon",
    "파프리카":   "paprika",
}


def _norm_farm_id(v: str) -> str:
    try:
        return str(int(float(str(v).strip())))
    except (ValueError, OverflowError):
        return str(v).strip()


def load_monthly_price_series(crop_ko: str) -> pd.DataFrame:
    """생산 CSV에서 연도×월별 중앙 가격 시계열 구성.

    Returns:
        DataFrame with columns ['ds', 'y'] (ds=날짜, y=원/kg)
        — Prophet 입력 포맷
    """
    all_frames = []

    for year in YEARS:
        zp = DATA_DIR / f"스마트팜_{year}.zip"
        if not zp.exists():
            continue
        with zipfile.ZipFile(zp) as zf:
            for info in zf.infolist():
                if not info.filename.lower().endswith(".csv"):
                    continue
                try:
                    raw = zf.read(info.filename)
                    df = pd.read_csv(io.BytesIO(raw), encoding="euc-kr", low_memory=False)
                    if "품목" not in df.columns:
                        continue
                    dc = df[df["품목"].astype(str).str.strip() == crop_ko].copy()
                    if dc.empty:
                        continue
                    if "출하일자" not in dc.columns or "판매금액" not in dc.columns:
                        continue
                    if "총출하량" not in dc.columns:
                        continue
                    dc["dt"] = pd.to_datetime(dc["출하일자"], errors="coerce")
                    dc["year"]  = year
                    dc["month"] = dc["dt"].dt.month
                    dc["판매금액"]   = pd.to_numeric(dc["판매금액"],  errors="coerce").fillna(0)
                    dc["총출하량"]   = pd.to_numeric(dc["총출하량"],  errors="coerce").fillna(0)
                    dc = dc[dc["총출하량"] > 0].copy()
                    dc["price_krw_kg"] = dc["판매금액"] / dc["총출하량"]
                    dc = dc[dc["price_krw_kg"] > 100]  # 100원/kg 미만 이상값 제거
                    dc = dc[dc["price_krw_kg"] < 200_000]  # 200,000원/kg 초과 제거
                    all_frames.append(dc[["year", "month", "price_krw_kg"]])
                except Exception:
                    pass

    if not all_frames:
        logger.warning("  %s: 가격 데이터 없음", crop_ko)
        return pd.DataFrame(columns=["ds", "y"])

    raw = pd.concat(all_frames, ignore_index=True)

    # 연도×월별 중앙값 집계
    monthly = (
        raw.groupby(["year", "month"])["price_krw_kg"]
        .agg(["median", "count"])
        .reset_index()
        .rename(columns={"median": "price_median", "count": "n"})
    )
    # n이 너무 적은 달 제거 (신뢰성 낮음)
    monthly = monthly[monthly["n"] >= 3]

    if monthly.empty:
        return pd.DataFrame(columns=["ds", "y"])

    # Prophet 포맷: ds = 해당 월의 15일 (대표 날짜)
    monthly["ds"] = pd.to_datetime(
        monthly["year"].astype(str) + "-" +
        monthly["month"].astype(str).str.zfill(2) + "-15"
    )
    monthly = monthly.sort_values("ds").reset_index(drop=True)
    result = monthly[["ds", "y" if "y" in monthly.columns else "price_median"]].copy()
    result = result.rename(columns={"price_median": "y"})

    logger.info("  %s: %d개 월별 가격 데이터 포인트 (%.0f~%.0f원/kg)",
                crop_ko, len(result), result["y"].min(), result["y"].max())
    return result[["ds", "y"]]


def train_prophet_for_crop(crop_ko: str) -> dict | None:
    """작목별 Prophet 학습 및 저장."""
    crop_en = CROP_EN.get(crop_ko)
    if not crop_en:
        logger.error("  지원하지 않는 작목: %s", crop_ko)
        return None

    logger.info("=" * 50)
    logger.info("Prophet 학습: %s (%s)", crop_ko, crop_en)
    logger.info("=" * 50)

    # 가격 시계열 로드
    price_df = load_monthly_price_series(crop_ko)
    if price_df.empty or len(price_df) < 12:
        logger.warning("  데이터 부족(%d개) — Prophet 건너뜀", len(price_df))
        return None

    # Prophet 학습
    try:
        from prophet import Prophet
    except ImportError:
        logger.error("  Prophet 미설치: pip install prophet")
        return None

    m = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        interval_width=0.80,
        changepoint_prior_scale=0.05,     # 추세 변화 유연성 (기본 0.05)
        seasonality_prior_scale=10.0,     # 계절성 강도
    )

    import logging as _log
    _log.getLogger("cmdstanpy").setLevel(_log.WARNING)
    _log.getLogger("prophet").setLevel(_log.WARNING)

    m.fit(price_df)
    logger.info("  Prophet 학습 완료 (%d개 학습 포인트)", len(price_df))

    # 미래 1년 예측 검증
    future = m.make_future_dataframe(periods=12, freq="MS")
    forecast = m.predict(future)
    next12 = forecast.tail(12)
    logger.info("  향후 12개월 예측: 평균=%.0f원/kg (%.0f~%.0f)",
                next12["yhat"].mean(),
                next12["yhat_lower"].mean(),
                next12["yhat_upper"].mean())

    # 학습 데이터 내 MAE (자체 검증)
    train_pred = forecast[forecast["ds"].isin(price_df["ds"])]["yhat"]
    mae = float(np.abs(price_df["y"].values - train_pred.values).mean())
    mape = float(np.abs(
        (price_df["y"].values - train_pred.values) / price_df["y"].values
    ).mean() * 100)
    logger.info("  학습셋 MAE=%.0f원/kg  MAPE=%.1f%%", mae, mape)

    # 저장
    art_dir = get_artifact_dir(crop_en)
    save_path = art_dir / "price_prophet.pkl"
    bundle = {
        "prophet":      m,
        "crop_ko":      crop_ko,
        "crop_en":      crop_en,
        "n_train":      len(price_df),
        "price_range":  [float(price_df["y"].min()), float(price_df["y"].max())],
        "train_mape":   round(mape, 1),
        "train_mae":    round(mae, 0),
    }
    with open(save_path, "wb") as f:
        pickle.dump(bundle, f)
    logger.info("  저장: %s", save_path)

    # 메타 JSON
    meta_path = art_dir / "price_prophet_meta.json"
    meta = {k: v for k, v in bundle.items() if k != "prophet"}
    meta["saved_at"] = pd.Timestamp.now().isoformat()
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return meta


def main():
    parser = argparse.ArgumentParser(description="Prophet 가격 예측 모델 학습")
    parser.add_argument("--crop", default="all", help="작목명 또는 'all'")
    args = parser.parse_args()

    targets = list(CROP_CONFIGS.keys()) if args.crop == "all" else [args.crop]

    results = {}
    for crop in targets:
        r = train_prophet_for_crop(crop)
        if r:
            results[crop] = r

    logger.info("\n=== Prophet 학습 완료 ===")
    for crop, r in results.items():
        logger.info("  %-10s  MAPE=%.1f%%  n=%d",
                    crop, r.get("train_mape", 0), r.get("n_train", 0))


if __name__ == "__main__":
    main()
