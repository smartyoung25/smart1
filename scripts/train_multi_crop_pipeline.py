"""다작목 소득최적화 파이프라인 (방울토마토·완숙토마토·참외·파프리카)

========================================================
딸기와 동일한 파이프라인 구조를 CropConfig 기반으로 일반화.
각 작목별로 독립 모델 학습 후 통합 메타모델 구성.

실행:
  python scripts/train_multi_crop_pipeline.py          # 전체 작목
  python scripts/train_multi_crop_pipeline.py 방울토마토 # 단일 작목
  python scripts/train_multi_crop_pipeline.py --integrate # 통합만

출력:
  models/artifacts/{crop_en}_revenue_model.pkl   (작목별)
  docs/{crop_en}_validation_report.json          (작목별)
  models/artifacts/integrated_model_meta.json    (통합)
  docs/multi_crop_validation_report.json         (통합 검증)
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 경로 ─────────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "기초자료" / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터"
OUT_DIR  = ROOT / "models" / "artifacts"
DOCS_DIR = ROOT / "docs"
YEARS    = [2018, 2019, 2020, 2021, 2022]

# ── 공통 환경 변수 ─────────────────────────────────────────────────────────────
ENV_COLS = {
    "온도_내부":     "temp_internal",
    "상대습도_내부": "humidity_int",
    "잔존CO2":       "co2_ppm",
    "토양온도":      "soil_temp",
    "일사량_외부":   "solar_rad",
    "온도_외부":     "temp_external",
    "풍속_외부":     "wind_speed",
}
ENV_HARD_BOUNDS = {
    "temp_internal": (-5.0, 55.0),
    "humidity_int":  (0.0, 100.0),
    "co2_ppm":       (0.0, 5000.0),
    "soil_temp":     (-5.0, 50.0),
    "solar_rad":     (0.0, 1500.0),
    "temp_external": (-20.0, 45.0),
    "wind_speed":    (0.0, 30.0),
}

# ── 작목별 설정 ───────────────────────────────────────────────────────────────

@dataclass
class CropConfig:
    crop_ko:    str               # 한국어 품목명
    crop_en:    str               # 영문 파일명
    t_base:     float             # GDD 기준온도
    growth_cols: list[str]        # 생육 측정 변수
    opt_temp_range:  tuple[float, float] = (14.0, 28.0)
    opt_humid_range: tuple[float, float] = (50.0, 85.0)
    opt_co2_range:   tuple[float, float] = (400.0, 1600.0)


CROP_CONFIGS: dict[str, CropConfig] = {
    "방울토마토": CropConfig(
        crop_ko="방울토마토",
        crop_en="cherry_tomato",
        t_base=10.0,
        growth_cols=["초장", "생장길이", "엽수", "엽장", "엽폭", "줄기굵기",
                     "화방별꽃수", "화방별개화수", "화방별착과수"],
        opt_temp_range=(18.0, 28.0),
        opt_humid_range=(55.0, 80.0),
        opt_co2_range=(600.0, 1400.0),
    ),
    "완숙토마토": CropConfig(
        crop_ko="완숙토마토",
        crop_en="tomato",
        t_base=10.0,
        growth_cols=["초장", "생장길이", "엽수", "엽장", "엽폭", "줄기굵기",
                     "화방별꽃수", "화방별개화수", "화방별착과수", "개화군", "착과군"],
        opt_temp_range=(18.0, 28.0),
        opt_humid_range=(55.0, 80.0),
        opt_co2_range=(600.0, 1400.0),
    ),
    "참외": CropConfig(
        crop_ko="참외",
        crop_en="melon",
        t_base=12.0,
        growth_cols=["초장", "마디수", "평균절간장", "줄기굵기",
                     "엽장", "엽폭", "엽수", "암꽃수", "착과수"],
        opt_temp_range=(22.0, 32.0),
        opt_humid_range=(55.0, 75.0),
        opt_co2_range=(400.0, 1200.0),
    ),
    "파프리카": CropConfig(
        crop_ko="파프리카",
        crop_en="paprika",
        t_base=10.0,
        growth_cols=["초장", "생장길이", "엽수", "엽장", "엽폭", "줄기굵기",
                     "화방높이", "개화마디", "착과마디"],
        opt_temp_range=(20.0, 28.0),
        opt_humid_range=(60.0, 80.0),
        opt_co2_range=(600.0, 1400.0),
    ),
    "딸기": CropConfig(
        crop_ko="딸기",
        crop_en="strawberry",
        t_base=6.0,
        growth_cols=["초장", "엽수", "엽장", "엽폭", "화방별착과수"],
        opt_temp_range=(14.0, 22.0),
        opt_humid_range=(55.0, 80.0),
        opt_co2_range=(600.0, 1200.0),
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _norm_farm_id(v: str) -> str:
    v = str(v).strip()
    try:
        return str(int(float(v)))
    except (ValueError, OverflowError):
        return v


def _normalize_keys(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["year", "month"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float").astype("Int64")
    if "farm_id" in df.columns:
        df["farm_id"] = df["farm_id"].astype(str).str.strip().apply(_norm_farm_id)
    return df


def clip_iqr(series: pd.Series, factor: float = 1.5) -> pd.Series:
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    iqr = q3 - q1
    return series.clip(lower=q1 - factor * iqr, upper=q3 + factor * iqr)


def impute_series(series: pd.Series) -> pd.Series:
    s = series.interpolate(method="linear", limit_direction="both")
    s = s.ffill().bfill()
    if s.isna().any():
        gm = series.mean()
        s = s.fillna(gm if not np.isnan(gm) else 0.0)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────────────────────────────────────

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


def load_env_crop(year: int, crop_ko: str) -> pd.DataFrame:
    frames = _read_crop_csvs(year, crop_ko)
    env_frames = [f for f in frames if "측정시간" in f.columns]
    if not env_frames:
        return pd.DataFrame()
    df = pd.concat(env_frames, ignore_index=True)
    logger.info("  [%d] %s 환경 %d행", year, crop_ko, len(df))
    return df


def load_growth_crop(year: int, crop_ko: str, growth_cols: list[str]) -> pd.DataFrame:
    frames = _read_crop_csvs(year, crop_ko)
    g_frames = [
        f for f in frames
        if "조사일자" in f.columns and "측정시간" not in f.columns
        and any(c in f.columns for c in growth_cols)
    ]
    if not g_frames:
        return pd.DataFrame()
    df = pd.concat(g_frames, ignore_index=True)
    logger.info("  [%d] %s 생육 %d행", year, crop_ko, len(df))
    return df


def load_production_crop(year: int, crop_ko: str) -> pd.DataFrame:
    frames = _read_crop_csvs(year, crop_ko)
    p_frames = [f for f in frames if "출하일자" in f.columns and "총출하량" in f.columns]
    if not p_frames:
        return pd.DataFrame()
    df = pd.concat(p_frames, ignore_index=True)
    logger.info("  [%d] %s 생산 %d행", year, crop_ko, len(df))
    return df


def load_cultivation_crop(year: int, crop_ko: str) -> pd.DataFrame:
    zp = DATA_DIR / f"스마트팜_{year}.zip"
    if not zp.exists():
        return pd.DataFrame()
    with zipfile.ZipFile(zp) as zf:
        for info in zf.infolist():
            if "csv" not in info.filename.lower():
                continue
            try:
                raw = zf.read(info.filename)
                df = pd.read_csv(io.BytesIO(raw), encoding="euc-kr", low_memory=False)
                if "정식일" in df.columns and "품목" in df.columns:
                    dc = df[df["품목"].astype(str).str.strip() == crop_ko].copy()
                    if len(dc) > 0:
                        return dc
            except Exception:
                pass
    return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# 전처리 & 집계
# ─────────────────────────────────────────────────────────────────────────────

def preprocess_env(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    time_col = "측정시간" if "측정시간" in df.columns else "측정일시"
    if time_col in df.columns:
        df["dt"] = pd.to_datetime(df[time_col], errors="coerce")
    else:
        df["dt"] = pd.NaT
    df["year"]  = df["dt"].dt.year
    df["month"] = df["dt"].dt.month
    fc = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
    df["farm_id"] = df[fc].astype(str).str.strip().apply(_norm_farm_id) if fc else "unknown"
    for orig, canon in ENV_COLS.items():
        if orig in df.columns:
            df[canon] = pd.to_numeric(df[orig], errors="coerce")
            lo, hi = ENV_HARD_BOUNDS.get(canon, (-1e6, 1e6))
            df.loc[~df[canon].between(lo, hi), canon] = np.nan
    return df


def agg_env_monthly(df: pd.DataFrame, t_base: float) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    env_vars = [c for c in ENV_COLS.values() if c in df.columns]
    if not env_vars:
        return pd.DataFrame()
    for col in env_vars:
        df[col] = clip_iqr(df[col])
    agg_dict = {col: ["mean", "std", "min", "max"] for col in env_vars}
    monthly = df.groupby(["farm_id", "year", "month"]).agg(agg_dict).reset_index()
    monthly.columns = [
        "_".join(c).strip("_") if c[1] else c[0]
        for c in monthly.columns
    ]
    if "temp_internal_mean" in monthly.columns:
        monthly["gdd_monthly"] = (
            monthly["temp_internal_mean"] - t_base
        ).clip(lower=0.0) * 30.0
    for col in [c for c in monthly.columns if c not in ["farm_id", "year", "month"]]:
        for _, grp in monthly.groupby("farm_id"):
            monthly.loc[grp.index, col] = impute_series(grp[col])
    logger.info("    환경 월집계: %d행", len(monthly))
    return monthly


def agg_growth_monthly(df: pd.DataFrame, growth_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    if "조사일자" not in df.columns:
        return pd.DataFrame()
    df["dt"]    = pd.to_datetime(df["조사일자"], errors="coerce")
    df["year"]  = df["dt"].dt.year
    df["month"] = df["dt"].dt.month
    fc = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
    df["farm_id"] = df[fc].astype(str).str.strip().apply(_norm_farm_id) if fc else "unknown"
    avail = [c for c in growth_cols if c in df.columns]
    for col in avail:
        df[col] = clip_iqr(pd.to_numeric(df[col], errors="coerce"))
    monthly = df.groupby(["farm_id", "year", "month"])[avail].mean().reset_index()
    monthly.columns = [f"growth_{c}" if c in avail else c for c in monthly.columns]
    for col in [c for c in monthly.columns if c.startswith("growth_")]:
        for _, grp in monthly.groupby("farm_id"):
            monthly.loc[grp.index, col] = impute_series(grp[col])
    logger.info("    생육 월집계: %d행", len(monthly))
    return monthly


def agg_prod_monthly(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    if "출하일자" not in df.columns:
        return pd.DataFrame()
    df["dt"]    = pd.to_datetime(df["출하일자"], errors="coerce")
    df["year"]  = df["dt"].dt.year
    df["month"] = df["dt"].dt.month
    fc = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
    df["farm_id"] = df[fc].astype(str).str.strip().apply(_norm_farm_id) if fc else "unknown"
    df["총출하량"] = pd.to_numeric(df.get("총출하량", 0), errors="coerce").fillna(0)
    df["판매금액"] = pd.to_numeric(df.get("판매금액", 0), errors="coerce").fillna(0)
    monthly = (
        df.groupby(["farm_id", "year", "month"])
        .agg({"총출하량": "sum", "판매금액": "sum"})
        .reset_index()
        .rename(columns={"총출하량": "yield_kg", "판매금액": "revenue_krw"})
    )
    monthly["yield_kg"]    = monthly["yield_kg"].clip(lower=0)
    monthly["revenue_krw"] = monthly["revenue_krw"].clip(lower=0)
    logger.info("    생산 월집계: %d행", len(monthly))
    return monthly


def add_cultiv_features(df: pd.DataFrame, cultiv_df: pd.DataFrame) -> pd.DataFrame:
    if cultiv_df.empty or "정식일" not in cultiv_df.columns:
        df["weeks_since_planting"] = np.nan
        df["area_m2"] = 1000.0
        return df
    fc = next((c for c in ["농가명", "농가ID"] if c in cultiv_df.columns), None)
    if fc is None:
        df["weeks_since_planting"] = np.nan
        df["area_m2"] = 1000.0
        return df
    cultiv_df["farm_id"] = cultiv_df[fc].astype(str).str.strip().apply(_norm_farm_id)
    cultiv_df["planting_dt"] = pd.to_datetime(cultiv_df["정식일"], errors="coerce")
    area_col = next((c for c in ["식부면적", "총면적"] if c in cultiv_df.columns), None)
    farm_info = (
        cultiv_df[["farm_id", "planting_dt"]]
        .assign(area_m2=pd.to_numeric(
            cultiv_df[area_col], errors="coerce").fillna(1000.0) * 100
            if area_col else 1000.0
        )
        .drop_duplicates("farm_id")
        .set_index("farm_id")
    )

    def _weeks(row):
        if row["farm_id"] not in farm_info.index:
            return np.nan
        fi = farm_info.loc[row["farm_id"]]
        if pd.isna(fi["planting_dt"]):
            return np.nan
        ref = pd.Timestamp(year=int(row["year"]), month=int(row["month"]), day=15)
        return max(0, (ref - fi["planting_dt"]).days // 7)

    df["weeks_since_planting"] = df.apply(_weeks, axis=1)
    df["area_m2"] = df["farm_id"].map(
        farm_info["area_m2"].to_dict()
    ).fillna(1000.0)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 피처 행렬 구성
# ─────────────────────────────────────────────────────────────────────────────

def build_feature_matrix(
    env_m: pd.DataFrame,
    growth_m: pd.DataFrame,
    prod_m: pd.DataFrame,
    config: CropConfig,
) -> pd.DataFrame:
    if env_m.empty:
        return pd.DataFrame()
    key = ["farm_id", "year", "month"]
    df = _normalize_keys(env_m.copy())
    if not growth_m.empty:
        df = df.merge(_normalize_keys(growth_m.copy()), on=key, how="left")
    if not prod_m.empty:
        df = df.merge(_normalize_keys(prod_m.copy()), on=key, how="left")
        df["yield_kg"]    = df["yield_kg"].fillna(0)
        df["revenue_krw"] = df["revenue_krw"].fillna(0)
    else:
        df["yield_kg"]    = 0.0
        df["revenue_krw"] = 0.0

    # GDD 누적
    df = df.sort_values(["farm_id", "year", "month"])
    if "gdd_monthly" in df.columns:
        df["gdd_cumsum"] = df.groupby("farm_id")["gdd_monthly"].cumsum().fillna(0)

    # 이동평균
    for col in ["temp_internal_mean", "co2_ppm_mean", "humidity_int_mean"]:
        if col in df.columns:
            df[f"{col}_ma3"] = df.groupby("farm_id")[col].transform(
                lambda s: s.rolling(3, min_periods=1).mean()
            )

    # 초장 증분
    g_col = "growth_초장"
    if g_col in df.columns:
        df["초장_월간_증분"] = df.groupby("farm_id")[g_col].diff().fillna(0)

    # 단위면적당 수익 (임시: area_m2=1000, add_cultiv_features 후 재계산)
    if "revenue_krw" in df.columns:
        area = df.get("area_m2", pd.Series(1000.0, index=df.index)).fillna(1000.0).replace(0, 1000.0)
        df["revenue_per_m2"] = df["revenue_krw"].astype(float) / area
        df["yield_per_m2"]   = df["yield_kg"].astype(float) / area

    # 작목 레이블
    df["crop"] = config.crop_ko
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 모델 학습
# ─────────────────────────────────────────────────────────────────────────────

ENV_FEATURE_COLS = [
    "temp_internal_mean", "temp_internal_std",
    "humidity_int_mean", "humidity_int_std",
    "co2_ppm_mean", "solar_rad_mean", "soil_temp_mean",
    "gdd_monthly", "gdd_cumsum",
    "temp_internal_mean_ma3", "co2_ppm_mean_ma3", "humidity_int_mean_ma3",
]


def _feature_cols(df: pd.DataFrame, growth_cols: list[str]) -> list[str]:
    g_feats = [f"growth_{c}" for c in growth_cols] + ["초장_월간_증분"]
    all_cols = ENV_FEATURE_COLS + g_feats + ["month", "weeks_since_planting"]
    return [c for c in all_cols if c in df.columns]


def train_model(df_train: pd.DataFrame, target: str, config: CropConfig) -> dict:
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    from sklearn.metrics import r2_score, mean_absolute_percentage_error

    feat_cols = _feature_cols(df_train, config.growth_cols)
    mask = df_train[target].astype(float) > 0
    X_raw = df_train.loc[mask, feat_cols]
    y     = df_train.loc[mask, target].astype(float)
    n     = len(X_raw)
    logger.info("    학습 샘플: %d개  피처: %d개", n, len(feat_cols))

    imputer = SimpleImputer(strategy="median")
    X = imputer.fit_transform(X_raw)

    if n < 10:
        scaler = StandardScaler()
        X_sc = scaler.fit_transform(X)
        model = Ridge(alpha=10.0)
        model.fit(X_sc, y)
        y_pred = model.predict(X_sc)
        return {
            "type": "ridge_fallback", "model": model, "imputer": imputer, "scaler": scaler,
            "feature_cols": feat_cols,
            "train_r2": round(float(r2_score(y, y_pred)), 4),
            "train_mape": round(float(mean_absolute_percentage_error(y, y_pred) * 100), 2),
            "n_train": n, "crop": config.crop_ko,
        }

    preds = []
    result: dict = {"type": "xgb_lgb_ensemble", "feature_cols": feat_cols,
                    "imputer": imputer, "n_train": n, "crop": config.crop_ko}
    try:
        import xgboost as xgb
        xgb_m = xgb.XGBRegressor(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
            random_state=42, verbosity=0)
        xgb_m.fit(X, y)
        preds.append(xgb_m.predict(X))
        result["xgb_model"] = xgb_m
    except ImportError:
        pass
    try:
        import lightgbm as lgb
        lgb_m = lgb.LGBMRegressor(
            n_estimators=300, num_leaves=31, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_samples=5,
            random_state=42, verbosity=-1)
        lgb_m.fit(X, y)
        preds.append(lgb_m.predict(X))
        result["lgb_model"] = lgb_m
    except ImportError:
        pass

    if not preds:
        scaler = StandardScaler()
        X_sc = scaler.fit_transform(X)
        model = Ridge(alpha=10.0)
        model.fit(X_sc, y)
        y_pred = model.predict(X_sc)
        result.update({"type": "ridge_fallback", "model": model, "scaler": scaler})
        preds = [y_pred]
        result["type"] = "ridge_fallback"

    y_pred_ens = np.mean(preds, axis=0)
    r2   = float(r2_score(y, y_pred_ens))
    mape = float(mean_absolute_percentage_error(y, y_pred_ens) * 100)
    result["train_r2"]   = round(r2, 4)
    result["train_mape"] = round(mape, 2)
    logger.info("    [%s %s] train R2=%.3f  MAPE=%.1f%%",
                config.crop_ko, result["type"], r2, mape)
    return result


def predict(model_info: dict, X_df: pd.DataFrame) -> np.ndarray:
    feat_cols = model_info["feature_cols"]
    X = model_info["imputer"].transform(X_df.reindex(columns=feat_cols))
    if model_info["type"] == "ridge_fallback":
        if "scaler" in model_info:
            X = model_info["scaler"].transform(X)
        return model_info["model"].predict(X)
    ps = []
    if "xgb_model" in model_info:
        ps.append(model_info["xgb_model"].predict(X))
    if "lgb_model" in model_info:
        ps.append(model_info["lgb_model"].predict(X))
    return np.mean(ps, axis=0) if ps else np.zeros(len(X))


def validate(model_info: dict, df_test: pd.DataFrame, target: str) -> dict:
    from sklearn.metrics import r2_score, mean_absolute_percentage_error, mean_squared_error
    mask = df_test[target].astype(float) > 0
    if int(mask.sum()) < 3:
        return {"n_test": int(mask.sum()), "note": "샘플 부족"}
    y_true = df_test.loc[mask, target].astype(float).values
    y_pred = predict(model_info, df_test.loc[mask])
    r2   = float(r2_score(y_true, y_pred))
    mape = float(mean_absolute_percentage_error(y_true, y_pred) * 100)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    logger.info("    [검증] R2=%.3f  MAPE=%.1f%%  RMSE=%.0f", r2, mape, rmse)
    return {
        "n_test": int(mask.sum()), "r2": round(r2, 4),
        "mape_pct": round(mape, 2), "rmse": round(rmse, 2),
        "y_true_sample": y_true[:5].tolist(),
        "y_pred_sample": [round(float(v), 0) for v in y_pred[:5]],
    }


def optimize(model_info: dict, sample_env: dict, area_m2: float,
             config: CropConfig, n_months: int = 6) -> dict:
    from itertools import product as iproduct
    survey_path = ROOT / "api" / "data" / "income_survey.json"
    if survey_path.exists():
        d = json.loads(survey_path.read_text(encoding="utf-8"))
        costs = d.get(config.crop_ko, d.get("딸기", {})).get("cost_per_m2", {})
    else:
        costs = {"seed": 800, "fertilizer": 180, "pesticide": 280,
                 "utility": 450, "labor": 2800, "depreciation": 162, "other": 500}
    monthly_cost = sum(costs.values()) / (150 / 30) * area_m2

    t_lo, t_hi = config.opt_temp_range
    h_lo, h_hi = config.opt_humid_range
    c_lo, c_hi = config.opt_co2_range
    temp_range  = np.arange(t_lo, t_hi + 0.5, 2.0)
    humid_range = np.arange(h_lo, h_hi + 0.5, 5.0)
    co2_range   = np.arange(c_lo, c_hi + 0.5, 200.0)

    best = {"income": -1e9}
    results = []
    for temp, humid, co2 in iproduct(temp_range, humid_range, co2_range):
        cand = {**sample_env, "temp_internal_mean": temp,
                "humidity_int_mean": humid, "co2_ppm_mean": co2}
        cdf = pd.DataFrame([cand] * n_months)
        cdf["month"] = range(1, n_months + 1)
        rev_pm2 = float(np.mean(predict(model_info, cdf)))
        income  = (rev_pm2 * area_m2 - monthly_cost) * n_months
        results.append({"temp": temp, "humid": humid, "co2": co2,
                        "rev_per_m2": round(rev_pm2, 0), "income_total": round(income, 0)})
        if income > best["income"]:
            best = {
                "temp_internal": float(temp), "humidity_int": float(humid),
                "co2_ppm": float(co2),
                "revenue_per_m2": round(rev_pm2, 0),
                "monthly_revenue": round(rev_pm2 * area_m2, 0),
                "monthly_cost": round(monthly_cost, 0),
                "monthly_income": round(rev_pm2 * area_m2 - monthly_cost, 0),
                "total_income_6m": round(income, 0),
                "income": income,
            }
    top5 = sorted(results, key=lambda x: x["income_total"], reverse=True)[:5]
    best.pop("income", None)
    return {"best": best, "top5": top5}


# ─────────────────────────────────────────────────────────────────────────────
# 단일 작목 파이프라인
# ─────────────────────────────────────────────────────────────────────────────

def run_crop_pipeline(config: CropConfig) -> dict:
    logger.info("\n" + "=" * 58)
    logger.info("%s 파이프라인 시작", config.crop_ko)
    logger.info("=" * 58)

    all_env, all_growth, all_prod, all_cultiv = [], [], [], []
    for year in YEARS:
        logger.info("  [%d]", year)
        e = load_env_crop(year, config.crop_ko)
        g = load_growth_crop(year, config.crop_ko, config.growth_cols)
        p = load_production_crop(year, config.crop_ko)
        c = load_cultivation_crop(year, config.crop_ko)

        if not e.empty:
            e["year"] = year
            all_env.append(preprocess_env(e))
        if not g.empty:
            g["year"] = year
            all_growth.append(g)
        if not p.empty:
            p["year"] = year
            all_prod.append(p)
        if not c.empty:
            c["year"] = year
            all_cultiv.append(c)

    if not all_env:
        logger.warning("%s 환경 데이터 없음 — 건너뜀", config.crop_ko)
        return {"crop": config.crop_ko, "status": "no_env_data"}

    env_all    = pd.concat(all_env,    ignore_index=True)
    growth_all = pd.concat(all_growth, ignore_index=True) if all_growth else pd.DataFrame()
    prod_all   = pd.concat(all_prod,   ignore_index=True) if all_prod   else pd.DataFrame()
    cultiv_all = pd.concat(all_cultiv, ignore_index=True) if all_cultiv else pd.DataFrame()

    logger.info("  환경 %d행  생육 %d행  생산 %d행",
                len(env_all), len(growth_all) if not growth_all.empty else 0,
                len(prod_all) if not prod_all.empty else 0)

    env_m    = agg_env_monthly(env_all, config.t_base)
    growth_m = agg_growth_monthly(growth_all, config.growth_cols)
    prod_m   = agg_prod_monthly(prod_all)

    if env_m.empty:
        return {"crop": config.crop_ko, "status": "agg_failed"}

    df = build_feature_matrix(env_m, growth_m, prod_m, config)
    df = add_cultiv_features(df, cultiv_all)

    # 재계산
    if "area_m2" in df.columns and "revenue_krw" in df.columns:
        area = df["area_m2"].fillna(1000.0).replace(0, 1000.0)
        df["revenue_per_m2"] = df["revenue_krw"].astype(float) / area
        df["yield_per_m2"]   = df["yield_kg"].astype(float) / area

    # 연도 정규화
    df["year"]  = pd.to_numeric(df["year"],  errors="coerce").astype("float").astype("Int64")
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("float").astype("Int64")

    df_train = df[df["year"].fillna(0) < 2022].copy()
    df_test  = df[df["year"].fillna(0) == 2022].copy()
    logger.info("  학습 %d행  테스트 %d행", len(df_train), len(df_test))

    target = "revenue_per_m2" if "revenue_per_m2" in df.columns else "yield_per_m2"
    n_pos_train = int((df_train[target].astype(float) > 0).sum())
    if n_pos_train < 5:
        logger.warning("  %s 학습 양성 샘플 부족 (%d) — 부분 결과 저장", config.crop_ko, n_pos_train)
        meta = {"crop": config.crop_ko, "status": "insufficient_revenue_data",
                "n_train_rows": len(df_train), "n_pos_revenue": n_pos_train}
        DOCS_DIR.mkdir(exist_ok=True)
        rp = DOCS_DIR / f"{config.crop_en}_validation_report.json"
        rp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    logger.info("  [모델 학습]")
    model_info = train_model(df_train, target, config)

    logger.info("  [모델 검증]")
    val = validate(model_info, df_test, target)

    logger.info("  [소득 최적화 샘플]")
    sample_env = {}
    for col in ["temp_internal_mean", "humidity_int_mean", "co2_ppm_mean",
                "solar_rad_mean", "soil_temp_mean", "gdd_monthly"]:
        if col in df.columns:
            sample_env[col] = float(df[col].median())
    opt = optimize(model_info, sample_env, 1000.0, config)
    _inc = opt["best"].get("total_income_6m", 0)
    logger.info("  최적 조건: temp=%.1f  humid=%.0f  co2=%.0f  소득=%s원",
                opt["best"].get("temp_internal", 0),
                opt["best"].get("humidity_int", 0),
                opt["best"].get("co2_ppm", 0),
                f"{_inc:+,.0f}")

    # 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pkl_path = OUT_DIR / f"{config.crop_en}_revenue_model.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(model_info, f)

    report = {
        "crop": config.crop_ko, "crop_en": config.crop_en,
        "pipeline_version": "1.0",
        "data_years": YEARS, "test_year": 2022,
        "n_train": len(df_train), "n_test": len(df_test),
        "target": target, "model_type": model_info.get("type"),
        "feature_count": len(model_info.get("feature_cols", [])),
        "train_metrics": {"r2": model_info.get("train_r2"), "mape": model_info.get("train_mape")},
        "test_metrics": val,
        "optimization_sample": opt["best"],
        "top5_env_combinations": opt["top5"],
    }
    rp = DOCS_DIR / f"{config.crop_en}_validation_report.json"
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    meta_p = OUT_DIR / f"{config.crop_en}_pipeline_meta.json"
    with open(meta_p, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info("  저장: %s  R2=%.3f  MAPE=%.1f%%",
                pkl_path.name, model_info["train_r2"], model_info["train_mape"])
    return report


# ─────────────────────────────────────────────────────────────────────────────
# 통합 메타모델
# ─────────────────────────────────────────────────────────────────────────────

def build_integrated_model(crop_reports: dict[str, dict]) -> dict:
    """각 작목 모델의 예측값을 스택하여 통합 수익 지수 산출.

    현재 구현: 작목별 최적 조건 집계 + 소득 랭킹 테이블.
    향후 확장: 크로스-작목 앙상블, 계절성 보정, 작목 전환 비용 반영.
    """
    logger.info("\n[통합 모델 구성]")
    ranking = []
    for crop_ko, rpt in crop_reports.items():
        if "optimization_sample" not in rpt:
            continue
        opt = rpt["optimization_sample"]
        ranking.append({
            "crop": crop_ko,
            "crop_en": rpt.get("crop_en", ""),
            "optimal_temp": opt.get("temp_internal"),
            "optimal_humid": opt.get("humidity_int"),
            "optimal_co2": opt.get("co2_ppm"),
            "revenue_per_m2": opt.get("revenue_per_m2"),
            "monthly_cost": opt.get("monthly_cost"),
            "monthly_income": opt.get("monthly_income"),
            "total_income_6m": opt.get("total_income_6m"),
            "train_r2": rpt.get("train_metrics", {}).get("r2"),
            "test_r2":  rpt.get("test_metrics", {}).get("r2"),
        })

    if ranking:
        ranking.sort(key=lambda x: x.get("total_income_6m") or 0, reverse=True)
        logger.info("  작목별 6개월 소득 랭킹:")
        for i, r in enumerate(ranking, 1):
            logger.info("    %d. %s — %s원", i, r["crop"],
                        f"{r.get('total_income_6m', 0):+,.0f}")

    integrated_meta = {
        "version": "1.0",
        "description": "다작목 소득최적화 통합 메타 보고서",
        "crops_trained": list(crop_reports.keys()),
        "income_ranking": ranking,
        "notes": [
            "통합 모델은 작목별 독립 모델 예측값을 집계한 것",
            "각 작목 모델 pkl 파일로 독립 예측 가능",
            "향후: 크로스-작목 앙상블, 작목 전환 비용 반영 계획",
        ],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = OUT_DIR / "integrated_model_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(integrated_meta, f, ensure_ascii=False, indent=2)

    rpt_path = DOCS_DIR / "multi_crop_validation_report.json"
    DOCS_DIR.mkdir(exist_ok=True)
    with open(rpt_path, "w", encoding="utf-8") as f:
        json.dump(integrated_meta, f, ensure_ascii=False, indent=2)

    logger.info("  통합 메타: %s", meta_path)
    logger.info("  통합 리포트: %s", rpt_path)
    return integrated_meta


# ─────────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="다작목 소득최적화 파이프라인")
    parser.add_argument("crop", nargs="?", default=None,
                        help="단일 작목 실행 (예: 방울토마토). 생략 시 전체 실행")
    parser.add_argument("--integrate", action="store_true",
                        help="저장된 작목별 리포트로 통합 메타만 재구성")
    args = parser.parse_args()

    if args.integrate:
        # 기존 리포트 파일 로드 후 통합
        reports = {}
        for cfg in CROP_CONFIGS.values():
            rp = DOCS_DIR / f"{cfg.crop_en}_validation_report.json"
            if rp.exists():
                reports[cfg.crop_ko] = json.loads(rp.read_text(encoding="utf-8"))
        # 딸기 리포트도 포함
        strawberry_rp = DOCS_DIR / "strawberry_validation_report.json"
        if strawberry_rp.exists():
            d = json.loads(strawberry_rp.read_text(encoding="utf-8"))
            d["crop_en"] = "strawberry"
            reports["딸기"] = d
        build_integrated_model(reports)
        return

    if args.crop:
        if args.crop not in CROP_CONFIGS:
            logger.error("알 수 없는 작목: %s  (선택: %s)", args.crop, list(CROP_CONFIGS.keys()))
            sys.exit(1)
        run_crop_pipeline(CROP_CONFIGS[args.crop])
        return

    # 전체 작목 실행 (딸기 제외 — 별도 스크립트에서 이미 완료)
    target_crops = ["방울토마토", "완숙토마토", "참외", "파프리카"]
    crop_reports = {}
    for crop_ko in target_crops:
        cfg = CROP_CONFIGS[crop_ko]
        try:
            rpt = run_crop_pipeline(cfg)
            crop_reports[crop_ko] = rpt
        except Exception as e:
            logger.error("%s 파이프라인 오류: %s", crop_ko, e)
            crop_reports[crop_ko] = {"crop": crop_ko, "status": f"error: {e}"}

    # 딸기 리포트 합산
    strawberry_rp = DOCS_DIR / "strawberry_validation_report.json"
    if strawberry_rp.exists():
        d = json.loads(strawberry_rp.read_text(encoding="utf-8"))
        d["crop_en"] = "strawberry"
        crop_reports["딸기"] = d

    build_integrated_model(crop_reports)

    logger.info("\n[전체 완료]")
    for crop, rpt in crop_reports.items():
        tr = rpt.get("train_metrics", {}).get("r2", "N/A")
        te = rpt.get("test_metrics", {}).get("r2", "N/A")
        logger.info("  %s  train_R2=%s  test_R2=%s", crop, tr, te)


if __name__ == "__main__":
    main()
