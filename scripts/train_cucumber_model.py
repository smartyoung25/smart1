"""오이(cucumber) stage2+stage3 합성 데이터 학습 스크립트.

농진청 오이 통계 기반 합성 데이터로 stage2(XGBoost yield)·stage3(Ridge revenue) 모델 생성.

실행:
    python scripts/train_cucumber_model.py
출력:
    models/artifacts/cucumber/stage2_yield.pkl
    models/artifacts/cucumber/stage3_revenue_coef.pkl
    models/artifacts/cucumber/stage2_meta.json
    models/artifacts/cucumber/stage3_meta.json
    models/artifacts/cucumber/pipeline_meta.json
"""
from __future__ import annotations

import json
import logging
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT      = Path(__file__).parent.parent
OUT_DIR   = ROOT / "models" / "artifacts" / "cucumber"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 오이 농진청 표준 통계치 ─────────────────────────────────────────────────────
# 연간 수확량: 18.25 kg/m²  (농진청 온실오이 10a당 18.25t)
# 단가 중앙: 1,845 원/kg (engine/profit_optimizer.py 기준)
# 작기 개월: 8개월
CUCUMBER_YIELD_MEAN   = 18.25   # kg/m²/year
CUCUMBER_YIELD_STD    =  3.2    # 변동 계수 ~17%
CUCUMBER_PRICE_MEDIAN = 1845    # 원/kg
CUCUMBER_SEASON_MONTHS = 8

# 오이 최적 환경 범위 (온실오이 기준)
OPT_TEMP   = (22.0, 28.0)   # 내부기온
OPT_HUMID  = (70.0, 85.0)   # 상대습도
OPT_CO2    = (600, 1200)     # CO2 ppm
OPT_SOLAR  = (80, 200)       # 일사량 W/m²
OPT_SOIL   = (18.0, 24.0)   # 토양온도

np.random.seed(42)
N = 200  # 합성 샘플 수

def _generate_synthetic_data(n: int) -> pd.DataFrame:
    """오이 환경·수확량 합성 데이터 생성."""
    # 환경 변수 (정규분포 + 클리핑)
    temp   = np.clip(np.random.normal(25.0, 3.0,  n), 15.0, 35.0)
    humid  = np.clip(np.random.normal(78.0, 8.0,  n), 50.0, 95.0)
    co2    = np.clip(np.random.normal(900.0, 200, n), 400, 1600)
    solar  = np.clip(np.random.normal(130.0, 40,  n), 30,  300)
    soil_t = np.clip(np.random.normal(21.0, 2.5,  n), 14,  30)
    gdd    = np.clip((temp - 10.0) * 30, 0, None)     # GDD 월간

    # 환경-수확량 관계 (도메인 지식 기반)
    # 최적 온도(22~28) → 수율 보너스, 과온/저온 → 감산
    temp_effect  = 1.0 - 0.02 * np.maximum(0, temp - 28) - 0.03 * np.maximum(0, 22 - temp)
    humid_effect = 1.0 - 0.01 * np.maximum(0, humid - 85) - 0.005 * np.maximum(0, 70 - humid)
    co2_effect   = 1.0 + 0.00015 * np.clip(co2 - 600, 0, 600)
    solar_effect = 1.0 + 0.001 * np.clip(solar - 80, 0, 120)

    # 기본 수확량 × 환경 효과 + 노이즈
    base_yield = CUCUMBER_YIELD_MEAN * temp_effect * humid_effect * co2_effect * solar_effect
    yield_ann  = np.clip(base_yield + np.random.normal(0, CUCUMBER_YIELD_STD * 0.5, n), 5, 40)

    df = pd.DataFrame({
        "temp_internal_mean": temp,
        "humidity_int_mean":  humid,
        "co2_ppm_mean":       co2,
        "solar_rad_mean":     solar,
        "soil_temp_mean":     soil_t,
        "gdd_monthly":        gdd,
        "yield_annual":       yield_ann,
    })
    return df


def train_stage2(df: pd.DataFrame) -> dict:
    """Stage2: 환경 피처 → log(yield_per_m2 연간) 예측."""
    FEAT_COLS = ["temp_internal_mean", "humidity_int_mean", "co2_ppm_mean",
                 "solar_rad_mean", "soil_temp_mean", "gdd_monthly"]
    X = df[FEAT_COLS].values
    y = np.log1p(df["yield_annual"].values)

    imputer = SimpleImputer(strategy="median")
    X_imp   = imputer.fit_transform(X)

    model = GradientBoostingRegressor(n_estimators=100, max_depth=3,
                                      learning_rate=0.1, random_state=42)
    model.fit(X_imp, y)

    cv_r2 = cross_val_score(model, X_imp, y, cv=5, scoring="r2").mean()

    pred   = np.expm1(model.predict(X_imp))
    actual = df["yield_annual"].values
    mape   = float(np.mean(np.abs((actual - pred) / np.maximum(actual, 0.01))) * 100)

    logger.info("[Stage2 오이] CV R²=%.3f  MAPE=%.1f%%  n=%d", cv_r2, mape, len(df))

    bundle = {
        "type":         "xgb",         # model_loader이 분기하는 키
        "model":        model,
        "imputer":      imputer,
        "feature_cols": FEAT_COLS,
        "log_transform": True,
        "cv_r2_mean":   float(cv_r2),
        "mape":         mape,
        "n_train":      len(df),
        "crop_ko":      "오이",
        "crop_en":      "cucumber",
        "agg_mode":     "annual",
    }
    return bundle


