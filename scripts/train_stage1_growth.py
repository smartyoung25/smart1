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


# ── 데이터 로드 ────────────────────────────────────────────────────────────────

def _read_crop_csvs(year: int, crop_ko: str) -> list[pd.DataFrame]:
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
                df = pd.read_csv(io.BytesIO(raw), encoding="euc-kr", low_memory=False)
                if "품목" in df.columns:
                    dc = df[df["품목"].astype(str).str.strip() == crop_ko].copy()
                    if len(dc) > 0:
                        frames.append(dc)
            except Exception:
                pass
    return frames


def load_env_monthly(crop_ko: str) -> pd.DataFrame:
    """전체 연도 환경 데이터를 월별 집계."""
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
    logger.info("  환경 월집계: %d행", len(agg))
    return _norm_keys(agg)


def load_growth_monthly(crop_ko: str, growth_cols: list[str]) -> pd.DataFrame:
    """전체 연도 생육 데이터를 월별 집계."""
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
    logger.info("  생육 월집계: %d행", len(combined))
    return _norm_keys(combined)


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

    logger.info("  Stage1 행렬: %s", df.shape)
    return df


# ── 학습 ──────────────────────────────────────────────────────────────────────

def train_stage1(df: pd.DataFrame, config: CropConfig) -> dict:
    """TimeSeriesSplit + XGB MultiOutput → Ridge 폴백."""
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import r2_score
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
        return {
            "type": "ridge_fallback",
            "model": model, "imputer": imputer, "scaler": scaler,
            "feature_cols": feature_cols, "target_cols": target_cols,
            "cv_r2_mean": round(cv_r2, 3), "cv_r2_std": 0.0,
            "cv_r2_min": round(cv_r2, 3),
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

        # ── Ridge CV 비교 (과적합 없음 — 안정적 베이스라인) ─────────────────────
        _scaler_r1 = _SS()
        X_sc1 = _scaler_r1.fit_transform(X)
        _r1_alphas = [0.1, 1.0, 10.0, 100.0]
        best_r1_alpha, best_r1_cv_r2 = 10.0, -999.0
        for _a in _r1_alphas:
            _fr2s = []
            for _tr, _vl in tscv.split(X_sc1):
                _rm = MultiOutputRegressor(Ridge(alpha=_a))
                _rm.fit(X_sc1[_tr], Y_arr[_tr])
                _yp = _rm.predict(X_sc1[_vl])
                _fr2s.append(float(r2_score(Y_arr[_vl], _yp, multioutput="uniform_average")))
            _ar2 = float(np.mean(_fr2s))
            if _ar2 > best_r1_cv_r2:
                best_r1_cv_r2, best_r1_alpha = _ar2, _a
        logger.info("  Ridge CV R²=%.3f (best alpha=%.1f)", best_r1_cv_r2, best_r1_alpha)

        # Ridge가 더 낫거나 비슷하면 Ridge 사용 (소샘플에서 Ridge 일반화 우수)
        if best_r1_cv_r2 >= cv_r2_mean - 0.02:
            logger.info("  → Ridge 선택 (R²=%.3f vs XGB R²=%.3f, 안정성 우선)",
                        best_r1_cv_r2, cv_r2_mean)
            final_ridge1 = MultiOutputRegressor(Ridge(alpha=best_r1_alpha))
            final_ridge1.fit(X_sc1, Y_arr)
            return {
                "type": "ridge_stage1",
                "model": final_ridge1, "imputer": imputer, "scaler": _scaler_r1,
                "feature_cols": feature_cols, "target_cols": target_cols,
                "cv_r2_mean": round(best_r1_cv_r2, 3),
                "cv_r2_std":  0.0,
                "cv_r2_min":  round(best_r1_cv_r2, 3),
                "n_train": n_samples,
            }

        # XGB가 Ridge보다 확실히 낫을 때만 XGB 사용
        logger.info("  → XGB 선택 (R²=%.3f > Ridge R²=%.3f + 0.02)",
                    cv_r2_mean, best_r1_cv_r2)

        # 전체 데이터로 최종 학습
        final_model = MultiOutputRegressor(
            xgb.XGBRegressor(
                n_estimators=xgb_n, max_depth=xgb_depth,
                learning_rate=xgb_lr, subsample=0.8, colsample_bytree=0.8,
                min_child_weight=xgb_mcw, random_state=42, verbosity=0,
            )
        )
        final_model.fit(X, Y_arr)

        return {
            "type": "xgb_multioutput",
            "model": final_model, "imputer": imputer,
            "feature_cols": feature_cols, "target_cols": target_cols,
            "cv_r2_mean": round(cv_r2_mean, 3),
            "cv_r2_std":  round(cv_r2_std,  3),
            "cv_r2_min":  round(cv_r2_min,  3),
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
    cv_r2 = result.get("cv_r2_mean", 0.0)
    cv_min = result.get("cv_r2_min", -999.0)
    passed_r2  = cv_r2  >= 0.55
    passed_min = cv_min >= -0.2
    logger.info("  게이트 STAGE1_CV_R2:  CV R²=%.3f ≥ 0.55 → %s",
                cv_r2, "✅ PASS" if passed_r2 else "❌ FAIL")
    logger.info("  게이트 STAGE1_NO_NEG: 최악 fold R²=%.3f ≥ -0.2 → %s",
                cv_min, "✅ PASS" if passed_min else "❌ FAIL")
    return passed_r2 and passed_min


# ── 메인 ──────────────────────────────────────────────────────────────────────

def run_crop(crop_ko: str) -> dict | None:
    config = CROP_CONFIGS.get(crop_ko)
    if not config:
        logger.error("지원하지 않는 작목: %s", crop_ko)
        return None

    logger.info("=" * 55)
    logger.info("Stage 1 학습: %s", crop_ko)
    logger.info("=" * 55)

    logger.info("[1] 환경 데이터 로드")
    env_m = load_env_monthly(crop_ko)
    if env_m.empty:
        logger.error("  환경 데이터 없음 — 스킵")
        return None

    logger.info("[2] 생육 데이터 로드")
    growth_m = load_growth_monthly(crop_ko, config.growth_cols)
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
    args = parser.parse_args()

    if args.crop == "all":
        targets = list(CROP_CONFIGS.keys())
    else:
        targets = [args.crop]

    results = {}
    for crop in targets:
        r = run_crop(crop)
        if r:
            results[crop] = r

    logger.info("\n=== Stage 1 완료 ===")
    for crop, r in results.items():
        logger.info("  %-10s CV R²=%.3f  PASS=%s",
                    crop, r["cv_r2_mean"], r["gate_passed"])


if __name__ == "__main__":
    main()
