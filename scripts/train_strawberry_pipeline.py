"""딸기 소득최적화 모델 파이프라인 (2018-2022 농진청 패널)

=========================================================
데이터 흐름
=========================================================
1. 데이터 로드 & 통합
   환경_YYYY.csv  ─┐
   생육_딸기_YYYY ─┤ → 월별 집계 → 병합
   생산_YYYY.csv  ─┤
   재배정보_YYYY  ─┘

2. 전처리
   - 결측치: 시계열 선형보간 → 앞방향/뒤방향 채움 → 전체 평균
   - 이상치: IQR 1.5배 기준 상한·하한 클리핑 (제거 아닌 클리핑)
   - 모든 행 처리 (건너뜀 없음)

3. 피처 엔지니어링
   - GDD 누적 (기준온도 6°C)
   - 정식 후 경과 주수
   - 3주 이동평균 (env 변수)
   - 초장 성장률 (주별 증분)

4. 모델 학습
   M1: 매출 예측  (XGBoost + LightGBM 앙상블)
   M2: 비용 추정  (고정비 + income_survey.json 변동비)
   M3: 소득 = M1 - M2
   최적화: 환경 그리드 서치 → 소득 최대 조합

5. 검증
   - 시간 기준 분할: 2018-2021 학습, 2022 테스트
   - 매출 R² / MAPE
   - 소득 MAPE
   - 샘플 최적화 시뮬레이션

출력:
   models/artifacts/strawberry_revenue_model.pkl
   models/artifacts/strawberry_pipeline_meta.json
   docs/strawberry_validation_report.json

실행:
   python scripts/train_strawberry_pipeline.py
"""
from __future__ import annotations

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

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).parent.parent
DATA_DIR  = ROOT / "기초자료" / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터"
OUT_DIR   = ROOT / "models" / "artifacts"
DOCS_DIR  = ROOT / "docs"
YEARS     = [2018, 2019, 2020, 2021, 2022]

# GDD 기준온도 (딸기)
T_BASE_STRAWBERRY = 6.0

# 환경 변수 매핑
ENV_COLS = {
    "온도_내부":     "temp_internal",
    "상대습도_내부": "humidity_int",
    "잔존CO2":       "co2_ppm",
    "토양온도":      "soil_temp",
    "일사량_외부":   "solar_rad",
    "온도_외부":     "temp_external",
    "풍속_외부":     "wind_speed",
}

# 유효 범위 (IQR 클리핑 전 하드 필터)
ENV_HARD_BOUNDS = {
    "temp_internal": (-5.0, 55.0),
    "humidity_int":  (0.0, 100.0),
    "co2_ppm":       (0.0, 5000.0),
    "soil_temp":     (-5.0, 50.0),
    "solar_rad":     (0.0, 1500.0),
    "temp_external": (-20.0, 45.0),
    "wind_speed":    (0.0, 30.0),
}

# 딸기 생육 변수
GROWTH_COLS_STR = ["초장", "엽수", "엽장", "엽폭", "화방별착과수"]

# ─────────────────────────────────────────────────────────────────────────────
# 1. 데이터 로드
# ─────────────────────────────────────────────────────────────────────────────