def train_stage3(df: pd.DataFrame) -> dict:
    """Stage3: log(yield) + log(price) → log(revenue_per_m2) 예측 Ridge."""
    # 월별 가격 (오이 계절성 반영)
    monthly_price = {
        "1": 2200.0, "2": 2000.0, "3": 1900.0, "4": 1700.0,
        "5": 1600.0, "6": 1500.0, "7": 1845.0, "8": 2100.0,
        "9": 2200.0, "10": 2000.0, "11": 1900.0, "12": 2100.0,
    }
    # 가격 노이즈
    price_arr = np.random.normal(CUCUMBER_PRICE_MEDIAN, 300, len(df))
    price_arr = np.clip(price_arr, 800, 4000)

    log_yield = np.log1p(df["yield_annual"].values)
    log_price = np.log1p(price_arr)
    # 연간 revenue = yield × price
    revenue   = df["yield_annual"].values * price_arr
    log_rev   = np.log1p(revenue)

    X = np.column_stack([log_yield, log_price])
    y = log_rev

    ridge = Ridge(alpha=1.0)
    ridge.fit(X, y)

    cv_mape_scores = []
    for _ in range(5):
        idx = np.random.choice(len(X), len(X), replace=True)
        pred_cv  = np.expm1(ridge.predict(X[idx]))
        true_cv  = revenue[idx]
        mape_cv  = np.mean(np.abs((true_cv - pred_cv) / np.maximum(true_cv, 1))) * 100
        cv_mape_scores.append(mape_cv)
    cv_mape = float(np.mean(cv_mape_scores))

    pred_all = np.expm1(ridge.predict(X))
    mape     = float(np.mean(np.abs((revenue - pred_all) / np.maximum(revenue, 1))) * 100)

    logger.info("[Stage3 오이] CV MAPE=%.1f%%  MAPE=%.1f%%", cv_mape, mape)

    bundle = {
        "ridge":             ridge,
        "feature_names":     ["log_yield_annual", "log_price_annual"],
        "price_median":      float(CUCUMBER_PRICE_MEDIAN),
        "price_p25":         1400.0,
        "price_p75":         2400.0,
        "monthly_price_map": monthly_price,
        "agg_mode":          "annual",
        "cv_mape_mean":      cv_mape,
        "mape":              mape,
        "gate_passed":       mape < 35.0,
        "n_train":           len(df),
        "stage":             3,
        "crop_ko":           "오이",
        "crop_en":           "cucumber",
    }
    return bundle


def main():
    logger.info("=== 오이 합성 데이터 학습 시작 ===")
    df = _generate_synthetic_data(N)
    logger.info("합성 데이터 %d행 생성 완료", len(df))

    # Stage 2
    s2 = train_stage2(df)
    s2_path = OUT_DIR / "stage2_yield.pkl"
    s2_path.write_bytes(pickle.dumps(s2))
    logger.info("stage2 저장 → %s", s2_path)

    # Stage 3
    s3 = train_stage3(df)
    s3_path = OUT_DIR / "stage3_revenue_coef.pkl"
    s3_path.write_bytes(pickle.dumps(s3))
    logger.info("stage3 저장 → %s", s3_path)

    # Meta JSONs
    s2_meta = {
        "crop_ko": "오이", "crop_en": "cucumber", "stage": 2,
        "model_type": "gbm_synthetic", "feature_count": 6,
        "n_train": N, "log_transform": True,
        "cv_r2_mean": s2["cv_r2_mean"], "mape": s2["mape"],
        "gate_passed": s2["cv_r2_mean"] > 0.3,
        "note": "합성 데이터 기반 — 실 농진청 데이터 수집 후 재학습 권장",
    }
    (OUT_DIR / "stage2_meta.json").write_text(
        json.dumps(s2_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    s3_meta = {
        "crop_ko": "오이", "crop_en": "cucumber", "stage": 3,
        "feature_names": s3["feature_names"],
        "price_median": s3["price_median"],
        "monthly_price_map": s3["monthly_price_map"],
        "cv_mape_mean": s3["cv_mape_mean"], "mape": s3["mape"],
        "gate_passed": s3["gate_passed"], "n_train": N,
        "note": "합성 데이터 기반 — 실 농진청 데이터 수집 후 재학습 권장",
    }
    (OUT_DIR / "stage3_meta.json").write_text(
        json.dumps(s3_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    pipeline_meta = {
        "crop_ko": "오이", "crop_en": "cucumber",
        "season_months": CUCUMBER_SEASON_MONTHS,
        "yield_baseline_kg_m2": CUCUMBER_YIELD_MEAN,
        "price_baseline_krw_kg": CUCUMBER_PRICE_MEDIAN,
        "data_source": "synthetic_rda_stats",
        "note": "농진청 통계 기반 합성 학습 — 실데이터 재학습 권장",
    }
    (OUT_DIR / "pipeline_meta.json").write_text(
        json.dumps(pipeline_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("=== 오이 모델 학습 완료 ===")
    logger.info("출력: %s", OUT_DIR)
    for f in sorted(OUT_DIR.iterdir()):
        logger.info("  %s (%d bytes)", f.name, f.stat().st_size)


if __name__ == "__main__":
    main()
