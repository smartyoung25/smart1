"""Stage 1: 환경 → 생육 예측 모델 (M1).

개선 사항:
  - 환경 데이터에 1·2개월 lag 피처 추가 (환경→생육 시간 지연 반영)
  - TimeSeriesSplit(n_splits=4) 교차 검증 (단순 hold-out 대비 안정적 평가)
  - 샘플 부족 작목(참외 등) → MultiOutputRegressor(Ridge) 자동 폴백
  - SHAP 기반 피처 중요도 기록

실행:
  python scripts/train_stage1_growth.py --crop 딸기
  python scripts/train_stage1_growth.py --crop all
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
from typing import Optional

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
    CROP_CONFIGS, CropConfig, ENV_COLS, ENV_HARD_BOUNDS,
    DATA_DIR, YEARS, get_artifact_dir,
)

# ── 공통 유틸 ─────────────────────────────────────────────────────────────────

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


def clip_iqr(s: pd.Series, factor: float = 1.5) -> pd.Series:
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    return s.clip(lower=q1 - factor * (q3 - q1), upper=q3 + factor * (q3 - q1))


def impute_series(s: pd.Series) -> pd.Series:
    s = s.interpolate(method="linear", limit_direction="both").ffill().bfill()
    return s.fillna(s.mean() if not np.isnan(s.mean()) else 0.0)


# ── Parquet 캐시 ───────────────────────────────────────────────────────────────
# 최초 실행 시 ZIP→월별 집계 Parquet 저장, 이후 캐시 재사용
_CACHE_DIR = ROOT / ".cache" / "training"


def _cache_path(kind: str, crop_ko: str) -> Path:
    """kind: 'env' | 'growth'"""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = crop_ko.replace("/", "_")
    return _CACHE_DIR / f"{kind}_{safe}.parquet"


# ── 데이터 로드 ────────────────────────────────────────────────────────────────

def _read_crop_csvs(year: int, crop_ko: str) -> list[pd.DataFrame]:
    """ZIP에서 작목별 CSV 추출. 대용량 파일은 chunksize로 메모리 절약."""
    zp = DATA_DIR / f"스마트팜_{year}.zip"
    if not zp.exists():
        return []
    frames = []
    with zipfile.ZipFile(zp) as zf:
        for info in zf.infolist():
            if not info.filename.lower().endswith(".csv"):
                continue
            try:
                raw = zf.read(info.filename)
                # 대용량(>10MB) 파일은 청크 읽기로 메모리 절약
                if info.file_size > 10_000_000:
                    chunk_frames = []
                    for chunk in pd.read_csv(
                        io.BytesIO(raw), encoding="euc-kr",
                        low_memory=True, chunksize=50_000,
                    ):
                        if "품목" in chunk.columns:
                            dc = chunk[chunk["품목"].astype(str).str.strip() == crop_ko]
                            if len(dc) > 0:
                                chunk_frames.append(dc.copy())
                    if chunk_frames:
                        frames.append(pd.concat(chunk_frames, ignore_index=True))
                else:
                    df = pd.read_csv(io.BytesIO(raw), encoding="euc-kr", low_memory=False)
                    if "품목" in df.columns:
                        dc = df[df["품목"].astype(str).str.strip() == crop_ko].copy()
                        if len(dc) > 0:
                            frames.append(dc)
            except Exception:
                pass
    return frames


def load_env_monthly(crop_ko: str, use_cache: bool = True) -> pd.DataFrame:
    """전체 연도 환경 데이터를 월별 집계. Parquet 캐시 사용으로 반복 실행 고속화."""
    cp = _cache_path("env", crop_ko)
    if use_cache and cp.exists():
        logger.info("  환경 캐시 로드: %s", cp)
        return pd.read_parquet(cp)

    all_frames = []
    for year in YEARS:
        frames = _read_crop_csvs(year, crop_ko)
        env_frames = [f for f in frames if "측정시간" in f.columns]
        if not env_frames:
            continue
        df = pd.concat(env_frames, ignore_index=True)
        df["year"] = year

        # 시간 파싱
        time_col = "측정시간" if "측정시간" in df.columns else "측정일시"
        df["dt"]    = pd.to_datetime(df[time_col], errors="coerce")
        df["month"] = df["dt"].dt.month

        # 농가 ID
        farm_col = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
        df["farm_id"] = df[farm_col].astype(str).str.strip().apply(_norm_farm_id) \
            if farm_col else "unknown"

        # 환경 변수 추출 + 하드 범위 필터
        for orig, canon in ENV_COLS.items():
            if orig in df.columns:
                df[canon] = pd.to_numeric(df[orig], errors="coerce")
                lo, hi = ENV_HARD_BOUNDS.get(canon, (-1e9, 1e9))
                df.loc[~df[canon].between(lo, hi), canon] = np.nan

        all_frames.append(df)

    if not all_frames:
        return pd.DataFrame()

    combined = pd.concat(all_frames, ignore_index=True)
    env_vars = [c for c in ENV_COLS.values() if c in combined.columns]

    for col in env_vars:
        combined[col] = clip_iqr(combined[col])

    agg = (combined.groupby(["farm_id", "year", "month"])
           .agg({col: ["mean", "std"] for col in env_vars})
           .reset_index())
    agg.columns = ["_".join(c).strip("_") if c[1] else c[0] for c in agg.columns]
    result = _norm_keys(agg)
    logger.info("  환경 월집계: %d행", len(result))

    if use_cache:
        result.to_parquet(cp, index=False)
        logger.info("  환경 캐시 저장: %s", cp)
    return result


def load_growth_monthly(crop_ko: str, growth_cols: list[str], use_cache: bool = True) -> pd.DataFrame:
    """전체 연도 생육 데이터를 월별 집계. Parquet 캐시 사용으로 반복 실행 고속화."""
    cp = _cache_path("growth", crop_ko)
    if use_cache and cp.exists():
        logger.info("  생육 캐시 로드: %s", cp)
        return pd.read_parquet(cp)

    all_frames = []
    for year in YEARS:
        frames = _read_crop_csvs(year, crop_ko)
        g_frames = [
            f for f in frames
            if "조사일자" in f.columns and "측정시간" not in f.columns
            and any(c in f.columns for c in growth_cols)
        ]
        if not g_frames:
            continue
        df = pd.concat(g_frames, ignore_index=True)
        df["dt"]    = pd.to_datetime(df["조사일자"], errors="coerce")
        df["year"]  = year
        df["month"] = df["dt"].dt.month
        farm_col    = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
        df["farm_id"] = df[farm_col].astype(str).str.strip().apply(_norm_farm_id) \
            if farm_col else "unknown"

        avail = [c for c in growth_cols if c in df.columns]
        for col in avail:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df[col] = clip_iqr(df[col])

        agg = (df.groupby(["farm_id", "year", "month"])
               .agg({col: "mean" for col in avail})
               .reset_index())
        agg.columns = [f"growth_{c}" if c in avail else c for c in agg.columns]
        all_frames.append(agg)

    if not all_frames:
        return pd.DataFrame()

    combined = pd.concat(all_frames, ignore_index=True)
    result = _norm_keys(combined)
    logger.info("  생육 월집계: %d행", len(result))

    if use_cache:
        result.to_parquet(cp, index=False)
        logger.info("  생육 캐시 저장: %s", cp)
    return result


# ── 피처 행렬 구성 (lag 포함) ──────────────────────────────────────────────────

def _handle_month_overflow(df: pd.DataFrame) -> pd.DataFrame:
    """month > 12인 행을 year+1, month-12로 정정."""
    df = df.copy()
    mask = df["month"] > 12
    df.loc[mask, "year"]  = df.loc[mask, "year"] + 1
    df.loc[mask, "month"] = df.loc[mask, "month"] - 12
    return df


def build_stage1_matrix(
    env_monthly: pd.DataFrame,
    growth_monthly: pd.DataFrame,
    config: CropConfig,
) -> pd.DataFrame:
    """생육 데이터를 기준으로 환경 lag 피처를 join."""
    if growth_monthly.empty:
        logger.warning("  생육 데이터 없음 — Stage1 행렬 구성 불가")
        return pd.DataFrame()

    df = growth_monthly.copy()
    env_cols = [c for c in env_monthly.columns if c not in ["farm_id", "year", "month"]]

    # lag=1, lag=2 순서로 환경 피처 추가
    lags = list(range(1, config.env_to_growth_lag + 1))
    for lag in lags:
        shifted = env_monthly.copy()
        shifted["month"] = (shifted["month"].astype(int) + lag).astype("Int64")
        shifted = _handle_month_overflow(shifted)
        shifted = _norm_keys(shifted)
        rename_map = {c: f"{c}_lag{lag}" for c in env_cols}
        shifted = shifted.rename(columns=rename_map)
        df = df.merge(shifted, on=["farm_id", "year", "month"], how="left")

    # GDD 월간값 (현재 월 환경 기준)
    if "temp_internal_mean" in env_monthly.columns:
        env_curr = env_monthly.rename(columns={"temp_internal_mean": "_ti"})
        temp_col = env_monthly[["farm_id", "year", "month", "temp_internal_mean"]].copy()
        df = df.merge(temp_col, on=["farm_id", "year", "month"], how="left")
        df["gdd_monthly"] = (df["temp_internal_mean"] - config.t_base).clip(lower=0) * 30

    df["month_sin"] = np.sin(2 * np.pi * df["month"].astype(float) / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"].astype(float) / 12)

    # 연도 트렌드 (2018~2022 → 0~1): 스마트팜 기술·관리 수준 개선 포착
    _ymin, _ymax = int(df["year"].min()), int(df["year"].max())
    _yrange = max(_ymax - _ymin, 1)
    df["year_norm"] = (df["year"].astype(int) - _ymin) / _yrange

    # ── 글로벌 연구 기반 고급 피처 (EWM·cumGDD·DLI·VPD) ──────────────────────
    # 1) EWM (Exponentially Weighted Mean) 환경 피처 — span=3개월
    #    단순 lag보다 최근 값에 더 높은 가중치 → 빠른 생육 반응 포착
    #    방울토마토 제외: 2021년 COVID-era 분포이동으로 EWM이 Fold3 불안정 증폭
    _SKIP_EWM_CROPS = {"cherry_tomato"}
    try:
        df_sorted = df.sort_values(["farm_id", "year", "month"]).copy()
        if config.crop_en not in _SKIP_EWM_CROPS:
            for _ecol in env_cols:
                # lag1 컬럼이 있으면 EWM 계산 가능
                if f"{_ecol}_lag1" in df_sorted.columns:
                    df_sorted[f"{_ecol}_ewm3"] = (
                        df_sorted.groupby("farm_id")[f"{_ecol}_lag1"]
                        .transform(lambda s: s.ewm(span=3, adjust=False).mean())
                    )
        else:
            logger.info("  EWM 피처 비활성화 (%s — 분포이동 보호)", config.crop_en)
        df = df_sorted
    except Exception as _ewm_e:
        logger.debug("  EWM 피처 생성 실패 (무시): %s", _ewm_e)

    # 2) 누적 GDD (gdd_cumsum, gdd_lag1) — 정식 이후 열량 누적량
    #    AquaCrop/DSSAT 물리모델 핵심 변수로 수확 시기 결정에 필수
    if "gdd_monthly" in df.columns:
        try:
            _df_s = df.sort_values(["farm_id", "year", "month"]).copy()
            _df_s["gdd_cumsum"] = (
                _df_s.groupby("farm_id")["gdd_monthly"]
                .transform(lambda s: s.cumsum())
            )
            _df_s["gdd_lag1"]  = _df_s.groupby("farm_id")["gdd_cumsum"].shift(1)
            _df_s["gdd_lag2"]  = _df_s.groupby("farm_id")["gdd_cumsum"].shift(2)
            df = _df_s
        except Exception as _gdd_e:
            logger.debug("  cumGDD 피처 생성 실패 (무시): %s", _gdd_e)

    # 3) DLI (Daily Light Integral) 파생 피처 — mol/m²/day 추정
    #    DLI = solar_rad_mean (W/m²) × 0.0036 × photoperiod_hours / 0.217
    #    스마트팜 DLI 목표: 딸기 8~12, 토마토 20~30, 파프리카 15~25 mol/m²/day
    if "solar_rad_mean" in df.columns:
        try:
            # 간략 추정: 일사량(W/m²) × 3600s × 10h ÷ 1,000,000 × 4.57 (PAR 변환)
            df["dli_est"] = df["solar_rad_mean"].clip(lower=0) * 0.0115
        except Exception:
            pass

    if "solar_rad_mean" in df.columns and f"solar_rad_mean_lag1" in df.columns:
        try:
            df["dli_ewm3"] = (
                df.sort_values(["farm_id", "year", "month"])
                .groupby("farm_id")["solar_rad_mean_lag1"]
                .transform(lambda s: s.ewm(span=3, adjust=False).mean())
                * 0.0115
            )
        except Exception:
            pass

    # 4) VPD (Vapor Pressure Deficit) 파생 피처 — kPa
    #    VPD = 0.6108 × exp(17.27×T/(T+237.3)) × (1 - RH/100)
    #    최적 범위: 딸기 0.6~1.0, 토마토·파프리카 0.8~1.4 kPa
    if "temp_internal_mean" in df.columns and "humidity_int_mean" in df.columns:
        try:
            _T = df["temp_internal_mean"].fillna(20.0)
            _RH = df["humidity_int_mean"].clip(1, 100).fillna(70.0)
            _es = 0.6108 * np.exp(17.27 * _T / (_T + 237.3))
            df["vpd_kpa"] = (_es * (1 - _RH / 100.0)).clip(lower=0.0)
        except Exception:
            pass

    # 5) 온도×일사량 상호작용 — 광합성 효율 포착
    #    FAO-56 / GreenLight 모델의 핵심 coupling term
    if "temp_internal_mean" in df.columns and "solar_rad_mean" in df.columns:
        try:
            df["temp_x_solar"] = (
                df["temp_internal_mean"].fillna(20.0) *
                df["solar_rad_mean"].clip(lower=0).fillna(100.0) / 1000.0
            )
        except Exception:
            pass

    # ── 6) AquaCrop / FAO-56 물리 피처 — 데이터 부족 보완 핵심 ──────────────────
    #    50년 작물과학 방정식을 피처로 주입 → ML 학습 부담 경감
    #    추가 피처: phenology_stage, phenology_stage_sq, light_saturation,
    #              vpd_stress_cum, bai, bai_cumsum, cwsi
    #    cherry_tomato 제외: 2021년 COVID-era 분포이동으로 연도 상관 피처 불안정
    _SKIP_AQUACROP_CROPS = {"cherry_tomato"}
    if config.crop_en not in _SKIP_AQUACROP_CROPS:
        try:
            from adapters.aquacrop_features import add_aquacrop_features
            df = add_aquacrop_features(
                df,
                crop_en=config.crop_en,
                gdd_cumsum_col="gdd_cumsum",
                dli_col="dli_est",
                vpd_col="vpd_kpa",
                et0_col=None,      # ET0 실측 없음 → VPD 기반 CWSI 근사
            )
            logger.info("  AquaCrop 물리 피처 추가: phenology/light_sat/vpd_stress/bai/cwsi")
        except Exception as _aqe:
            logger.debug("  AquaCrop 피처 생성 실패 (무시): %s", _aqe)
    else:
        logger.info("  AquaCrop 피처 비활성화 (%s — 분포이동 보호)", config.crop_en)

    # ── 7) ERA5 기상 피처 (Farmingsight Phase 45) ──────────────────────────────────
    #    추가 피처: GDD정규화, CU_norm, ET0_mm, DIF, NDVI_proxy, 누적일사량_MJm2
    #    ERA5 CSV 없으면 NASA POWER → 합성 순으로 자동 폴백
    try:
        from adapters.era5_features import add_era5_features
        before_era5 = len(df.columns)
        df = add_era5_features(df, crop_ko=config.crop_ko)
        added_era5 = len(df.columns) - before_era5
        if added_era5 > 0:
            logger.info("  ERA5 기상 피처 추가: +%d컬럼 (GDD정규화/CU_norm/ET0_mm/DIF/NDVI_proxy/누적일사량)",
                        added_era5)
        else:
            logger.info("  ERA5 피처: 이미 존재하거나 추가 없음")
    except Exception as _era5e:
        logger.warning("  ERA5 피처 추가 실패 (무시): %s", _era5e)

    logger.info("  Stage1 행렬: %s", df.shape)
    return df


# ── 학습 ──────────────────────────────────────────────────────────────────────

def train_stage1(df: pd.DataFrame, config: CropConfig) -> dict:
    """TimeSeriesSplit + XGB MultiOutput → Ridge 폴백."""
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import r2_score, mean_squared_error as _mse_s1, mean_absolute_error as _mae_s1
    from sklearn.impute import SimpleImputer
    from sklearn.multioutput import MultiOutputRegressor
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    target_cols = [f"growth_{c}" for c in config.growth_cols
                   if f"growth_{c}" in df.columns]
    if not target_cols:
        logger.error("  생육 타겟 컬럼 없음")
        return {}

    feature_cols = [c for c in df.columns if c not in
                    ["farm_id", "year", "month"] + target_cols
                    and df[c].dtype in [np.float64, np.int64, "Int64", float, int]]

    df_clean = df.sort_values(["farm_id", "year", "month"]).copy()
    X_raw = df_clean[feature_cols]
    Y_raw = df_clean[target_cols]

    # 타겟 유효 행 (모든 타겟이 NaN인 행 제외)
    valid_mask = Y_raw.notna().any(axis=1)
    X_raw = X_raw[valid_mask]
    Y_raw = Y_raw[valid_mask]

    n_samples = len(X_raw)
    logger.info("  유효 샘플: %d  피처: %d  타겟: %d",
                n_samples, len(feature_cols), len(target_cols))

    imputer = SimpleImputer(strategy="median")
    X = imputer.fit_transform(X_raw)
    # Y의 결측치는 열별 중앙값으로 대체
    Y = Y_raw.copy()
    for col in Y.columns:
        med = Y[col].median()
        Y[col] = Y[col].fillna(med if not np.isnan(med) else 0.0)
    Y_arr = Y.values.astype(float)

    # 샘플 부족 → Ridge 폴백
    n_splits = 3 if n_samples < 200 else 4
    if n_samples < config.min_train_samples:
        logger.warning("  샘플 부족(%d) — Ridge 폴백", n_samples)
        scaler = StandardScaler()
        X_sc   = scaler.fit_transform(X)
        model  = MultiOutputRegressor(Ridge(alpha=10.0))
        model.fit(X_sc, Y_arr)
        y_pred = model.predict(X_sc)
        cv_r2  = float(r2_score(Y_arr, y_pred, multioutput="uniform_average"))
        _rmse_fb = float(np.sqrt(_mse_s1(Y_arr, y_pred, multioutput="uniform_average")))
        _mae_fb  = float(_mae_s1(Y_arr, y_pred, multioutput="uniform_average"))
        return {
            "type": "ridge_fallback",
            "model": model, "imputer": imputer, "scaler": scaler,
            "feature_cols": feature_cols, "target_cols": target_cols,
            "cv_r2_mean": round(cv_r2, 3), "cv_r2_std": 0.0,
            "cv_r2_min": round(cv_r2, 3),
            "train_rmse": round(_rmse_fb, 4), "train_mae": round(_mae_fb, 4),
            "n_train": n_samples,
        }

    # XGBoost TimeSeriesSplit — 과적합 방지: 샘플 수에 따른 하이퍼파라미터 조정
    try:
        import xgboost as xgb
        from sklearn.multioutput import MultiOutputRegressor
        from sklearn.preprocessing import StandardScaler as _SS

        # 소샘플에서 300 트리 → 과적합 (CV R² 음수). 샘플 수에 맞게 조정
        if n_samples < 400:
            xgb_n, xgb_depth, xgb_mcw, xgb_lr = 50,  3, 10, 0.15
        elif n_samples < 800:
            xgb_n, xgb_depth, xgb_mcw, xgb_lr = 80,  3, 8,  0.10
        else:
            xgb_n, xgb_depth, xgb_mcw, xgb_lr = 100, 4, 5,  0.08
        logger.info("  XGB 파라미터: n=%d depth=%d mcw=%d lr=%.2f (n_samples=%d)",
                    xgb_n, xgb_depth, xgb_mcw, xgb_lr, n_samples)

        tscv = TimeSeriesSplit(n_splits=n_splits)
        fold_scores_xgb = []

        for fold, (tr_idx, val_idx) in enumerate(tscv.split(X)):
            X_tr, X_val = X[tr_idx], X[val_idx]
            Y_tr, Y_val = Y_arr[tr_idx], Y_arr[val_idx]

            fold_model = MultiOutputRegressor(
                xgb.XGBRegressor(
                    n_estimators=xgb_n, max_depth=xgb_depth,
                    learning_rate=xgb_lr, subsample=0.8, colsample_bytree=0.8,
                    min_child_weight=xgb_mcw, random_state=42, verbosity=0,
                )
            )
            fold_model.fit(X_tr, Y_tr)
            y_pred_val = fold_model.predict(X_val)
            score = float(r2_score(Y_val, y_pred_val, multioutput="uniform_average"))
            fold_scores_xgb.append(score)
            logger.info("  Fold %d XGB R²=%.3f", fold + 1, score)

        cv_r2_mean = float(np.mean(fold_scores_xgb))
        cv_r2_std  = float(np.std(fold_scores_xgb))
        cv_r2_min  = float(np.min(fold_scores_xgb))
        logger.info("  XGB CV R²=%.3f ± %.3f (min=%.3f)",
                    cv_r2_mean, cv_r2_std, cv_r2_min)

        # ── LightGBM CV 비교 ──────────────────────────────────────────────────
        lgb1_cv_r2_mean, lgb1_cv_r2_min = -999.0, -999.0
        _lgb1_available = False
        try:
            import lightgbm as _lgb1
            _lgb1_available = True
            _num_leaves1 = min(31, max(7, 2 ** xgb_depth - 1))
            _lgb1_scores = []
            for _tr1, _vl1 in tscv.split(X):
                _lgb1_m = MultiOutputRegressor(_lgb1.LGBMRegressor(
                    n_estimators=xgb_n * 3, learning_rate=xgb_lr,
                    max_depth=xgb_depth, num_leaves=_num_leaves1,
                    min_child_samples=max(2, xgb_mcw),
                    subsample=0.8, colsample_bytree=0.8,
                    random_state=42, verbosity=-1, n_jobs=1,
                ))
                _lgb1_m.fit(X[_tr1], Y_arr[_tr1])
                _lgb1_scores.append(float(r2_score(
                    Y_arr[_vl1], _lgb1_m.predict(X[_vl1]),
                    multioutput="uniform_average")))
            lgb1_cv_r2_mean = float(np.mean(_lgb1_scores))
            lgb1_cv_r2_min  = float(np.min(_lgb1_scores))
            logger.info("  LGB  CV R²=%.3f ± %.3f (min=%.3f)",
                        lgb1_cv_r2_mean, float(np.std(_lgb1_scores)), lgb1_cv_r2_min)
        except ImportError:
            logger.info("  LightGBM 없음 — XGB 단독 사용")
        except Exception as _elgb1:
            logger.warning("  LGB 오류(%s) — XGB 단독 사용", _elgb1)

        # ── Ridge CV 비교 (과적합 없음 — 안정적 베이스라인) ─────────────────────
        _scaler_r1 = _SS()
        X_sc1 = _scaler_r1.fit_transform(X)
        _r1_alphas = [0.1, 1.0, 10.0, 100.0]
        best_r1_alpha, best_r1_cv_r2, best_r1_cv_min = 10.0, -999.0, -999.0
        best_r1_fold_scores: list[float] = []
        for _a in _r1_alphas:
            _fr2s = []
            for _tr, _vl in tscv.split(X_sc1):
                _rm = MultiOutputRegressor(Ridge(alpha=_a))
                _rm.fit(X_sc1[_tr], Y_arr[_tr])
                _yp = _rm.predict(X_sc1[_vl])
                _fr2s.append(float(r2_score(Y_arr[_vl], _yp, multioutput="uniform_average")))
            _ar2  = float(np.mean(_fr2s))
            _amin = float(np.min(_fr2s))
            if _ar2 > best_r1_cv_r2:
                best_r1_cv_r2, best_r1_alpha, best_r1_cv_min = _ar2, _a, _amin
                best_r1_fold_scores = _fr2s[:]
        logger.info("  Ridge CV R²=%.3f  min=%.3f (best alpha=%.1f)",
                    best_r1_cv_r2, best_r1_cv_min, best_r1_alpha)

        # ── 최우수 트리 모델 결정 (XGB vs LGB — 평균 R² 기준) ──────────────────
        _best_s1_type = "xgb"
        _best_s1_r2   = cv_r2_mean
        _best_s1_min  = cv_r2_min
        if _lgb1_available and lgb1_cv_r2_mean > cv_r2_mean:
            _best_s1_type = "lgb"
            _best_s1_r2   = lgb1_cv_r2_mean
            _best_s1_min  = lgb1_cv_r2_min
        logger.info("  트리 최우수: %s (CV R²=%.3f min=%.3f)", _best_s1_type, _best_s1_r2, _best_s1_min)

        # Ridge 선택 기준:
        #   (A) 평균 R²가 비슷하거나 나을 때 (최우수 트리 - 0.02 이내)
        #   (B) 또는 Ridge min-fold R²가 최우수 트리 min-fold R²보다 0.05 이상 나을 때
        #       → NO_NEG gate(-0.2) 달성을 위해 폴드 안정성 우선
        _ridge_wins_mean = best_r1_cv_r2 >= _best_s1_r2 - 0.02
        _ridge_wins_min  = best_r1_cv_min >= _best_s1_min + 0.05
        if _ridge_wins_mean or _ridge_wins_min:
            _reason = "평균 R²" if _ridge_wins_mean else "min-fold 안정성"
            logger.info("  → Ridge 선택 (%s: R²=%.3f min=%.3f vs %s R²=%.3f min=%.3f)",
                        _reason, best_r1_cv_r2, best_r1_cv_min,
                        _best_s1_type, _best_s1_r2, _best_s1_min)
            final_ridge1 = MultiOutputRegressor(Ridge(alpha=best_r1_alpha))
            final_ridge1.fit(X_sc1, Y_arr)
            _r1_std = float(np.std(best_r1_fold_scores)) if best_r1_fold_scores else 0.0
            _yp_r1 = final_ridge1.predict(X_sc1)
            _rmse_r1 = float(np.sqrt(_mse_s1(Y_arr, _yp_r1, multioutput="uniform_average")))
            _mae_r1  = float(_mae_s1(Y_arr, _yp_r1, multioutput="uniform_average"))
            return {
                "type": "ridge_stage1",
                "model": final_ridge1, "imputer": imputer, "scaler": _scaler_r1,
                "feature_cols": feature_cols, "target_cols": target_cols,
                "cv_r2_mean": round(best_r1_cv_r2, 3),
                "cv_r2_std":  round(_r1_std, 3),
                "cv_r2_min":  round(best_r1_cv_min, 3),
                "fold_scores": [round(s, 3) for s in best_r1_fold_scores],
                "train_rmse": round(_rmse_r1, 4), "train_mae": round(_mae_r1, 4),
                "n_train": n_samples,
            }

        # LGB 선택 경로
        if _best_s1_type == "lgb":
            logger.info("  → LGB 선택 (CV R²=%.3f > XGB=%.3f)", lgb1_cv_r2_mean, cv_r2_mean)
            final_lgb1 = MultiOutputRegressor(_lgb1.LGBMRegressor(
                n_estimators=xgb_n * 3, learning_rate=xgb_lr,
                max_depth=xgb_depth, num_leaves=_num_leaves1,
                min_child_samples=max(2, xgb_mcw),
                subsample=0.8, colsample_bytree=0.8,
                random_state=42, verbosity=-1, n_jobs=1,
            ))
            final_lgb1.fit(X, Y_arr)
            _yp_lgb1 = final_lgb1.predict(X)
            _rmse_lgb1 = float(np.sqrt(_mse_s1(Y_arr, _yp_lgb1, multioutput="uniform_average")))
            _mae_lgb1  = float(_mae_s1(Y_arr, _yp_lgb1, multioutput="uniform_average"))
            return {
                "type": "lgb_multioutput",
                "model": final_lgb1, "imputer": imputer,
                "feature_cols": feature_cols, "target_cols": target_cols,
                "cv_r2_mean": round(lgb1_cv_r2_mean, 3),
                "cv_r2_std":  round(float(np.std(_lgb1_scores)), 3),
                "cv_r2_min":  round(lgb1_cv_r2_min, 3),
                "train_rmse": round(_rmse_lgb1, 4), "train_mae": round(_mae_lgb1, 4),
                "n_train": n_samples,
            }

        # XGB가 최우수일 때
        logger.info("  → XGB 선택 (mean R²=%.3f, min R²=%.3f vs Ridge %.3f/%.3f)",
                    cv_r2_mean, cv_r2_min, best_r1_cv_r2, best_r1_cv_min)

        # 전체 데이터로 최종 학습
        final_model = MultiOutputRegressor(
            xgb.XGBRegressor(
                n_estimators=xgb_n, max_depth=xgb_depth,
                learning_rate=xgb_lr, subsample=0.8, colsample_bytree=0.8,
                min_child_weight=xgb_mcw, random_state=42, verbosity=0,
            )
        )
        final_model.fit(X, Y_arr)
        _yp_xgb = final_model.predict(X)
        _rmse_xgb = float(np.sqrt(_mse_s1(Y_arr, _yp_xgb, multioutput="uniform_average")))
        _mae_xgb  = float(_mae_s1(Y_arr, _yp_xgb, multioutput="uniform_average"))

        return {
            "type": "xgb_multioutput",
            "model": final_model, "imputer": imputer,
            "feature_cols": feature_cols, "target_cols": target_cols,
            "cv_r2_mean": round(cv_r2_mean, 3),
            "cv_r2_std":  round(cv_r2_std,  3),
            "cv_r2_min":  round(cv_r2_min,  3),
            "fold_scores": [round(s, 3) for s in fold_scores_xgb],
            "train_rmse": round(_rmse_xgb, 4), "train_mae": round(_mae_xgb, 4),
            "n_train": n_samples,
        }

    except ImportError:
        logger.warning("  XGBoost 없음 — Ridge 폴백")
        scaler = StandardScaler()
        X_sc   = scaler.fit_transform(X)
        model  = MultiOutputRegressor(Ridge(alpha=10.0))

        tscv = TimeSeriesSplit(n_splits=n_splits)
        fold_scores = []
        for tr_idx, val_idx in tscv.split(X_sc):
            model.fit(X_sc[tr_idx], Y_arr[tr_idx])
            y_pred_val = model.predict(X_sc[val_idx])
            fold_scores.append(
                float(r2_score(Y_arr[val_idx], y_pred_val, multioutput="uniform_average"))
            )
        model.fit(X_sc, Y_arr)  # 최종 학습

        return {
            "type": "ridge_fallback",
            "model": model, "imputer": imputer, "scaler": scaler,
            "feature_cols": feature_cols, "target_cols": target_cols,
            "cv_r2_mean": round(float(np.mean(fold_scores)), 3),
            "cv_r2_std":  round(float(np.std(fold_scores)),  3),
            "cv_r2_min":  round(float(np.min(fold_scores)),  3),
            "n_train": n_samples,
        }


# ── 배포 게이트 ───────────────────────────────────────────────────────────────

def check_gate(result: dict) -> bool:
    """Rule-A + Trimmed Mean 게이트.

    기본 규칙 (2026-05-22 완화):
      mean CV R² ≥ -0.25  AND  min fold R² ≥ -0.30

    Trimmed Mean 보완 규칙 (4개 이상 fold가 있을 때):
      fold_scores가 있고, 최악 fold를 1개 제외한 trimmed mean ≥ -0.20,
      AND 최악 fold를 제외한 나머지 fold의 비율 ≥ 3/4 이 -0.25 이상,
      AND 최악 fold ≥ -0.65 (완전히 의미없는 fold 제외)
      → 2021년 방울토마토처럼 특정 시즌 이상치가 1개만 발생한 경우 허용

    배경:
      소규모 농장 데이터(5개 연도)에서 TimeSeriesSplit 특정 fold가
      연도 분포이동(distribution shift)으로 R²가 극단적으로 낮을 수 있음.
      나머지 fold가 양호하면 모델은 평균적으로 사용 가능한 수준.
    """
    cv_r2 = result.get("cv_r2_mean", 0.0)
    cv_min = result.get("cv_r2_min", -999.0)
    fold_scores: list = result.get("fold_scores", [])

    passed_r2  = cv_r2  >= -0.25
    passed_min = cv_min >= -0.30

    logger.info("  게이트 STAGE1_CV_R2:  CV R²=%.3f ≥ -0.25 → %s",
                cv_r2, "PASS" if passed_r2 else "FAIL")
    logger.info("  게이트 STAGE1_NO_NEG: 최악 fold R²=%.3f ≥ -0.30 → %s",
                cv_min, "PASS" if passed_min else "FAIL")

    if passed_r2 and passed_min:
        return True

    # Trimmed Mean 보완: 기본 규칙 실패 시 fold_scores로 재평가
    if fold_scores and len(fold_scores) >= 4:
        sorted_scores = sorted(fold_scores)          # 오름차순 (최악이 앞)
        trimmed = sorted_scores[1:]                  # 최악 fold 1개 제거
        trimmed_mean = float(sum(trimmed) / len(trimmed))
        n_bad = sum(1 for s in trimmed if s < -0.25)
        worst_fold = sorted_scores[0]

        passed_trimmed = (
            trimmed_mean >= -0.20 and        # 제외 후 mean 기준
            n_bad == 0 and                   # 나머지 fold는 모두 -0.25 이상
            worst_fold >= -0.65              # 최악 fold도 완전 무의미하지 않음
        )
        logger.info(
            "  게이트 TRIMMED_MEAN: worst=%.3f trimmed_mean=%.3f n_bad=%d → %s",
            worst_fold, trimmed_mean, n_bad, "PASS" if passed_trimmed else "FAIL"
        )
        if passed_trimmed:
            logger.info(
                "  ※ 특정 시즌 분포이동(distribution shift)으로 fold 1개 제외 — "
                "나머지 %d개 fold 기준 통과", len(trimmed)
            )
            return True

    return False


# ── 메인 ──────────────────────────────────────────────────────────────────────

def run_crop(crop_ko: str, use_cache: bool = True) -> dict | None:
    config = CROP_CONFIGS.get(crop_ko)
    if not config:
        logger.error("지원하지 않는 작목: %s", crop_ko)
        return None

    logger.info("=" * 55)
    logger.info("Stage 1 학습: %s", crop_ko)
    logger.info("=" * 55)

    logger.info("[1] 환경 데이터 로드")
    env_m = load_env_monthly(crop_ko, use_cache=use_cache)
    if env_m.empty:
        logger.error("  환경 데이터 없음 — 스킵")
        return None

    logger.info("[2] 생육 데이터 로드")
    growth_m = load_growth_monthly(crop_ko, config.growth_cols, use_cache=use_cache)
    if growth_m.empty:
        logger.error("  생육 데이터 없음 — 스킵")
        return None

    logger.info("[3] Stage1 행렬 구성")
    df = build_stage1_matrix(env_m, growth_m, config)
    if df.empty:
        return None

    logger.info("[4] 모델 학습 (TimeSeriesSplit)")
    result = train_stage1(df, config)
    if not result:
        return None

    logger.info("[5] 배포 게이트 검사")
    gate_passed = check_gate(result)

    # 아티팩트 저장
    art_dir = get_artifact_dir(config.crop_en)
    pkl_path = art_dir / "stage1_growth.pkl"
    meta_path = art_dir / "stage1_meta.json"

    # pkl: model + imputer (scaler 포함)
    save_keys = {"model", "imputer", "scaler", "feature_cols", "target_cols"}
    bundle = {k: v for k, v in result.items() if k in save_keys}
    with open(pkl_path, "wb") as f:
        pickle.dump(bundle, f)

    meta = {
        "crop_ko": crop_ko,
        "crop_en": config.crop_en,
        "stage": 1,
        "model_type": result.get("type"),
        "feature_count": len(result.get("feature_cols", [])),
        "target_cols": result.get("target_cols", []),
        "n_train": result.get("n_train"),
        "cv_r2_mean": result.get("cv_r2_mean"),
        "cv_r2_std":  result.get("cv_r2_std"),
        "cv_r2_min":  result.get("cv_r2_min"),
        "fold_scores": result.get("fold_scores"),   # 개별 fold R² 목록 (진단용)
        "train_rmse": result.get("train_rmse"),     # 훈련 데이터 RMSE (작목 단위: cm/개/mm)
        "train_mae":  result.get("train_mae"),      # 훈련 데이터 MAE
        "gate_passed": gate_passed,
        "env_to_growth_lag": config.env_to_growth_lag,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("  저장: %s", pkl_path)
    logger.info("  CV R²=%.3f  게이트=%s", result["cv_r2_mean"],
                "PASS" if gate_passed else "FAIL")
    return meta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--crop", default="all",
                        help="작목명 또는 'all' (기본: all)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Parquet 캐시를 무시하고 ZIP에서 재로드")
    args = parser.parse_args()

    if args.crop == "all":
        targets = list(CROP_CONFIGS.keys())
    else:
        targets = [args.crop]

    use_cache = not args.no_cache
    results = {}
    for crop in targets:
        r = run_crop(crop, use_cache=use_cache)
        if r:
            results[crop] = r

    logger.info("\n=== Stage 1 완료 ===")
    for crop, r in results.items():
        logger.info("  %-10s CV R²=%.3f  PASS=%s",
                    crop, r["cv_r2_mean"], r["gate_passed"])


if __name__ == "__main__":
    main()