def _decode_zip_name(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("euc-kr", errors="replace")


def _read_csv_from_zip(
    zip_path: Path,
    keyword: Optional[str] = None,
    filter_crop: str = "딸기",
) -> list[pd.DataFrame]:
    """ZIP 파일에서 CSV를 읽어 딸기 행만 반환 (모든 일치 파일).

    keyword가 None이면 품목 컬럼으로 딸기 행 필터링.
    keyword가 있으면 파일명에 keyword가 포함된 파일만.
    """
    if not zip_path.exists():
        logger.warning("ZIP 없음: %s", zip_path.name)
        return []

    frames = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if not info.filename.lower().endswith(".csv"):
                continue
            fname = info.filename
            if keyword and keyword.lower() not in fname.lower():
                continue
            try:
                raw = zf.read(fname)
                df = pd.read_csv(
                    io.BytesIO(raw), encoding="euc-kr", low_memory=False,
                )
                if "품목" in df.columns:
                    df_crop = df[df["품목"].astype(str).str.strip() == filter_crop].copy()
                    if len(df_crop) > 0:
                        frames.append(df_crop)
                        logger.debug("  %s → %d행 (%s)", fname, len(df_crop), filter_crop)
            except Exception as e:
                logger.warning("  읽기 실패 %s: %s", fname, e)
    return frames


def load_env(year: int) -> pd.DataFrame:
    """환경 데이터 로드."""
    zip_path = DATA_DIR / f"스마트팜_{year}.zip"
    frames = _read_csv_from_zip(zip_path, filter_crop="딸기")
    if not frames:
        logger.warning("[%d] 환경 딸기 데이터 없음", year)
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    logger.info("[%d] 환경 %d행", year, len(df))
    return df


def load_growth(year: int) -> pd.DataFrame:
    """생육 데이터 로드 (딸기 한정)."""
    zip_path = DATA_DIR / f"스마트팜_{year}.zip"
    frames = _read_csv_from_zip(zip_path, filter_crop="딸기")
    # 생육 파일 = 조사일자 컬럼 있고 측정시간 컬럼 없는 것
    growth_frames = [
        f for f in frames
        if "조사일자" in f.columns and "측정시간" not in f.columns
        and "초장" in f.columns  # 딸기 생육 식별
    ]
    if not growth_frames:
        logger.warning("[%d] 생육 딸기 데이터 없음", year)
        return pd.DataFrame()
    df = pd.concat(growth_frames, ignore_index=True)
    logger.info("[%d] 생육 %d행", year, len(df))
    return df


def load_production(year: int) -> pd.DataFrame:
    """생산(출하) 데이터 로드."""
    zip_path = DATA_DIR / f"스마트팜_{year}.zip"
    frames = _read_csv_from_zip(zip_path, filter_crop="딸기")
    # 생산 파일 = 출하일자 + 총출하량 + 판매금액
    prod_frames = [
        f for f in frames
        if "출하일자" in f.columns and "총출하량" in f.columns
    ]
    if not prod_frames:
        logger.warning("[%d] 생산 딸기 데이터 없음", year)
        return pd.DataFrame()
    df = pd.concat(prod_frames, ignore_index=True)
    logger.info("[%d] 생산 %d행", year, len(df))
    return df


def load_cultivation_info(year: int) -> pd.DataFrame:
    """재배정보 (정식일, 식부면적) 로드."""
    zip_path = DATA_DIR / f"스마트팜_{year}.zip"
    if not zip_path.exists():
        return pd.DataFrame()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if "csv" not in info.filename.lower():
                continue
            try:
                raw = zf.read(info.filename)
                df = pd.read_csv(io.BytesIO(raw), encoding="euc-kr", low_memory=False)
                if "정식일" in df.columns and "품목" in df.columns:
                    df_crop = df[df["품목"].astype(str).str.strip() == "딸기"].copy()
                    if len(df_crop) > 0:
                        logger.info("[%d] 재배정보 %d행", year, len(df_crop))
                        return df_crop
            except Exception:
                pass
    logger.warning("[%d] 재배정보 딸기 없음", year)
    return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# 2. 전처리
# ─────────────────────────────────────────────────────────────────────────────

def preprocess_env(df: pd.DataFrame) -> pd.DataFrame:
    """환경 데이터 전처리."""
    if df.empty:
        return df

    # 시간 파싱
    time_col = "측정시간" if "측정시간" in df.columns else "측정일시"
    if time_col in df.columns:
        df["dt"] = pd.to_datetime(df[time_col], errors="coerce")
    else:
        df["dt"] = pd.NaT

    df["year"]  = df["dt"].dt.year
    df["month"] = df["dt"].dt.month

    # 농가 ID 정규화
    farm_col = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
    df["farm_id"] = df[farm_col].astype(str).str.strip().apply(_norm_farm_id) if farm_col else "unknown"

    # 환경 변수 추출 및 하드 범위 필터
    for orig, canon in ENV_COLS.items():
        if orig in df.columns:
            df[canon] = pd.to_numeric(df[orig], errors="coerce")
            lo, hi = ENV_HARD_BOUNDS.get(canon, (-1e6, 1e6))
            df.loc[~df[canon].between(lo, hi), canon] = np.nan

    return df


def clip_iqr(series: pd.Series, factor: float = 1.5) -> pd.Series:
    """IQR 방법으로 이상치를 클리핑 (제거 아닌 경계값 대체).

    전체 데이터를 유지하면서 극단값만 보정.
    """
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    iqr = q3 - q1
    lo  = q1 - factor * iqr
    hi  = q3 + factor * iqr
    return series.clip(lower=lo, upper=hi)


def impute_series(series: pd.Series) -> pd.Series:
    """결측치 보간: 선형보간 → 앞방향 채움 → 뒤방향 채움 → 전체 평균."""
    s = series.interpolate(method="linear", limit_direction="both")
    s = s.ffill().bfill()
    if s.isna().any():
        global_mean = series.mean()
        s = s.fillna(global_mean if not np.isnan(global_mean) else 0.0)
    return s


def aggregate_env_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """환경 데이터를 (farm_id, year, month) 단위로 월별 집계."""
    if df.empty:
        return pd.DataFrame()

    env_vars = [c for c in ENV_COLS.values() if c in df.columns]
    if not env_vars:
        return pd.DataFrame()

    # IQR 클리핑 (전체 데이터 기준)
    for col in env_vars:
        df[col] = clip_iqr(df[col])

    agg_dict = {col: ["mean", "std", "min", "max"] for col in env_vars}
    monthly = (
        df.groupby(["farm_id", "year", "month"])
        .agg(agg_dict)
        .reset_index()
    )
    monthly.columns = [
        "_".join(c).strip("_") if c[1] else c[0]
        for c in monthly.columns
    ]

    # GDD 계산 (월 평균 온도 사용)
    temp_mean_col = "temp_internal_mean"
    if temp_mean_col in monthly.columns:
        monthly["gdd_monthly"] = (
            monthly[temp_mean_col] - T_BASE_STRAWBERRY
        ).clip(lower=0.0) * 30.0  # 월 30일 가정

    # 결측치 보간 (farm별로)
    for col in [c for c in monthly.columns if c not in ["farm_id", "year", "month"]]:
        for farm, grp in monthly.groupby("farm_id"):
            idx = grp.index
            monthly.loc[idx, col] = impute_series(grp[col])

    logger.info("  환경 월집계: %d행", len(monthly))
    return monthly


def aggregate_growth_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """생육 데이터를 월별 집계."""
    if df.empty:
        return pd.DataFrame()

    date_col = "조사일자"
    if date_col not in df.columns:
        return pd.DataFrame()

    df["dt"]    = pd.to_datetime(df[date_col], errors="coerce")
    df["year"]  = df["dt"].dt.year
    df["month"] = df["dt"].dt.month
    farm_col = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
    df["farm_id"] = df[farm_col].astype(str).str.strip().apply(_norm_farm_id) if farm_col else "unknown"

    avail_growth = [c for c in GROWTH_COLS_STR if c in df.columns]
    for col in avail_growth:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = clip_iqr(df[col])

    agg_dict = {col: "mean" for col in avail_growth}
    monthly  = (
        df.groupby(["farm_id", "year", "month"])
        .agg(agg_dict)
        .reset_index()
    )
    monthly.columns = [
        f"growth_{c}" if c in avail_growth else c
        for c in monthly.columns
    ]

    for col in [c for c in monthly.columns if c.startswith("growth_")]:
        for farm, grp in monthly.groupby("farm_id"):
            idx = grp.index
            monthly.loc[idx, col] = impute_series(grp[col])

    logger.info("  생육 월집계: %d행", len(monthly))
    return monthly


def aggregate_production_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """생산/출하 데이터를 월별 집계."""
    if df.empty:
        return pd.DataFrame()

    date_col = "출하일자"
    if date_col not in df.columns:
        return pd.DataFrame()

    df["dt"]    = pd.to_datetime(df[date_col], errors="coerce")
    df["year"]  = df["dt"].dt.year
    df["month"] = df["dt"].dt.month
    farm_col = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
    df["farm_id"] = df[farm_col].astype(str).str.strip().apply(_norm_farm_id) if farm_col else "unknown"

    df["총출하량"] = pd.to_numeric(df.get("총출하량", 0), errors="coerce").fillna(0)
    df["판매금액"] = pd.to_numeric(df.get("판매금액", 0), errors="coerce").fillna(0)

    monthly = (
        df.groupby(["farm_id", "year", "month"])
        .agg({"총출하량": "sum", "판매금액": "sum"})
        .reset_index()
        .rename(columns={"총출하량": "yield_kg", "판매금액": "revenue_krw"})
    )

    # 이상치 클리핑 (음수 제거)
    monthly["yield_kg"]   = monthly["yield_kg"].clip(lower=0)
    monthly["revenue_krw"] = monthly["revenue_krw"].clip(lower=0)

    logger.info("  생산 월집계: %d행", len(monthly))
    return monthly


def add_cultivation_features(
    df: pd.DataFrame,
    cultiv_df: pd.DataFrame,
) -> pd.DataFrame:
    """재배정보에서 정식일 기반 경과 주수 추가."""
    if cultiv_df.empty or "정식일" not in cultiv_df.columns:
        df["weeks_since_planting"] = np.nan
        df["area_m2"] = 1000.0
        return df

    farm_col = next(
        (c for c in ["농가명", "농가ID"] if c in cultiv_df.columns),
        None,
    )
    if farm_col is None:
        df["weeks_since_planting"] = np.nan
        df["area_m2"] = 1000.0
        return df

    cultiv_df["farm_id"]    = cultiv_df[farm_col].astype(str).str.strip()
    cultiv_df["정식일_dt"] = pd.to_datetime(cultiv_df["정식일"], errors="coerce")
    area_col = next(
        (c for c in ["식부면적", "총면적"] if c in cultiv_df.columns),
        None,
    )

    farm_info = (
        cultiv_df[["farm_id", "정식일_dt"]]
        .assign(area_m2=pd.to_numeric(
            cultiv_df[area_col], errors="coerce").fillna(1000.0) * 100
            if area_col else 1000.0
        )
        .drop_duplicates("farm_id")
        .set_index("farm_id")
    )

    def compute_weeks(row):
        fi = farm_info.get(row["farm_id"]) if hasattr(farm_info, "get") else (
            farm_info.loc[row["farm_id"]] if row["farm_id"] in farm_info.index else None
        )
        if fi is None:
            return np.nan
        ref_date = pd.Timestamp(year=int(row["year"]), month=int(row["month"]), day=15)
        if pd.isna(fi["정식일_dt"]):
            return np.nan
        delta = (ref_date - fi["정식일_dt"]).days
        return max(0, delta // 7)

    df["weeks_since_planting"] = df.apply(compute_weeks, axis=1)
    df["area_m2"] = df["farm_id"].map(
        farm_info["area_m2"].to_dict()
    ).fillna(1000.0)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 3. 피처 엔지니어링 + 병합
# ─────────────────────────────────────────────────────────────────────────────

def _norm_farm_id(v: str) -> str:
    """농가ID 정규화: '1.0' → '1', '001' → '1', '10' → '10'.

    연도별로 형식이 다른 농가ID (숫자+소수점, 선행0)를 통일된 정수 문자열로 변환.
    """
    v = str(v).strip()
    try:
        return str(int(float(v)))
    except (ValueError, OverflowError):
        return v


def _normalize_keys(df: pd.DataFrame) -> pd.DataFrame:
    """year, month, farm_id 컬럼 정규화 (병합 키 타입 불일치 방지)."""
    for col in ["year", "month"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    if "farm_id" in df.columns:
        df["farm_id"] = df["farm_id"].astype(str).str.strip().apply(_norm_farm_id)
    return df


def build_feature_matrix(
    env_monthly: pd.DataFrame,
    growth_monthly: pd.DataFrame,
    prod_monthly: pd.DataFrame,
) -> pd.DataFrame:
    """환경 + 생육 → 피처 행렬, 생산 → 타겟 변수 병합."""
    if env_monthly.empty:
        logger.error("환경 데이터 없음 — 피처 행렬 구성 불가")
        return pd.DataFrame()

    key = ["farm_id", "year", "month"]
    df = _normalize_keys(env_monthly.copy())

    if not growth_monthly.empty:
        df = df.merge(_normalize_keys(growth_monthly.copy()), on=key, how="left")

    if not prod_monthly.empty:
        pm = _normalize_keys(prod_monthly.copy())
        df = df.merge(pm, on=key, how="left")
        df["yield_kg"]    = df["yield_kg"].fillna(0)
        df["revenue_krw"] = df["revenue_krw"].fillna(0)
    else:
        df["yield_kg"]    = 0.0
        df["revenue_krw"] = 0.0

    # 누적 GDD
    df = df.sort_values(["farm_id", "year", "month"])
    df["gdd_cumsum"] = (
        df.groupby("farm_id")["gdd_monthly"]
        .cumsum()
        .fillna(0)
    ) if "gdd_monthly" in df.columns else 0.0

    # 3개월 이동 평균 (온도, CO2)
    for col in ["temp_internal_mean", "co2_ppm_mean", "humidity_int_mean"]:
        if col in df.columns:
            df[f"{col}_ma3"] = (
                df.groupby("farm_id")[col]
                .transform(lambda s: s.rolling(3, min_periods=1).mean())
            )

    # 생육 성장률 (초장 월간 변화)
    if "growth_초장" in df.columns:
        df["초장_월간_증분"] = (
            df.groupby("farm_id")["growth_초장"]
            .diff()
            .fillna(0)
        )

    # 정규화된 수익 (단위 면적당)
    # area_m2가 없는 경우 기본값 1000m2 사용 (add_cultivation_features 이후 재계산)
    if "revenue_krw" in df.columns:
        area = df.get("area_m2", pd.Series(1000.0, index=df.index)).fillna(1000.0).replace(0, 1000.0)
        df["revenue_per_m2"] = df["revenue_krw"] / area
        df["yield_per_m2"]   = df.get("yield_kg", pd.Series(0.0, index=df.index)) / area

    return df


# ─────────────────────────────────────────────────────────────────────────────
# 4. 모델 학습
# ─────────────────────────────────────────────────────────────────────────────

ENV_FEATURE_COLS = [
    "temp_internal_mean", "temp_internal_std",
    "humidity_int_mean", "humidity_int_std",
    "co2_ppm_mean", "solar_rad_mean",
    "soil_temp_mean", "gdd_monthly", "gdd_cumsum",
    "temp_internal_mean_ma3", "co2_ppm_mean_ma3", "humidity_int_mean_ma3",
]
GROWTH_FEATURE_COLS = [
    "growth_초장", "growth_엽수", "growth_엽장", "growth_엽폭",
    "growth_화방별착과수", "초장_월간_증분",
]
ALL_FEATURE_COLS = ENV_FEATURE_COLS + GROWTH_FEATURE_COLS + [
    "month", "weeks_since_planting",
]


def _get_feature_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in ALL_FEATURE_COLS if c in df.columns]


def train_revenue_model(
    df_train: pd.DataFrame,
    target: str = "revenue_per_m2",
) -> dict:
    """XGBoost + LightGBM 앙상블 매출 예측 모델 학습.

    데이터 부족 시 선형 모델로 자동 폴백.
    결측치는 중앙값으로 대체 (건너뜀 없음).
    """
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.linear_model import Ridge
    from sklearn.metrics import r2_score, mean_absolute_percentage_error

    feature_cols = _get_feature_cols(df_train)
    mask = df_train[target].astype(float) > 0  # 출하 없는 달 제외 (Int64 BooleanArray 우회)
    X_raw = df_train.loc[mask, feature_cols]
    y     = df_train.loc[mask, target].astype(float)

    n_samples = len(X_raw)
    logger.info("  학습 샘플: %d개  피처: %d개", n_samples, len(feature_cols))

    if n_samples < 10:
        logger.warning("  샘플 부족 (%d) — Ridge 폴백", n_samples)
        imputer = SimpleImputer(strategy="median")
        X_imp = imputer.fit_transform(X_raw)
        scaler = StandardScaler()
        X_sc = scaler.fit_transform(X_imp)
        model = Ridge(alpha=10.0)
        model.fit(X_sc, y)
        y_pred = model.predict(X_sc)
        r2   = float(r2_score(y, y_pred))
        mape = float(mean_absolute_percentage_error(y, y_pred) * 100)
        return {
            "type": "ridge_fallback",
            "model": model, "imputer": imputer, "scaler": scaler,
            "feature_cols": feature_cols,
            "train_r2": round(r2, 4), "train_mape": round(mape, 2),
            "n_train": n_samples,
        }

    from sklearn.impute import SimpleImputer
    imputer = SimpleImputer(strategy="median")
    X = imputer.fit_transform(X_raw)

    try:
        import xgboost as xgb
        xgb_model = xgb.XGBRegressor(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            min_child_weight=3, random_state=42,
            verbosity=0,
        )
        xgb_model.fit(X, y)
        y_pred_xgb = xgb_model.predict(X)
        xgb_avail = True
    except ImportError:
        logger.warning("  XGBoost 없음 — Ridge 단독 사용")
        xgb_avail = False

    try:
        import lightgbm as lgb
        lgb_model = lgb.LGBMRegressor(
            n_estimators=300, num_leaves=31, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            min_child_samples=5, random_state=42,
            verbosity=-1,
        )
        lgb_model.fit(X, y)
        y_pred_lgb = lgb_model.predict(X)
        lgb_avail = True
    except ImportError:
        logger.warning("  LightGBM 없음 — XGBoost 단독 사용")
        lgb_avail = False

    if not xgb_avail and not lgb_avail:
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler()
        X_sc = scaler.fit_transform(X)
        model = Ridge(alpha=10.0)
        model.fit(X_sc, y)
        y_pred = model.predict(X_sc)
        r2 = float(r2_score(y, y_pred))
        mape = float(mean_absolute_percentage_error(y, y_pred) * 100)
        return {
            "type": "ridge_fallback",
            "model": model, "scaler": scaler,
            "imputer": imputer, "feature_cols": feature_cols,
            "train_r2": round(r2, 4), "train_mape": round(mape, 2),
            "n_train": n_samples,
        }

    # 앙상블: 평균
    if xgb_avail and lgb_avail:
        y_pred = (y_pred_xgb + y_pred_lgb) / 2.0
        model_type = "xgb_lgb_ensemble"
    elif xgb_avail:
        y_pred = y_pred_xgb
        model_type = "xgb_only"
    else:
        y_pred = y_pred_lgb
        model_type = "lgb_only"

    from sklearn.metrics import r2_score, mean_absolute_percentage_error
    r2   = float(r2_score(y, y_pred))
    mape = float(mean_absolute_percentage_error(y, y_pred) * 100)

    result = {
        "type": model_type,
        "feature_cols": feature_cols,
        "imputer": imputer,
        "train_r2": round(r2, 4),
        "train_mape": round(mape, 2),
        "n_train": n_samples,
    }
    if xgb_avail:
        result["xgb_model"] = xgb_model
    if lgb_avail:
        result["lgb_model"] = lgb_model

    logger.info("  [%s] train R²=%.3f  MAPE=%.1f%%", model_type, r2, mape)
    return result


def predict_revenue(
    model_info: dict,
    X_df: pd.DataFrame,
) -> np.ndarray:
    """매출 예측."""
    feat_cols = model_info["feature_cols"]
    avail = [c for c in feat_cols if c in X_df.columns]
    X_raw = X_df.reindex(columns=feat_cols)
    X = model_info["imputer"].transform(X_raw)

    if model_info["type"] == "ridge_fallback":
        if "scaler" in model_info:
            X = model_info["scaler"].transform(X)
        return model_info["model"].predict(X)

    preds = []
    if "xgb_model" in model_info:
        preds.append(model_info["xgb_model"].predict(X))
    if "lgb_model" in model_info:
        preds.append(model_info["lgb_model"].predict(X))
    return np.mean(preds, axis=0) if preds else np.zeros(len(X))


# ── 비용 모델 ─────────────────────────────────────────────────────────────────

def estimate_cost_per_m2(area_m2: float = 1000.0) -> dict:
    """income_survey.json 기반 딸기 월 경영비 추정."""
    survey_path = ROOT / "api" / "data" / "income_survey.json"
    if survey_path.exists():
        d = json.loads(survey_path.read_text(encoding="utf-8"))
        costs = d.get("딸기", {}).get("cost_per_m2", {})
    else:
        costs = {
            "seed": 800.0, "fertilizer": 180.0, "pesticide": 280.0,
            "utility": 450.0, "labor": 2800.0, "depreciation": 162.0,
            "other": 500.0,
        }
    season_days = 150
    # 월간 비용 = 연간비용 / (season_days / 30)
    months_per_season = season_days / 30.0
    monthly_per_m2 = {k: round(v / months_per_season, 2) for k, v in costs.items()}
    total_monthly_per_m2 = round(sum(monthly_per_m2.values()), 2)
    return {
        "breakdown": monthly_per_m2,
        "total_per_m2_per_month": total_monthly_per_m2,
    }


# ── 소득 최적화 ───────────────────────────────────────────────────────────────

def optimize_income(
    model_info: dict,
    current_env: dict,
    area_m2: float,
    n_months: int = 6,
) -> dict:
    """환경 파라미터 그리드 서치로 소득 최대화 조합 탐색."""
    from itertools import product

    cost_info    = estimate_cost_per_m2(area_m2)
    monthly_cost = cost_info["total_per_m2_per_month"] * area_m2

    # 탐색 그리드
    temp_range  = np.arange(14.0, 24.0, 1.0)
    humid_range = np.arange(55.0, 80.0, 5.0)
    co2_range   = np.arange(600.0, 1400.0, 200.0)

    best = {"income": -1e9}
    results = []

    for temp, humid, co2 in product(temp_range, humid_range, co2_range):
        candidate = {**current_env, "temp_internal_mean": temp,
                     "humidity_int_mean": humid, "co2_ppm_mean": co2}
        cdf = pd.DataFrame([candidate] * n_months)
        cdf["month"] = range(1, n_months + 1)

        rev_per_m2 = predict_revenue(model_info, cdf)
        avg_rev_per_m2 = float(np.mean(rev_per_m2))
        monthly_rev    = avg_rev_per_m2 * area_m2
        monthly_income = monthly_rev - monthly_cost
        total_income   = monthly_income * n_months

        results.append({
            "temp": temp, "humid": humid, "co2": co2,
            "rev_per_m2": round(avg_rev_per_m2, 0),
            "income_total": round(total_income, 0),
        })

        if total_income > best["income"]:
            best = {
                "temp_internal": temp, "humidity_int": humid, "co2_ppm": co2,
                "revenue_per_m2": round(avg_rev_per_m2, 0),
                "monthly_revenue": round(monthly_rev, 0),
                "monthly_cost": round(monthly_cost, 0),
                "monthly_income": round(monthly_rev - monthly_cost, 0),
                "total_income_6m": round(total_income, 0),
                "income": total_income,
            }

    # 상위 5개 조합
    top5 = sorted(results, key=lambda x: x["income_total"], reverse=True)[:5]
    best.pop("income", None)
    return {"best": best, "top5": top5}


# ─────────────────────────────────────────────────────────────────────────────
# 5. 검증
# ─────────────────────────────────────────────────────────────────────────────

def validate_model(
    model_info: dict,
    df_test: pd.DataFrame,
    target: str = "revenue_per_m2",
) -> dict:
    """2022년 테스트셋 검증."""
    from sklearn.metrics import r2_score, mean_absolute_percentage_error, mean_squared_error

    mask = df_test[target].astype(float) > 0
    if int(mask.sum()) < 3:
        logger.warning("  검증 샘플 부족 (%d)", mask.sum())
        return {"n_test": int(mask.sum()), "note": "샘플 부족"}

    X_test = df_test.loc[mask]
    y_true = df_test.loc[mask, target].astype(float).values
    y_pred = predict_revenue(model_info, X_test)

    r2   = float(r2_score(y_true, y_pred))
    mape = float(mean_absolute_percentage_error(y_true, y_pred) * 100)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))

    logger.info("  [검증] R²=%.3f  MAPE=%.1f%%  RMSE=%.0f", r2, mape, rmse)
    return {
        "n_test":    int(mask.sum()),
        "r2":        round(r2, 4),
        "mape_pct":  round(mape, 2),
        "rmse":      round(rmse, 2),
        "y_true_sample": y_true[:5].tolist(),
        "y_pred_sample": [round(float(v), 0) for v in y_pred[:5]],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("딸기 소득최적화 모델 파이프라인 시작")
    logger.info("=" * 60)

    # 1. 데이터 로드
    all_env    = []
    all_growth = []
    all_prod   = []
    cultiv_frames = []

    for year in YEARS:
        logger.info("[%d년] 데이터 로드 중...", year)
        env_df  = load_env(year)
        gro_df  = load_growth(year)
        prod_df = load_production(year)
        cult_df = load_cultivation_info(year)

        if not env_df.empty:
            env_df["year"] = year
            all_env.append(preprocess_env(env_df))
        if not gro_df.empty:
            gro_df["year"] = year
            all_growth.append(gro_df)
        if not prod_df.empty:
            prod_df["year"] = year
            all_prod.append(prod_df)
        if not cult_df.empty:
            cult_df["year"] = year
            cultiv_frames.append(cult_df)

    if not all_env:
        logger.error("환경 데이터 없음 — 파이프라인 중단")
        sys.exit(1)

    logger.info("\n[데이터 현황]")
    logger.info("  환경: %d년분  %d행",
        len(all_env), sum(len(d) for d in all_env))
    logger.info("  생육: %d년분  %d행",
        len(all_growth), sum(len(d) for d in all_growth))
    logger.info("  생산: %d년분  %d행",
        len(all_prod), sum(len(d) for d in all_prod))
    logger.info("  재배정보: %d년분", len(cultiv_frames))

    # 2. 월별 집계
    logger.info("\n[월별 집계]")
    env_all    = pd.concat(all_env, ignore_index=True)
    growth_all = pd.concat(all_growth, ignore_index=True) if all_growth else pd.DataFrame()
    prod_all   = pd.concat(all_prod, ignore_index=True) if all_prod else pd.DataFrame()
    cultiv_all = pd.concat(cultiv_frames, ignore_index=True) if cultiv_frames else pd.DataFrame()

    env_monthly    = aggregate_env_monthly(env_all)
    growth_monthly = aggregate_growth_monthly(growth_all)
    prod_monthly   = aggregate_production_monthly(prod_all)

    if env_monthly.empty:
        logger.error("환경 월집계 실패 — 종료")
        sys.exit(1)

    # 3. 피처 행렬 구성
    logger.info("\n[피처 행렬 구성]")
    df = build_feature_matrix(env_monthly, growth_monthly, prod_monthly)
    df = add_cultivation_features(df, cultiv_all)

    # add_cultivation_features 이후 실제 면적으로 재계산
    if "area_m2" in df.columns and "revenue_krw" in df.columns:
        area = df["area_m2"].fillna(1000.0).replace(0, 1000.0)
        df["revenue_per_m2"] = df["revenue_krw"] / area
        df["yield_per_m2"]   = df.get("yield_kg", pd.Series(0.0, index=df.index)) / area

    logger.info("  최종 피처 행렬: %s", df.shape)
    logger.info("  타겟(revenue_per_m2) 통계:\n%s",
        df.get("revenue_per_m2", pd.Series()).describe().to_string())

    # 4. Train/Test 분리 (2022 = 테스트)
    # 연도 정수 정규화
    df["year"]  = pd.to_numeric(df["year"],  errors="coerce").astype("float").astype("Int64")
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("float").astype("Int64")

    df_train = df[df["year"].fillna(0) < 2022].copy()
    df_test  = df[df["year"].fillna(0) == 2022].copy()
    logger.info("  학습: %d행  테스트: %d행", len(df_train), len(df_test))

    # 5. 모델 학습
    logger.info("\n[모델 학습]")
    target = "revenue_per_m2" if "revenue_per_m2" in df.columns else "yield_per_m2"

    if df_train.empty or target not in df_train.columns:
        logger.error("학습 데이터 또는 타겟 없음 — 종료")
        # 데이터 없어도 파이프라인 구조 저장
        meta = {
            "status": "no_production_data",
            "note": "딸기 출하(판매) 데이터 없음 — 환경/생육 데이터만 수집됨",
            "env_rows": len(env_all),
            "growth_rows": len(growth_all),
            "years_with_env": sorted(env_all["year"].unique().tolist()) if "year" in env_all.columns else [],
        }
        DOCS_DIR.mkdir(exist_ok=True)
        (DOCS_DIR / "strawberry_validation_report.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.warning("부분 결과 저장 완료")
        return

    model_info = train_revenue_model(df_train, target=target)

    # 6. 검증
    logger.info("\n[모델 검증]")
    val_result = validate_model(model_info, df_test, target=target)

    # 7. 소득 최적화 샘플
    logger.info("\n[소득 최적화 샘플 (1000m2, 6개월)]")
    sample_env = {}
    for col in ["temp_internal_mean", "humidity_int_mean", "co2_ppm_mean",
                "solar_rad_mean", "soil_temp_mean", "gdd_monthly"]:
        if col in df.columns:
            sample_env[col] = float(df[col].median())

    opt_result = optimize_income(model_info, sample_env, area_m2=1000.0, n_months=6)
    logger.info("  최적 조건: temp=%.1f°C  humid=%.0f%%  co2=%.0fppm",
        opt_result["best"].get("temp_internal", 0),
        opt_result["best"].get("humidity_int", 0),
        opt_result["best"].get("co2_ppm", 0),
    )
    _inc6 = opt_result["best"].get("total_income_6m", 0)
    logger.info("  최적 6개월 소득: %s원", f"{_inc6:+,.0f}")

    # 8. 비용 분석
    cost_info = estimate_cost_per_m2()

    # 9. 모델 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = {
        "model_info": {
            k: v for k, v in model_info.items()
            if k not in ("xgb_model", "lgb_model", "model", "imputer", "scaler")
        },
    }
    model_save = {k: v for k, v in model_info.items()}
    pkl_path = OUT_DIR / "strawberry_revenue_model.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(model_save, f)
    logger.info("  모델 저장: %s", pkl_path)

    # 10. 메타데이터 + 검증 리포트 저장
    report = {
        "crop": "딸기",
        "pipeline_version": "1.0",
        "data_years": YEARS,
        "train_years": sorted(df_train["year"].unique().tolist()),
        "test_year": 2022,
        "n_train": len(df_train),
        "n_test":  len(df_test),
        "target": target,
        "model_type": model_info.get("type"),
        "feature_count": len(model_info.get("feature_cols", [])),
        "train_metrics": {
            "r2":   model_info.get("train_r2"),
            "mape": model_info.get("train_mape"),
        },
        "test_metrics": val_result,
        "cost_per_m2_monthly": cost_info,
        "optimization_sample": opt_result["best"],
        "top5_env_combinations": opt_result["top5"],
    }

    DOCS_DIR.mkdir(exist_ok=True)
    report_path = DOCS_DIR / "strawberry_validation_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    meta_path = OUT_DIR / "strawberry_pipeline_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info("\n[완료]")
    logger.info("  모델: %s", pkl_path)
    logger.info("  리포트: %s", report_path)
    logger.info("  학습 R2=%.3f  MAPE=%.1f%%",
        model_info.get("train_r2", 0), model_info.get("train_mape", 0))
    if val_result.get("r2") is not None:
        logger.info("  검증 R2=%.3f  MAPE=%.1f%%",
            val_result.get("r2", 0), val_result.get("mape_pct", 0))


if __name__ == "__main__":
    main()
