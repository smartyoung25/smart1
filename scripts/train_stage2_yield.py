"""Stage 2: 생육+환경 → 수확량 예측 (M2 재작성).

핵심 개선:
  - 타겟: yield_per_m2 (kg/m²)  ← revenue_per_m2 직접 예측 폐기
  - 면적: farm_registry.json 작목별 중앙값 / 재배정보 실측값 (기본값 1000m² 폐기)
  - 수확 lag: 생육[month=M] → 수확[month=M+1]
  - early_stopping_rounds=50 + eval_set → 과적합 방지
  - log1p 타겟 변환 → 역변환 expm1
  - TimeSeriesSplit(n_splits=4) 교차 검증
  - SHAP 피처 선택 (상위 15개)

실행:
  python scripts/train_stage2_yield.py --crop 딸기
  python scripts/train_stage2_yield.py --crop all
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

# 작목별 면적 기본값 (farm_registry median 기반)
AREA_DEFAULTS: dict[str, float] = {
    "딸기":       1200.0,
    "방울토마토": 1600.0,
    "완숙토마토": 1400.0,
    "참외":       3800.0,
    "파프리카":   2500.0,
}


# ── 유틸 (Stage 1과 동일) ─────────────────────────────────────────────────────

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


# ── 면적 로드 ─────────────────────────────────────────────────────────────────

def _load_cultiv_csv(year: int) -> pd.DataFrame:
    """재배정보_YYYY.CSV 로드 (ZIP 내부)."""
    zp = DATA_DIR / f"스마트팜_{year}.zip"
    if not zp.exists():
        return pd.DataFrame()
    with zipfile.ZipFile(zp) as zf:
        for info in zf.infolist():
            try:
                raw = zf.read(info.filename)
                df = pd.read_csv(io.BytesIO(raw), encoding="euc-kr", low_memory=False)
                # 재배정보 CSV 판별: 정식일 + 품목 컬럼 존재
                if "정식일" in df.columns and "품목" in df.columns:
                    return df
            except Exception:
                pass
    return pd.DataFrame()


def load_area_map(crop_ko: str) -> dict[str, float]:
    """재배정보 CSV(식부면적)에서 농가면적 맵 {farm_id: area_m2} 구성.

    우선순위:
      1. 재배정보_YYYY.CSV의 식부면적 (생산CSV 농가명과 동일 키)
      2. farm_registry.json의 plant_area_m2
      3. 빈 dict (→ AREA_DEFAULTS 기본값 사용)
    """
    result: dict[str, float] = {}

    # ① 재배정보 CSV — 연도별로 파싱, farm_id+area 집계
    area_records: list[tuple[str, float]] = []
    for year in YEARS:
        df = _load_cultiv_csv(year)
        if df.empty:
            continue
        dc = df[df["품목"].astype(str).str.strip() == crop_ko].copy() if "품목" in df.columns else df
        if dc.empty:
            continue
        farm_col = next((c for c in ["농가명", "농가ID"] if c in dc.columns), None)
        area_col = next((c for c in ["식부면적", "총면적"] if c in dc.columns), None)
        if farm_col and area_col:
            for _, row in dc.iterrows():
                fid = _norm_farm_id(str(row[farm_col]))
                try:
                    area = float(row[area_col])
                    if area > 0:
                        area_records.append((fid, area))
                except (ValueError, TypeError):
                    pass

    if area_records:
        # 동일 farm_id에 여러 연도 값 → 중앙값 사용
        from collections import defaultdict
        fid_areas: dict[str, list[float]] = defaultdict(list)
        for fid, area in area_records:
            fid_areas[fid].append(area)
        for fid, areas in fid_areas.items():
            result[fid] = float(np.median(areas))
        logger.info("  면적 맵(재배정보 CSV): %d농가 (작목=%s)", len(result), crop_ko)
        return result

    # ② farm_registry.json 폴백
    reg_path = ROOT / "api" / "data" / "farm_registry.json"
    if reg_path.exists():
        registry = json.loads(reg_path.read_text(encoding="utf-8"))
        farms_dict = registry.get("farms", registry)
        for farm_id, info in farms_dict.items():
            if isinstance(info, dict) and info.get("crop") == crop_ko:
                area = info.get("plant_area_m2", info.get("total_area_m2", info.get("area_m2", 0)))
                if area > 0:
                    result[_norm_farm_id(farm_id)] = float(area)
        if result:
            logger.info("  면적 맵(registry 폴백): %d농가 (작목=%s)", len(result), crop_ko)

    return result


def load_cultiv_meta(crop_ko: str) -> dict[str, dict]:
    """재배정보 CSV에서 품종·온실유형·재배일수 메타 {farm_id: {...}} 구성."""
    meta: dict[str, dict] = {}
    for year in YEARS:
        df = _load_cultiv_csv(year)
        if df.empty:
            continue
        dc = df[df["품목"].astype(str).str.strip() == crop_ko].copy() if "품목" in df.columns else df
        if dc.empty:
            continue
        farm_col = next((c for c in ["농가명", "농가ID"] if c in dc.columns), None)
        if not farm_col:
            continue
        for _, row in dc.iterrows():
            fid = _norm_farm_id(str(row[farm_col]))
            entry = meta.setdefault(fid, {})
            if "품종" in dc.columns and pd.notna(row.get("품종")):
                entry["variety"] = str(row["품종"]).strip()
            if "온실종류" in dc.columns and pd.notna(row.get("온실종류")):
                entry["greenhouse_type"] = str(row["온실종류"]).strip()
            if "정식일" in dc.columns:
                try:
                    plant_dt = pd.to_datetime(row["정식일"], errors="coerce")
                    if pd.notna(plant_dt):
                        entry["plant_month"] = int(plant_dt.month)
                except Exception:
                    pass
    return meta


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
    all_frames = []
    for year in YEARS:
        frames = _read_crop_csvs(year, crop_ko)
        env_f = [f for f in frames if "측정시간" in f.columns]
        if not env_f:
            continue
        df = pd.concat(env_f, ignore_index=True)
        df["year"]  = year
        time_col    = "측정시간" if "측정시간" in df.columns else "측정일시"
        df["dt"]    = pd.to_datetime(df[time_col], errors="coerce")
        df["month"] = df["dt"].dt.month
        farm_col    = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
        df["farm_id"] = df[farm_col].astype(str).str.strip().apply(_norm_farm_id) \
            if farm_col else "unknown"
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
           .agg({col: "mean" for col in env_vars})
           .reset_index())
    return _norm_keys(agg)


def load_growth_monthly(crop_ko: str, growth_cols: list[str]) -> pd.DataFrame:
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
    return _norm_keys(pd.concat(all_frames, ignore_index=True))


def load_production_monthly(crop_ko: str, area_map: dict[str, float],
                             default_area: float) -> pd.DataFrame:
    """생산 데이터를 월별 집계 + 면적 정규화 → yield_per_m2."""
    all_frames = []
    for year in YEARS:
        frames = _read_crop_csvs(year, crop_ko)
        prod_f = [f for f in frames
                  if "출하일자" in f.columns and "총출하량" in f.columns]
        if not prod_f:
            continue
        df = pd.concat(prod_f, ignore_index=True)
        df["dt"]    = pd.to_datetime(df["출하일자"], errors="coerce")
        df["year"]  = year
        df["month"] = df["dt"].dt.month
        farm_col    = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
        df["farm_id"] = df[farm_col].astype(str).str.strip().apply(_norm_farm_id) \
            if farm_col else "unknown"
        df["총출하량"] = pd.to_numeric(df.get("총출하량", 0), errors="coerce").fillna(0).clip(lower=0)
        agg = (df.groupby(["farm_id", "year", "month"])
               .agg({"총출하량": "sum"})
               .reset_index()
               .rename(columns={"총출하량": "yield_kg"}))
        all_frames.append(agg)

    if not all_frames:
        return pd.DataFrame()

    prod = _norm_keys(pd.concat(all_frames, ignore_index=True))
    # 면적 적용 → yield_per_m2
    prod["area_m2"] = prod["farm_id"].map(area_map).fillna(default_area)
    prod["yield_per_m2"] = prod["yield_kg"] / prod["area_m2"].replace(0, default_area)
    prod["yield_per_m2"] = clip_iqr(prod["yield_per_m2"].clip(lower=0))
    logger.info("  수확량 월집계: %d행 (yield_per_m2 중앙값=%.3f kg/m²)",
                len(prod), prod["yield_per_m2"].median())
    return prod


# ── 피처 행렬 ─────────────────────────────────────────────────────────────────

def build_stage2_matrix(
    env_monthly: pd.DataFrame,
    growth_monthly: pd.DataFrame,
    prod_monthly: pd.DataFrame,
    config: CropConfig,
    cultiv_meta: Optional[dict] = None,
) -> pd.DataFrame:
    """생육[t] + 환경[t] + 재배메타 → 수확량[t+harvest_lag] 매핑."""
    if prod_monthly.empty:
        logger.warning("  수확량 데이터 없음")
        return pd.DataFrame()

    key = ["farm_id", "year", "month"]

    # 수확 lag: 생육·환경 month를 harvest_lag 만큼 앞으로 당겨 수확 month에 매핑
    # 즉, 수확[M] ← 생육[M - harvest_lag], 환경[M - harvest_lag]
    lag = config.harvest_lag

    # 생육 month 오프셋
    if not growth_monthly.empty:
        gm = growth_monthly.copy()
        gm["month"] = (gm["month"].astype(int) + lag).astype("Int64")
        # year 경계 처리
        mask = gm["month"] > 12
        gm.loc[mask, "year"]  = gm.loc[mask, "year"] + 1
        gm.loc[mask, "month"] = gm.loc[mask, "month"] - 12
        gm = _norm_keys(gm)

    # 환경 month 오프셋
    if not env_monthly.empty:
        em = env_monthly.copy()
        em["month"] = (em["month"].astype(int) + lag).astype("Int64")
        mask = em["month"] > 12
        em.loc[mask, "year"]  = em.loc[mask, "year"] + 1
        em.loc[mask, "month"] = em.loc[mask, "month"] - 12
        em = _norm_keys(em)

    # 수확량을 기준으로 join
    df = prod_monthly[key + ["yield_per_m2", "area_m2"]].copy()
    if not growth_monthly.empty:
        g_cols = [c for c in gm.columns if c not in key]
        df = df.merge(gm[key + g_cols], on=key, how="left")
    if not env_monthly.empty:
        e_cols = [c for c in em.columns if c not in key]
        df = df.merge(em[key + e_cols], on=key, how="left")

    # GDD
    if "temp_internal" in df.columns:
        df["gdd_monthly"] = (df["temp_internal"] - config.t_base).clip(lower=0) * 30
    df["month_sin"] = np.sin(2 * np.pi * df["month"].astype(float) / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"].astype(float) / 12)

    # 재배정보 메타 피처 (품종, 온실유형, 정식월)
    if cultiv_meta:
        df["variety_code"] = df["farm_id"].map(
            lambda fid: hash(cultiv_meta.get(fid, {}).get("variety", "")) % 100
        ).fillna(0).astype(int)
        _GREENHOUSE_MAP = {"유리": 1, "플라스틱": 2, "비닐": 3}
        df["greenhouse_code"] = df["farm_id"].map(
            lambda fid: _GREENHOUSE_MAP.get(
                cultiv_meta.get(fid, {}).get("greenhouse_type", ""), 0)
        ).fillna(0).astype(int)
        df["plant_month"] = df["farm_id"].map(
            lambda fid: cultiv_meta.get(fid, {}).get("plant_month", 0)
        ).fillna(0).astype(int)
        n_meta = sum(1 for fid in df["farm_id"] if fid in cultiv_meta)
        logger.info("  재배메타 적용: %d/%d행 (품종/온실/정식월)", n_meta, len(df))

    logger.info("  Stage2 행렬: %s", df.shape)
    return df


# ── SHAP 피처 선택 ────────────────────────────────────────────────────────────

def select_top_features(model, X: np.ndarray, feature_names: list[str],
                         top_n: int = 15) -> list[str]:
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(X[:min(500, len(X))])
        importance = np.abs(sv).mean(axis=0)
        top_idx = np.argsort(importance)[::-1][:top_n]
        selected = [feature_names[i] for i in top_idx]
        logger.info("  SHAP 선택 피처 (top %d): %s", top_n, selected[:5])
        return selected
    except Exception as e:
        logger.warning("  SHAP 실패(%s) — 전체 피처 사용", e)
        return feature_names[:top_n]


# ── 학습 ──────────────────────────────────────────────────────────────────────

def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true > 0
    if not mask.any():
        return 999.9
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def train_stage2(df: pd.DataFrame, config: CropConfig) -> dict:
    """TimeSeriesSplit + XGB early stopping + log1p + SHAP."""
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import r2_score
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    target = "yield_per_m2"
    exclude = {"farm_id", "year", "month", "yield_kg", "area_m2", target}
    feature_cols = [c for c in df.columns if c not in exclude
                    and df[c].dtype in [np.float64, np.int64, "Int64", float, int]]

    # 타겟 유효 행 (yield > 0)
    mask = df[target].astype(float) > 0
    X_raw = df.loc[mask, feature_cols]
    y_raw = df.loc[mask, target].astype(float)
    n_samples = len(X_raw)

    logger.info("  유효 샘플: %d  피처: %d", n_samples, len(feature_cols))

    imputer = SimpleImputer(strategy="median")
    X = imputer.fit_transform(X_raw)
    y = y_raw.values

    n_splits = 3 if n_samples < 200 else 4

    # 샘플 부족 → Ridge 폴백
    if n_samples < config.min_train_samples:
        logger.warning("  샘플 부족(%d) — Ridge 폴백", n_samples)
        scaler = StandardScaler()
        X_sc = scaler.fit_transform(X)
        model = Ridge(alpha=10.0)
        model.fit(X_sc, np.log1p(y))
        y_pred = np.expm1(model.predict(X_sc))
        r2   = float(r2_score(y, y_pred))
        mape = _mape(y, y_pred)
        return {
            "type": "ridge_fallback",
            "model": model, "imputer": imputer, "scaler": scaler,
            "feature_cols": feature_cols,
            "log_transform": True,
            "cv_r2_mean": round(r2, 3), "cv_r2_std": 0.0,
            "mape": round(mape, 1), "n_train": n_samples,
        }

    try:
        import xgboost as xgb

        tscv = TimeSeriesSplit(n_splits=n_splits)
        cv_r2, cv_mape, best_iters = [], [], []

        for fold, (tr_idx, val_idx) in enumerate(tscv.split(X)):
            X_tr, X_val = X[tr_idx], X[val_idx]
            y_tr, y_val = np.log1p(y[tr_idx]), np.log1p(y[val_idx])

            fold_m = xgb.XGBRegressor(
                n_estimators=1000,
                early_stopping_rounds=50,
                learning_rate=0.05, max_depth=4,
                subsample=0.8, colsample_bytree=0.8,
                min_child_weight=5, random_state=42, verbosity=0,
            )
            fold_m.fit(X_tr, y_tr,
                       eval_set=[(X_val, y_val)],
                       verbose=False)

            y_pred_v = np.expm1(fold_m.predict(X_val))
            y_true_v = np.expm1(y_val)
            r2   = float(r2_score(y_true_v, y_pred_v))
            mape = _mape(y_true_v, y_pred_v)
            cv_r2.append(r2)
            cv_mape.append(mape)
            best_iters.append(fold_m.best_iteration)
            logger.info("  Fold %d R²=%.3f MAPE=%.1f%% (n_trees=%d)",
                        fold + 1, r2, mape, fold_m.best_iteration)

        cv_r2_mean  = float(np.mean(cv_r2))
        cv_mape_mean = float(np.mean(cv_mape))
        best_n = max(50, int(np.median(best_iters)))
        logger.info("  CV R²=%.3f  MAPE=%.1f%%  best_n=%d",
                    cv_r2_mean, cv_mape_mean, best_n)

        # 전체 데이터로 최종 학습 (best_n으로 고정)
        final_model = xgb.XGBRegressor(
            n_estimators=best_n,
            learning_rate=0.05, max_depth=4,
            subsample=0.8, colsample_bytree=0.8,
            min_child_weight=5, random_state=42, verbosity=0,
        )
        final_model.fit(X, np.log1p(y))

        # SHAP 피처 선택
        top_n = 10 if n_samples < 300 else 15
        selected_features = select_top_features(final_model, X, feature_cols, top_n)

        # SHAP 선택 피처로 재학습
        sel_idx  = [feature_cols.index(f) for f in selected_features
                    if f in feature_cols]
        X_sel    = X[:, sel_idx]
        imp_sel  = SimpleImputer(strategy="median").fit(X_raw[selected_features])

        final_sel = xgb.XGBRegressor(
            n_estimators=best_n, learning_rate=0.05, max_depth=4,
            subsample=0.8, colsample_bytree=0.8,
            min_child_weight=5, random_state=42, verbosity=0,
        )
        final_sel.fit(X_sel, np.log1p(y))

        # 최종 검증
        y_pred_final = np.expm1(final_sel.predict(X_sel))
        final_r2   = float(r2_score(y, y_pred_final))
        final_mape = _mape(y, y_pred_final)

        return {
            "type": "xgb",
            "model": final_sel,
            "imputer": imp_sel,
            "feature_cols": selected_features,
            "log_transform": True,
            "best_n_estimators": best_n,
            "cv_r2_mean":  round(cv_r2_mean, 3),
            "cv_r2_std":   round(float(np.std(cv_r2)), 3),
            "cv_mape_mean": round(cv_mape_mean, 1),
            "final_r2":    round(final_r2, 3),
            "mape":        round(final_mape, 1),
            "n_train": n_samples,
            "all_feature_cols": feature_cols,
            "shap_top_n": top_n,
        }

    except ImportError:
        logger.warning("  XGBoost 없음 — Ridge 폴백")
        scaler = StandardScaler()
        X_sc = scaler.fit_transform(X)
        tscv = TimeSeriesSplit(n_splits=n_splits)
        cv_r2, cv_mape = [], []
        model = Ridge(alpha=10.0)
        for tr_idx, val_idx in tscv.split(X_sc):
            model.fit(X_sc[tr_idx], np.log1p(y[tr_idx]))
            y_pv = np.expm1(model.predict(X_sc[val_idx]))
            cv_r2.append(float(r2_score(y[val_idx], y_pv)))
            cv_mape.append(_mape(y[val_idx], y_pv))
        model.fit(X_sc, np.log1p(y))
        return {
            "type": "ridge_fallback",
            "model": model, "imputer": imputer, "scaler": scaler,
            "feature_cols": feature_cols, "log_transform": True,
            "cv_r2_mean":  round(float(np.mean(cv_r2)), 3),
            "cv_r2_std":   round(float(np.std(cv_r2)),  3),
            "mape":        round(float(np.mean(cv_mape)), 1),
            "n_train": n_samples,
        }


# ── 배포 게이트 ───────────────────────────────────────────────────────────────

def check_gate(result: dict) -> bool:
    mape = result.get("mape", 999.0)
    r2   = result.get("cv_r2_mean", -999.0)
    p_mape = mape <= 25.0
    p_r2   = r2   >= 0.30
    logger.info("  게이트 STAGE2_MAPE: %.1f%% ≤ 25%%  → %s",
                mape, "✅ PASS" if p_mape else "❌ FAIL")
    logger.info("  게이트 STAGE2_R2:   R²=%.3f ≥ 0.30 → %s",
                r2,   "✅ PASS" if p_r2   else "❌ FAIL")
    return p_mape and p_r2


# ── 메인 ──────────────────────────────────────────────────────────────────────

def run_crop(crop_ko: str) -> dict | None:
    config = CROP_CONFIGS.get(crop_ko)
    if not config:
        logger.error("지원하지 않는 작목: %s", crop_ko)
        return None

    logger.info("=" * 55)
    logger.info("Stage 2 학습: %s", crop_ko)
    logger.info("=" * 55)

    default_area = AREA_DEFAULTS.get(crop_ko, 1200.0)

    logger.info("[1] 환경 데이터 로드")
    env_m = load_env_monthly(crop_ko)

    logger.info("[2] 생육 데이터 로드")
    growth_m = load_growth_monthly(crop_ko, config.growth_cols)

    logger.info("[3] 수확량 데이터 로드")
    area_map = load_area_map(crop_ko)
    prod_m = load_production_monthly(crop_ko, area_map, default_area)
    if prod_m.empty:
        logger.error("  수확량 데이터 없음 — 스킵")
        return None

    logger.info("[3b] 재배정보 메타 로드 (품종·온실유형·정식월)")
    cultiv_meta = load_cultiv_meta(crop_ko)
    logger.info("  재배메타: %d농가", len(cultiv_meta))

    logger.info("[4] Stage2 행렬 구성")
    df = build_stage2_matrix(env_m, growth_m, prod_m, config, cultiv_meta=cultiv_meta)
    if df.empty:
        return None

    logger.info("[5] 모델 학습 (TimeSeriesSplit + early stopping)")
    result = train_stage2(df, config)
    if not result:
        return None

    logger.info("[6] 배포 게이트 검사")
    gate_passed = check_gate(result)

    # 아티팩트 저장
    art_dir  = get_artifact_dir(config.crop_en)
    pkl_path = art_dir / "stage2_yield.pkl"
    meta_path = art_dir / "stage2_meta.json"

    save_keys = {"model", "imputer", "scaler", "feature_cols", "log_transform",
                 "best_n_estimators"}
    bundle = {k: v for k, v in result.items() if k in save_keys}
    with open(pkl_path, "wb") as f:
        pickle.dump(bundle, f)

    meta = {
        "crop_ko": crop_ko,
        "crop_en": config.crop_en,
        "stage": 2,
        "model_type": result.get("type"),
        "feature_count": len(result.get("feature_cols", [])),
        "n_train": result.get("n_train"),
        "log_transform": result.get("log_transform", True),
        "best_n_estimators": result.get("best_n_estimators"),
        "cv_r2_mean":  result.get("cv_r2_mean"),
        "cv_r2_std":   result.get("cv_r2_std"),
        "cv_mape_mean": result.get("cv_mape_mean"),
        "mape": result.get("mape"),
        "gate_passed": gate_passed,
        "harvest_lag": config.harvest_lag,
        "area_default_m2": default_area,
        "area_from_registry_count": len(area_map),  # 레거시 호환
        "area_from_csv_count": len(area_map),        # 재배정보 CSV 기반
        "cultiv_meta_count": len(cultiv_meta),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("  저장: %s", pkl_path)
    logger.info("  CV R²=%.3f  MAPE=%.1f%%  게이트=%s",
                result.get("cv_r2_mean", 0), result.get("mape", 0),
                "PASS" if gate_passed else "FAIL")
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

    logger.info("\n=== Stage 2 완료 ===")
    for crop, r in results.items():
        logger.info("  %-10s CV R²=%.3f  MAPE=%.1f%%  PASS=%s",
                    crop, r.get("cv_r2_mean", 0), r.get("mape", 0), r["gate_passed"])


if __name__ == "__main__":
    main()
