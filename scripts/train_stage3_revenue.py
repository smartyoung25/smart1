"""Stage 3: 수확량 × 가격 → 매출 Ridge 보정 학습.

이 스크립트는 Stage 2에서 생성된 yield_per_m2 예측값(또는 실제값)과
price_stats.json의 가격 데이터를 결합하여 Ridge 보정 계수를 추정한다.

실행:
  python scripts/train_stage3_revenue.py --crop 딸기
  python scripts/train_stage3_revenue.py --crop all
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

from models.crop_config import (
    CROP_CONFIGS, DATA_DIR, YEARS, get_artifact_dir,
)

AREA_DEFAULTS = {
    "딸기": 1200.0, "방울토마토": 1600.0, "완숙토마토": 1400.0,
    "참외": 3800.0, "파프리카": 2500.0,
}


def _norm_farm_id(v: str) -> str:
    try:
        return str(int(float(str(v).strip())))
    except (ValueError, OverflowError):
        return str(v).strip()


def _norm_keys(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["year", "month"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float").astype("Int64")
    if "farm_id" in df.columns:
        df["farm_id"] = df["farm_id"].astype(str).str.strip().apply(_norm_farm_id)
    return df


def load_price_stats(crop_ko: str) -> tuple[float, float, float]:
    """price_stats.json에서 작목별 가격 통계 로드."""
    price_path = ROOT / "api" / "data" / "price_stats.json"
    defaults = {
        "딸기": (9000.0, 6300.0, 11700.0),
        "방울토마토": (3800.0, 2660.0, 4940.0),
        "완숙토마토": (2700.0, 1890.0, 3510.0),
        "참외": (5000.0, 3500.0, 6500.0),
        "파프리카": (6500.0, 4550.0, 8450.0),
    }
    if not price_path.exists():
        return defaults.get(crop_ko, (5000.0, 3500.0, 6500.0))

    stats = json.loads(price_path.read_text(encoding="utf-8"))
    # price_stats.json은 {"by_crop": {"딸기": {...}}} 구조
    crop_dict = stats.get("by_crop", stats)
    d = crop_dict.get(crop_ko, {})
    if isinstance(d, dict):
        med = float(d.get("median_krw_kg", d.get("mean", 5000.0)))
        p25 = float(d.get("p25_krw_kg", med * 0.7))
        p75 = float(d.get("p75_krw_kg", med * 1.3))
        return med, p25, p75
    return defaults.get(crop_ko, (5000.0, 3500.0, 6500.0))


def load_monthly_price_map(crop_ko: str) -> dict[str, float]:
    """price_stats.json monthly_trend에서 월별 중앙값 반환 {month_str: krw_kg}.

    월별 가격 피처로 사용 → 계절성 반영 (파프리카: 1월 5,000원 vs 7월 2,000원 등)
    """
    price_path = ROOT / "api" / "data" / "price_stats.json"
    if not price_path.exists():
        return {}
    stats = json.loads(price_path.read_text(encoding="utf-8"))
    monthly = stats.get("monthly_trend", {}).get(crop_ko, {})
    return {m: float(v.get("median_krw_kg", 0)) for m, v in monthly.items()
            if v.get("median_krw_kg", 0) > 0}


def load_production_with_revenue(crop_ko: str) -> pd.DataFrame:
    """생산 데이터 로드 — yield_kg, revenue_krw, area_m2 포함.

    면적은 Stage2와 동일한 재배정보 CSV year+farm_id 복합키 기반으로 로드.
    """
    # Stage2의 load_area_map 재활용 (재배정보 CSV year+farm_id 복합키)
    try:
        from scripts.train_stage2_yield import load_area_map as _s2_load_area_map
        area_map = _s2_load_area_map(crop_ko)
    except Exception:
        area_map = {}

    default_area = AREA_DEFAULTS.get(crop_ko, 1200.0)
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
                    if "품목" not in df.columns or "출하일자" not in df.columns:
                        continue
                    dc = df[df["품목"].astype(str).str.strip() == crop_ko].copy()
                    if dc.empty or "총출하량" not in dc.columns:
                        continue
                    dc["dt"] = pd.to_datetime(dc["출하일자"], errors="coerce")
                    dc["year"] = year
                    dc["month"] = dc["dt"].dt.month
                    farm_col = next((c for c in ["농가명", "농가ID"] if c in dc.columns), None)
                    dc["farm_id"] = dc[farm_col].astype(str).str.strip().apply(_norm_farm_id) \
                        if farm_col else "unknown"
                    dc["총출하량"] = pd.to_numeric(dc.get("총출하량", 0), errors="coerce").fillna(0).clip(lower=0)
                    dc["판매금액"] = pd.to_numeric(dc.get("판매금액", 0), errors="coerce").fillna(0).clip(lower=0)
                    agg = (dc.groupby(["farm_id", "year", "month"])
                           .agg({"총출하량": "sum", "판매금액": "sum"})
                           .reset_index()
                           .rename(columns={"총출하량": "yield_kg", "판매금액": "revenue_krw"}))
                    all_frames.append(agg)
                except Exception:
                    pass

    if not all_frames:
        return pd.DataFrame()

    prod = _norm_keys(pd.concat(all_frames, ignore_index=True))

    # 면적: year+farm_id 복합키 우선, 없으면 단순 farm_id, 없으면 기본값
    year_key = prod["year"].astype(str) + "_" + prod["farm_id"].astype(str)
    prod["area_m2"] = year_key.map(area_map)
    missing = prod["area_m2"].isna()
    if missing.any():
        prod.loc[missing, "area_m2"] = prod.loc[missing, "farm_id"].map(area_map)
    prod["area_m2"] = prod["area_m2"].fillna(default_area)

    prod["yield_per_m2"]   = prod["yield_kg"] / prod["area_m2"].replace(0, default_area)
    prod["revenue_per_m2"] = prod["revenue_krw"] / prod["area_m2"].replace(0, default_area)

    # 유효 행만 (수확 있고, 단가 계산 가능)
    mask = (prod["yield_per_m2"] > 0) & (prod["revenue_per_m2"] > 0)
    prod = prod[mask].copy()

    # 실제 단가 계산 + 이상치 필터링 (IQR, 최소 100원/kg 이상)
    prod["price_actual"] = prod["revenue_krw"] / prod["yield_kg"].replace(0, np.nan)
    q1 = prod["price_actual"].quantile(0.01)
    q3 = prod["price_actual"].quantile(0.99)
    prod = prod[(prod["price_actual"] >= max(100.0, q1)) & (prod["price_actual"] <= q3)].copy()

    n_area_matched = int((~year_key.reindex(prod.index).isna()).sum()) if len(prod) > 0 else 0
    logger.info("  수익 데이터: %d행 (yield 중앙=%.3f, price 중앙=%.0f원/kg, 면적기본값=%.0fm²)",
                len(prod), prod["yield_per_m2"].median(),
                prod["price_actual"].median(), default_area)
    return prod


def train_stage3(crop_ko: str) -> dict | None:
    """Ridge 보정 계수 학습."""
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import mean_absolute_percentage_error

    config = CROP_CONFIGS.get(crop_ko)
    if not config:
        return None

    logger.info("=" * 55)
    logger.info("Stage 3 학습: %s", crop_ko)
    logger.info("=" * 55)

    prod = load_production_with_revenue(crop_ko)
    if prod.empty:
        logger.error("  수익 데이터 없음 — 스킵")
        return None

    price_med, price_p25, price_p75 = load_price_stats(crop_ko)
    monthly_price_map = load_monthly_price_map(crop_ko)
    n_monthly_prices = len(monthly_price_map)
    logger.info("  가격 통계: 중앙=%.0f p25=%.0f p75=%.0f 원/kg (월별분해=%d개월)",
                price_med, price_p25, price_p75, n_monthly_prices)

    def _get_monthly_price(month_val: float) -> float:
        """월별 가격 조회 — monthly_trend 우선, 없으면 전체 중앙값."""
        key = str(int(month_val)) if not np.isnan(month_val) else ""
        p = monthly_price_map.get(key, 0.0)
        return p if p > 0 else price_med

    n = len(prod)
    if n < 10:
        logger.warning("  샘플 부족(%d) — Ridge 스킵, 순수 곱셈 사용", n)
        monthly_prices = prod["month"].astype(float).map(_get_monthly_price)
        mape_pure = float(mean_absolute_percentage_error(
            prod["revenue_per_m2"].values,
            prod["yield_per_m2"].values * monthly_prices.values
        ) * 100)
        logger.info("  순수 곱셈 MAPE: %.1f%%", mape_pure)
        gate_passed = mape_pure <= 20.0
        return {
            "crop_ko": crop_ko, "crop_en": config.crop_en,
            "ridge": None,
            "price_median": price_med, "price_p25": price_p25, "price_p75": price_p75,
            "mape": round(mape_pure, 1),
            "gate_passed": gate_passed, "n_train": n,
        }

    # TimeSeriesSplit
    prod_sorted = prod.sort_values(["year", "month"])
    # 월별 가격 피처 (연간 단일값 대신 월별 계절 가격 사용)
    monthly_prices_s = prod_sorted["month"].astype(float).map(_get_monthly_price)
    # 가격 계절성 지수 (월별/연간 비율)
    price_seasonality_s = monthly_prices_s / (price_med + 1e-9)

    X_s = np.column_stack([
        np.log1p(prod_sorted["yield_per_m2"].values),
        np.log1p(monthly_prices_s.values),       # 월별 가격 (핵심 개선)
        prod_sorted["month"].astype(float).values,
        price_seasonality_s.values,              # 계절성 지수
    ])
    y_s = np.log1p(prod_sorted["revenue_per_m2"].values)
    n_feats = X_s.shape[1]

    n_splits = 3 if n < 100 else 4
    tscv = TimeSeriesSplit(n_splits=n_splits)
    cv_mape = []
    for tr_idx, val_idx in tscv.split(X_s):
        m = Ridge(alpha=1.0)
        m.fit(X_s[tr_idx], y_s[tr_idx])
        y_pred = np.expm1(m.predict(X_s[val_idx]))
        y_true = np.expm1(y_s[val_idx])
        cv_mape.append(float(mean_absolute_percentage_error(y_true, y_pred) * 100))

    cv_mape_mean = float(np.mean(cv_mape))
    logger.info("  CV MAPE=%.1f%%  (n_splits=%d)", cv_mape_mean, n_splits)

    # 전체 학습
    ridge = Ridge(alpha=1.0)
    ridge.fit(X_s, y_s)
    y_pred_all = np.expm1(ridge.predict(X_s))
    final_mape = float(mean_absolute_percentage_error(
        np.expm1(y_s), y_pred_all) * 100)

    gate_passed = cv_mape_mean <= 20.0
    logger.info("  최종 MAPE=%.1f%%  게이트=%s",
                final_mape, "✅ PASS" if gate_passed else "❌ FAIL")

    feat_names = ["log_yield", "log_price_monthly", "month", "price_seasonality"]
    return {
        "crop_ko": crop_ko, "crop_en": config.crop_en,
        "ridge": ridge,
        "feature_names": feat_names[:n_feats],
        "price_median": price_med, "price_p25": price_p25, "price_p75": price_p75,
        "monthly_price_map": monthly_price_map,
        "cv_mape_mean": round(cv_mape_mean, 1),
        "mape": round(final_mape, 1),
        "gate_passed": gate_passed, "n_train": n,
    }


def run_crop(crop_ko: str) -> dict | None:
    result = train_stage3(crop_ko)
    if not result:
        return None

    config   = CROP_CONFIGS[crop_ko]
    art_dir  = get_artifact_dir(config.crop_en)
    pkl_path = art_dir / "stage3_revenue_coef.pkl"
    meta_path = art_dir / "stage3_meta.json"

    bundle = {
        "ridge": result.get("ridge"),
        "feature_names": result.get("feature_names", []),
        "price_median": result["price_median"],
        "price_p25":    result["price_p25"],
        "price_p75":    result["price_p75"],
    }
    with open(pkl_path, "wb") as f:
        pickle.dump(bundle, f)

    meta = {k: v for k, v in result.items() if k != "ridge"}
    meta["stage"] = 3
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("  저장: %s", pkl_path)
    return meta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--crop", default="all")
    args = parser.parse_args()
    targets = list(CROP_CONFIGS.keys()) if args.crop == "all" else [args.crop]

    results = {}
    for crop in targets:
        r = run_crop(crop)
        if r:
            results[crop] = r

    logger.info("\n=== Stage 3 완료 ===")
    for crop, r in results.items():
        logger.info("  %-10s MAPE=%.1f%%  PASS=%s",
                    crop, r.get("mape", 0), r["gate_passed"])


if __name__ == "__main__":
    main()
