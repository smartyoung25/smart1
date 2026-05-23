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
    DATA_DIR, YEARS, SUPP_YEARS, get_artifact_dir,
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
    """재배정보 CSV(식부면적)에서 농가면적 맵 구성.

    키 형식: "{year}_{farm_id}"  ← 연도별로 농가번호가 재사용되므로 복합키 필수
    우선순위:
      1. 재배정보_YYYY.CSV의 식부면적 (생산CSV 농가명과 동일 키)
      2. farm_registry.json의 plant_area_m2
      3. 빈 dict (→ AREA_DEFAULTS 기본값 사용)
    """
    result: dict[str, float] = {}

    # ① 재배정보 CSV — 연도+farm_id 복합키로 저장 (연도별 농가번호 중복 방지)
    csv_count = 0
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
                        key = f"{year}_{fid}"
                        result[key] = area
                        csv_count += 1
                except (ValueError, TypeError):
                    pass

    if result:
        logger.info("  면적 맵(재배정보 CSV): %d연도-농가 쌍 (작목=%s)", csv_count, crop_ko)
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
    """재배정보 CSV에서 품종·온실유형·재배일수 메타 {year_farm_id: {...}} 구성."""
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
            key = f"{year}_{fid}"   # 연도+농가 복합키
            entry = meta.setdefault(key, {})
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


# ── Parquet 캐시 ───────────────────────────────────────────────────────────────
_CACHE_DIR = ROOT / ".cache" / "training"


def _cache_path(kind: str, crop_ko: str) -> Path:
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
    """환경 데이터 월별 집계. Parquet 캐시로 반복 실행 고속화."""
    cp = _cache_path("s2_env", crop_ko)
    if use_cache and cp.exists():
        logger.info("  환경 캐시 로드: %s", cp)
        return pd.read_parquet(cp)

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
    result = _norm_keys(agg)
    if use_cache:
        result.to_parquet(cp, index=False)
        logger.info("  환경 캐시 저장: %s", cp)
    return result


def load_growth_monthly(crop_ko: str, growth_cols: list[str], use_cache: bool = True) -> pd.DataFrame:
    """생육 데이터 월별 집계. Parquet 캐시로 반복 실행 고속화."""
    cp = _cache_path("s2_growth", crop_ko)
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
    result = _norm_keys(pd.concat(all_frames, ignore_index=True))
    if use_cache:
        result.to_parquet(cp, index=False)
        logger.info("  생육 캐시 저장: %s", cp)
    return result


def load_production_monthly(crop_ko: str, area_map: dict[str, float],
                             default_area: float, use_cache: bool = True) -> pd.DataFrame:
    """생산 데이터를 월별 집계 + 면적 정규화 → yield_per_m2. Parquet 캐시 지원."""
    cp = _cache_path("s2_prod", crop_ko)
    if use_cache and cp.exists():
        logger.info("  생산 캐시 로드: %s", cp)
        prod_cached = pd.read_parquet(cp)
        # 면적 재적용 (캐시에는 yield_kg만 저장)
        if "yield_kg" in prod_cached.columns and "yield_per_m2" not in prod_cached.columns:
            year_key = prod_cached["year"].astype(str) + "_" + prod_cached["farm_id"].astype(str)
            prod_cached["area_m2"] = year_key.map(area_map)
            missing = prod_cached["area_m2"].isna()
            if missing.any():
                prod_cached.loc[missing, "area_m2"] = prod_cached.loc[missing, "farm_id"].map(area_map)
            prod_cached["area_m2"] = prod_cached["area_m2"].fillna(default_area)
            prod_cached["yield_per_m2"] = prod_cached["yield_kg"] / prod_cached["area_m2"].replace(0, default_area)
            prod_cached["yield_per_m2"] = clip_iqr(prod_cached["yield_per_m2"].clip(lower=0))
        return prod_cached

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

    # 캐시에는 yield_kg 저장 (area_map은 재실행마다 달라질 수 있으므로 제외)
    if use_cache:
        prod.to_parquet(cp, index=False)
        logger.info("  생산 캐시 저장: %s", cp)

    # 면적 적용 → yield_per_m2
    # area_map 키: "{year}_{farm_id}" 복합키 우선, 없으면 단순 farm_id (registry 폴백용)
    year_key = prod["year"].astype(str) + "_" + prod["farm_id"].astype(str)
    prod["area_m2"] = year_key.map(area_map)
    # 복합키 미매칭 시 단순 farm_id 폴백 (registry 경로)
    missing = prod["area_m2"].isna()
    if missing.any():
        prod.loc[missing, "area_m2"] = prod.loc[missing, "farm_id"].map(area_map)
    prod["area_m2"] = prod["area_m2"].fillna(default_area)
    n_matched = int((~(year_key.map(area_map).isna())).sum())
    logger.info("  면적 매칭: %d/%d행 (실측), 나머지 기본값=%.0fm²",
                n_matched, len(prod), default_area)
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

    # 재배정보 메타 피처 (품종, 온실유형, 정식월) — year_farm_id 복합키 조회
    if cultiv_meta:
        _GREENHOUSE_MAP = {"유리": 1, "플라스틱": 2, "비닐": 3}
        def _meta_get(row, field, default=0):
            ykey = f"{int(row['year'])}_{row['farm_id']}"
            val = cultiv_meta.get(ykey, cultiv_meta.get(row["farm_id"], {})).get(field)
            return val if val is not None else default

        df["variety_code"] = df.apply(
            lambda r: hash(_meta_get(r, "variety", "")) % 100, axis=1
        ).astype(int)
        df["greenhouse_code"] = df.apply(
            lambda r: _GREENHOUSE_MAP.get(_meta_get(r, "greenhouse_type", ""), 0), axis=1
        ).astype(int)
        df["plant_month"] = df.apply(
            lambda r: _meta_get(r, "plant_month", 0), axis=1
        ).astype(int)
        n_meta = sum(
            1 for _, r in df.iterrows()
            if f"{int(r['year'])}_{r['farm_id']}" in cultiv_meta
        )
        logger.info("  재배메타 적용: %d/%d행 (품종/온실/정식월)", n_meta, len(df))

    # ── 농가별 target encoding (시계열 안전: 과거 데이터만 사용) ─────────────────
    # 시계열 정렬 후 expanding window로 현재 행 이전 데이터만 참조 → 유출 없음
    df = df.sort_values(["farm_id", "year", "month"]).reset_index(drop=True)
    global_mean = df["yield_per_m2"].astype(float).mean()
    global_std  = df["yield_per_m2"].astype(float).std()

    # 농가별 과거 평균 수확량 (shift(1): 현재 값 제외)
    df["farm_yield_hist_mean"] = (
        df.groupby("farm_id")["yield_per_m2"]
        .transform(lambda x: x.astype(float).expanding().mean().shift(1))
        .fillna(global_mean)
    )
    # 농가별 과거 표준편차 → 변동계수(일관성 지표)
    df["farm_yield_hist_cv"] = (
        df.groupby("farm_id")["yield_per_m2"]
        .transform(lambda x: x.astype(float).expanding().std().shift(1))
        .fillna(global_std)
    ) / (df["farm_yield_hist_mean"] + 1e-9)

    # 농가별 관측 횟수 (학습 안정성 피처)
    df["farm_obs_count"] = (
        df.groupby("farm_id")["yield_per_m2"]
        .transform(lambda x: x.expanding().count().shift(1).fillna(0))
    )

    n_enc = int((df["farm_obs_count"] > 0).sum())
    logger.info("  farm target encoding: %d/%d행 적용 (global_mean=%.3f)",
                n_enc, len(df), global_mean)

    # ── 수확량 시계열 lag 피처 (DSSAT/APSIM 물리모델 기반 전년도 생산성 반영) ──
    # 전년도·전전년도 수확량 lag → 토양 피로도·농가 관리 수준 장기 패턴 포착
    # 시계열 안전: shift(1)로 현재 값 제외 → 데이터 유출 없음
    # 소표본(n<150) → yield lag 비활성화: lag shift 후 imputed 값이 과적합 유발
    _use_yield_lag = len(df) >= 150
    if not _use_yield_lag:
        logger.info("  yield lag 비활성화 (n=%d < 150 — 소표본 과적합 방지)", len(df))
    if _use_yield_lag:
        try:
            _df_lag = df.sort_values(["farm_id", "year", "month"]).copy()
            for _lag_n in [1, 2, 3]:
                _df_lag[f"yield_lag{_lag_n}"] = (
                    _df_lag.groupby("farm_id")["yield_per_m2"]
                    .shift(_lag_n)
                    .fillna(global_mean)
                )
            # 수확량 변화율 (전기 대비)
            _df_lag["yield_chg_rate"] = (
                (_df_lag["yield_lag1"] - _df_lag["yield_lag2"]) /
                (_df_lag["yield_lag2"].clip(lower=0.01))
            ).clip(-1.0, 1.0).fillna(0.0)
            # EWM 수확량 트렌드 (span=3 시즌)
            _df_lag["yield_ewm3"] = (
                _df_lag.groupby("farm_id")["yield_lag1"]
                .transform(lambda s: s.ewm(span=3, adjust=False).mean())
                .fillna(global_mean)
            )
            df = _df_lag
            logger.info("  yield lag 피처 추가: lag1/lag2/lag3/chg_rate/ewm3")
        except Exception as _lag_e:
            logger.debug("  yield lag 피처 생성 실패 (무시): %s", _lag_e)

    logger.info("  Stage2 행렬: %s", df.shape)
    return df


# ── 임계 이벤트 피처 (개화기/착과기 스트레스) ────────────────────────────────

# 작목별 임계 이벤트 기간 및 임계값 정의
# flowering_months : 개화기 (저온에 민감 → 수정 장애)
# fruit_set_months : 착과기 (고온에 민감 → 낙과·품질 저하)
# cold_thresh      : 저온 임계 (℃), 이하이면 개화기 스트레스
# heat_thresh      : 고온 임계 (℃), 이상이면 착과기 스트레스
# dli_scale        : DLI 환산 계수 (W/m²·h → mol/m²·d 근사)
_CRITICAL_EVENT_CFG: dict[str, dict] = {
    "딸기": {
        "flowering_months": [11, 12, 1],
        "fruit_set_months": [1, 2, 3],
        "cold_thresh": 8.0,
        "heat_thresh": 25.0,
        "vpd_opt": (0.6, 1.0),
    },
    "방울토마토": {
        "flowering_months": [3, 4, 5],
        "fruit_set_months": [4, 5, 6],
        "cold_thresh": 12.0,
        "heat_thresh": 32.0,
        "vpd_opt": (0.8, 1.4),
    },
    "완숙토마토": {
        "flowering_months": [3, 4, 5],
        "fruit_set_months": [4, 5, 6],
        "cold_thresh": 12.0,
        "heat_thresh": 32.0,
        "vpd_opt": (0.8, 1.4),
    },
    "참외": {
        "flowering_months": [4, 5],
        "fruit_set_months": [5, 6],
        "cold_thresh": 14.0,
        "heat_thresh": 35.0,
        "vpd_opt": (0.7, 1.2),
    },
    "파프리카": {
        "flowering_months": [3, 4, 5],
        "fruit_set_months": [4, 5, 6],
        "cold_thresh": 12.0,
        "heat_thresh": 30.0,
        "vpd_opt": (0.8, 1.2),
    },
    "오이": {
        "flowering_months": [4, 5, 6],
        "fruit_set_months": [5, 6, 7],
        "cold_thresh": 12.0,
        "heat_thresh": 33.0,
        "vpd_opt": (0.7, 1.3),
    },
}


def _calc_vpd_series(temp: pd.Series, humi: pd.Series) -> pd.Series:
    """월 평균 온도·습도로 VPD(kPa) 계산."""
    import numpy as np
    svp = 0.6108 * np.exp(17.27 * temp / (temp + 237.3))
    return (svp * (1.0 - humi.clip(1, 100) / 100.0)).clip(lower=0)


def _add_critical_event_features(
    env_monthly: pd.DataFrame,
    prod_ann: pd.DataFrame,
    crop_ko: str,
) -> pd.DataFrame:
    """임계 이벤트 피처를 prod_ann에 추가한다.

    월 평균값을 기반으로 작목별 핵심 시기의 스트레스를 정량화:
      - flower_cold_months : 개화기 중 저온 임계 이하 월 수
      - flower_temp_mean   : 개화기 평균 온도
      - fruit_heat_months  : 착과기 중 고온 임계 이상 월 수
      - fruit_temp_mean    : 착과기 평균 온도
      - dli_annual         : 연간 DLI 추정 (일사량 기반)
      - vpd_out_months     : VPD 최적 범위 이탈 월 수
      - vpd_flower_mean    : 개화기 평균 VPD
    """
    cfg = _CRITICAL_EVENT_CFG.get(crop_ko)
    if cfg is None or env_monthly.empty:
        return prod_ann

    key = ["farm_id", "year"]
    em  = env_monthly.copy()
    em  = _norm_keys(em)

    has_temp  = "temp_internal" in em.columns
    has_humi  = "humidity_int"  in em.columns
    has_solar = "solar_rad"     in em.columns

    flower_m   = cfg["flowering_months"]
    fruit_m    = cfg["fruit_set_months"]
    cold_thr   = cfg["cold_thresh"]
    heat_thr   = cfg["heat_thresh"]
    vpd_lo, vpd_hi = cfg["vpd_opt"]

    # ── VPD 시리즈 ───────────────────────────────────────────────────────────
    if has_temp and has_humi:
        em["vpd"] = _calc_vpd_series(em["temp_internal"], em["humidity_int"])

    feats: list[pd.DataFrame] = []

    # ── 개화기 피처 ──────────────────────────────────────────────────────────
    flower_df = em[em["month"].isin(flower_m)]
    if has_temp and not flower_df.empty:
        flower_agg = (
            flower_df.groupby(key)
            .agg(
                flower_temp_mean=("temp_internal", "mean"),
                flower_cold_months=("temp_internal",
                                    lambda x: (x < cold_thr).sum()),
            )
            .reset_index()
        )
        feats.append(flower_agg)

    if has_temp and has_humi and not flower_df.empty and "vpd" in flower_df.columns:
        vpd_flower_agg = (
            flower_df.groupby(key)
            .agg(vpd_flower_mean=("vpd", "mean"))
            .reset_index()
        )
        feats.append(vpd_flower_agg)

    # ── 착과기 피처 ──────────────────────────────────────────────────────────
    fruit_df = em[em["month"].isin(fruit_m)]
    if has_temp and not fruit_df.empty:
        fruit_agg = (
            fruit_df.groupby(key)
            .agg(
                fruit_temp_mean=("temp_internal", "mean"),
                fruit_heat_months=("temp_internal",
                                   lambda x: (x > heat_thr).sum()),
            )
            .reset_index()
        )
        feats.append(fruit_agg)

    # ── DLI 연간 누적 ────────────────────────────────────────────────────────
    # DLI(mol/m²/d) ≈ 일사량(W/m²) × 3600초 × 일조시간(≈8h) × 10^-6 × (1/0.217)
    # 월 단위 근사: DLI_monthly ≈ solar_rad_mean × 0.0115 (W/m² → mol/m²/d)
    if has_solar and not em.empty:
        dli_agg = (
            em.groupby(key)
            .agg(dli_annual=("solar_rad", lambda x: (x * 0.0115).sum()))
            .reset_index()
        )
        feats.append(dli_agg)

    # ── VPD 이탈 월 수 (연간) ────────────────────────────────────────────────
    if "vpd" in em.columns:
        vpd_agg = (
            em.groupby(key)
            .agg(
                vpd_out_months=("vpd",
                                lambda x: ((x < vpd_lo) | (x > vpd_hi)).sum()),
                vpd_annual_mean=("vpd", "mean"),
            )
            .reset_index()
        )
        feats.append(vpd_agg)

    # ── prod_ann에 병합 ──────────────────────────────────────────────────────
    result = prod_ann.copy()
    for feat_df in feats:
        result = result.merge(feat_df, on=key, how="left")

    # 결측(해당 월 데이터 없음) → 0 채움
    new_cols = [c for c in result.columns if c not in prod_ann.columns]
    result[new_cols] = result[new_cols].fillna(0)

    if new_cols:
        logger.info(
            "  임계 이벤트 피처 %d개 추가 (%s): %s",
            len(new_cols), crop_ko, new_cols,
        )

    return result


# ── 논문 기반 생리학적 피처 (Phase 2) ────────────────────────────────────────

# 작목별 최적 환경 범위 (PeerJ 2023 Korean farm study + RDA 기준)
_OPT_TEMP_RANGE: dict[str, tuple[float, float]] = {
    "딸기":       (15.0, 20.0),   # 과실 발달기 최적
    "방울토마토": (18.0, 25.0),
    "완숙토마토": (18.0, 25.0),
    "참외":       (22.0, 30.0),
    "파프리카":   (18.0, 26.0),
}
_OPT_RH_RANGE: dict[str, tuple[float, float]] = {
    "딸기":       (55.0, 75.0),   # 과습 → 회색곰팡이, 건조 → 수정 불량
    "방울토마토": (60.0, 80.0),
    "완숙토마토": (60.0, 80.0),
    "참외":       (60.0, 75.0),
    "파프리카":   (60.0, 80.0),
}
# TOMSIM (Heuvelink) 화방 출현 간격 (℃·day / 화방)
_TRUSS_INTERVAL: dict[str, float] = {
    "방울토마토": 8.5,
    "완숙토마토": 7.0,
}
_KR_LAT_RAD = np.radians(36.5)   # 한국 평균 위도 36.5°N


def _daylength_hours(month: float) -> float:
    """월 중순 기준 천문 일장 계산 (한국 위도 36.5°N).

    Cooper (1969) 근사식 사용:
      δ = 23.45 × sin(360/365 × (doy − 81))
      ω = arccos(−tan(φ) × tan(δ))
      N = 2ω/15  (시간)
    """
    if not (1 <= month <= 12):
        return 12.0
    doy = int(month) * 30 - 15
    decl = np.radians(23.45) * np.sin(np.radians(360.0 / 365.0 * (doy - 81)))
    cos_ha = -np.tan(_KR_LAT_RAD) * np.tan(decl)
    cos_ha = float(np.clip(cos_ha, -1.0, 1.0))
    return 2.0 * np.degrees(np.arccos(cos_ha)) / 15.0


def _add_science_features(
    env_monthly: pd.DataFrame,
    prod_ann: pd.DataFrame,
    config: "CropConfig",
) -> pd.DataFrame:
    """논문 기반 생리학적 피처를 prod_ann에 추가한다.

    추가 피처:
      pct_time_optimal_temp  — 월평균 온도가 작목별 최적 범위 내 비율 (PeerJ 2023)
      pct_time_optimal_rh    — 습도 최적 범위 내 비율
      co2_mm_response        — CO₂ Michaelis-Menten 포화 응답 (Km=250 ppm, C3 식물)
      [딸기 전용]
        daylength_plant_month  — 이식월 일장(h), 천문학 계산 (센서 불필요)
        sd_induction_index     — 단일 유도 강도 (14.5h − 일장).clip(0) : 높을수록 화아분화↑
        pct_time_optimal_temp_straw — 딸기 전용 최적 범위 체류 비율
      [토마토 전용]
        cumulative_par_mj      — 시즌 누적 차단 PAR (mol→MJ 환산, TOMSIM 기반)
        truss_count_estimate   — 화방 수 추정 (GDD / TOMSIM 화방 간격)
      [파프리카 전용]
        n_harvest_months_cv    — 월별 수확 편차계수 (컨베이어 벨트 진동 프록시)
    """
    result = prod_ann.copy()
    key    = ["farm_id", "year"]
    crop   = config.crop_ko

    # ── 1. 최적 온도 체류 비율 ─────────────────────────────────────────────────
    opt_tl, opt_th = _OPT_TEMP_RANGE.get(crop, (18.0, 25.0))
    if not env_monthly.empty and "temp_internal" in env_monthly.columns:
        _em = env_monthly.copy()
        _em = _norm_keys(_em)
        _em["_t_ok"] = _em["temp_internal"].between(opt_tl, opt_th).astype(float)
        _t_agg = (
            _em.groupby(key)["_t_ok"].mean().reset_index()
            .rename(columns={"_t_ok": "pct_time_optimal_temp"})
        )
        result = result.merge(_t_agg, on=key, how="left")
        result["pct_time_optimal_temp"] = result["pct_time_optimal_temp"].fillna(0.5)

        # 과열 / 저온 스트레스 시간 비율 (PeerJ: 범위 이탈이 수확 감소 유발)
        _em["_t_cold"] = (_em["temp_internal"] < opt_tl).astype(float)
        _em["_t_heat"] = (_em["temp_internal"] > opt_th).astype(float)
        for _col, _new in [("_t_cold", "pct_time_cold_stress"),
                           ("_t_heat", "pct_time_heat_stress")]:
            _agg = (_em.groupby(key)[_col].mean().reset_index()
                    .rename(columns={_col: _new}))
            result = result.merge(_agg, on=key, how="left")
            result[_new] = result[_new].fillna(0.0)
        logger.info("  [과학 피처] pct_time_optimal_temp / cold_stress / heat_stress 추가")

    # ── 2. 최적 습도 체류 비율 ─────────────────────────────────────────────────
    opt_rl, opt_rh = _OPT_RH_RANGE.get(crop, (60.0, 80.0))
    if not env_monthly.empty and "humidity_int" in env_monthly.columns:
        _em2 = env_monthly.copy()
        _em2 = _norm_keys(_em2)
        _em2["_rh_ok"] = _em2["humidity_int"].between(opt_rl, opt_rh).astype(float)
        _rh_agg = (
            _em2.groupby(key)["_rh_ok"].mean().reset_index()
            .rename(columns={"_rh_ok": "pct_time_optimal_rh"})
        )
        result = result.merge(_rh_agg, on=key, how="left")
        result["pct_time_optimal_rh"] = result["pct_time_optimal_rh"].fillna(0.5)
        logger.info("  [과학 피처] pct_time_optimal_rh 추가")

    # ── 3. CO₂ Michaelis-Menten 포화 응답 ─────────────────────────────────────
    # A_net = Amax × [CO₂] / (Km + [CO₂]),  Km ≈ 250 ppm (C3 식물)
    # co2_mm_response ∈ [0.28(100ppm)~0.80(1000ppm)]: 비선형 수익 체감 포착
    if "co2_ppm_mean" in result.columns:
        _co2 = result["co2_ppm_mean"].fillna(400.0).clip(lower=50.0)
        result["co2_mm_response"] = _co2 / (_co2 + 250.0)
        logger.info("  [과학 피처] CO₂ Michaelis-Menten 응답 (Km=250 ppm) 추가")

    # ── 4. 딸기 전용: 일장 + 단일 유도 지수 ──────────────────────────────────
    if crop == "딸기" and "plant_month" in result.columns:
        _pm = result["plant_month"].replace(0, np.nan)
        result["daylength_plant_month"] = _pm.apply(
            lambda m: _daylength_hours(m) if pd.notna(m) else _daylength_hours(9.0)
        )
        # 단일 유도 강도: 14.5h 미달 시 화아분화 강하게 유도됨
        # Seolhyang(설향) 임계 일장 ≈ 14.5h (IntechOpen review)
        result["sd_induction_index"] = (
            14.5 - result["daylength_plant_month"]
        ).clip(lower=0.0)
        # 이식 시기별 적산 단일 일수 추정 (이식 후 60일, 하루 단위 근사)
        # daylength < 14.5h 인 월 수 × 30 / 60 (정규화)
        if not env_monthly.empty:
            _em_s = env_monthly.copy()
            _em_s = _norm_keys(_em_s)
            # 이식 후 시즌 초반 (plant_month + 0~2개월) 저일장 월 비율
            def _sd_months(row):
                pm = row.get("plant_month", 0)
                if not pm or pd.isna(pm):
                    pm = 9
                pm = int(pm)
                # 이식 후 3개월 체크
                check_months = [(pm + i - 1) % 12 + 1 for i in range(3)]
                return sum(1 for m in check_months if _daylength_hours(m) < 14.5) / 3.0
            if "plant_month" in result.columns:
                result["sd_month_fraction"] = result.apply(_sd_months, axis=1)
        logger.info("  [딸기 전용·과학 피처] daylength + sd_induction_index + sd_month_fraction 추가")

    # ── 5. 토마토 전용: 누적 PAR + 화방 수 추정 (TOMSIM) ─────────────────────
    if crop in ("방울토마토", "완숙토마토"):
        _truss_iv = _TRUSS_INTERVAL.get(crop, 7.5)

        # 누적 차단 PAR: DLI(mol/m²/d) × 0.217MJ/mol × 30.4d/월 × 재배월수
        # TOMSIM RUE=2.5 g DM/MJ; cumulative_par_mj → 이론적 건물 생산량 기준값
        if "dli_annual" in result.columns:
            _n_m = result["n_harvest_months"].clip(lower=1)
            result["cumulative_par_mj"] = (
                result["dli_annual"] * 0.217 * _n_m * 30.4
            ).clip(lower=0)
            logger.info("  [토마토 전용·과학 피처] cumulative_par_mj 추가")

        # 화방 수 추정: GDD_시즌 / 화방 출현 간격
        if "gdd_annual" in result.columns:
            result["truss_count_estimate"] = (
                result["gdd_annual"] / _truss_iv
            ).clip(lower=0, upper=300)
            logger.info("  [토마토 전용·과학 피처] truss_count_estimate (GDD/%.1f) 추가",
                        _truss_iv)

        # PAR 단위 예상 수확량 대비 상대 생산성 (관리 품질 프록시)
        # 주의: harvest_index_ratio는 yield_per_m2를 분자로 사용하므로
        #       farm target encoding 이후 적용 → leakage 없음 (farm hist로 정규화)
        if "cumulative_par_mj" in result.columns and "farm_yield_hist_mean" in result.columns:
            _expected_rue = (result["cumulative_par_mj"] * 2.5 / 1000.0).clip(lower=0.1)
            result["par_yield_efficiency"] = (
                result["farm_yield_hist_mean"] / _expected_rue
            ).clip(0.05, 10.0)
            logger.info("  [토마토 전용·과학 피처] par_yield_efficiency (farm hist / RUE 기대값) 추가")

    # ── 6. 파프리카 전용: 컨베이어 벨트 진동 프록시 ───────────────────────────
    # 수확량 진동이 심한 농가 = 착과 부하 관리 미흡 → 예측 어려움 표시
    if crop == "파프리카" and "n_harvest_months" in result.columns:
        # 농가별 역대 n_harvest_months 변동계수 (expanding, shift 1)
        result_sorted = result.sort_values(key)
        _nhm_cv = (
            result_sorted.groupby("farm_id")["n_harvest_months"]
            .transform(lambda x:
                (x.astype(float).expanding().std().shift(1)
                 / x.astype(float).expanding().mean().shift(1).clip(lower=1e-9))
                .fillna(0.0)
            )
        ).clip(0, 3)
        result["harvest_month_cv"] = _nhm_cv.values
        logger.info("  [파프리카 전용·과학 피처] harvest_month_cv (컨베이어 벨트 진동 프록시) 추가")

    return result


# ── 연간(시즌) 집계 행렬 ─────────────────────────────────────────────────────

def build_stage2_matrix_annual(
    env_monthly: pd.DataFrame,
    growth_monthly: pd.DataFrame,
    prod_monthly: pd.DataFrame,
    config: CropConfig,
    cultiv_meta: Optional[dict] = None,
) -> pd.DataFrame:
    """월별 데이터를 연간(작기) 단위로 집계 → 출하 타이밍 노이즈 제거.

    타겟: farm_id + year 단위 연간 총수확량 / 면적 = yield_per_m2_annual
    피처: 연간 환경 평균/분산, 생육 평균/분산, 재배메타, farm target encoding
    """
    if prod_monthly.empty:
        return pd.DataFrame()

    key_annual = ["farm_id", "year"]

    # ① 생산: 연간 총 수확량
    prod_ann = (
        prod_monthly.groupby(key_annual)
        .agg(
            yield_kg=("yield_kg", "sum"),
            area_m2=("area_m2", "first"),
            n_harvest_months=("yield_kg", lambda x: (x > 0).sum()),
        )
        .reset_index()
    )
    prod_ann["yield_per_m2"] = (
        prod_ann["yield_kg"] / prod_ann["area_m2"].replace(0, config.area_default_m2)
    ).clip(lower=0)
    prod_ann["yield_per_m2"] = clip_iqr(prod_ann["yield_per_m2"])

    # ② 환경: 연간 평균 + 분산 + 계절 편차
    if not env_monthly.empty:
        env_vars = [c for c in env_monthly.columns if c not in ["farm_id", "year", "month"]]
        agg_dict: dict = {}
        for col in env_vars:
            agg_dict[f"{col}_mean"] = (col, "mean")
            agg_dict[f"{col}_std"]  = (col, "std")
        env_ann = env_monthly.groupby(key_annual).agg(**agg_dict).reset_index()
        env_ann = _norm_keys(env_ann)
        prod_ann = prod_ann.merge(env_ann, on=key_annual, how="left")

    # ③ 생육: 연간 평균 + 분산
    if not growth_monthly.empty:
        g_vars = [c for c in growth_monthly.columns
                  if c not in ["farm_id", "year", "month"]
                  and growth_monthly[c].dtype in [np.float64, np.int64, float, int]]
        agg_dict = {}
        for col in g_vars:
            agg_dict[f"{col}_mean"] = (col, "mean")
            agg_dict[f"{col}_std"]  = (col, "std")
        grw_ann = growth_monthly.groupby(key_annual).agg(**agg_dict).reset_index()
        grw_ann = _norm_keys(grw_ann)
        prod_ann = prod_ann.merge(grw_ann, on=key_annual, how="left")

    # ④ 계절 피처 (GDD 연간 누적)
    if "temp_internal_mean" in prod_ann.columns:
        prod_ann["gdd_annual"] = (
            prod_ann["temp_internal_mean"] - config.t_base
        ).clip(lower=0) * 365

    # ④-et ET₀ / ETc 기반 피처 (Hargreaves-Samani 간이식, 온실 내부 온도 기반)
    # 온실 내부 환경으로 ET₀ 근사: 외기 대신 내부 max/min 추정 (Tmax = avg+3, Tmin = avg-3)
    # solar_rad_mean (W/m²) → MJ/m²/day: ÷ 1000 × 3600 × 일조 9h ≈ × 0.0324
    _has_et_inputs = (
        "temp_internal_mean" in prod_ann.columns
        and "solar_rad_mean" in prod_ann.columns
    )
    if _has_et_inputs:
        _t_mean = prod_ann["temp_internal_mean"].fillna(20.0)
        _t_max  = _t_mean + 3.0
        _t_min  = _t_mean - 3.0
        _sol_wm2 = prod_ann["solar_rad_mean"].fillna(150.0)
        _sol_mj  = (_sol_wm2 * 0.0324).clip(lower=0.5)   # W/m² → MJ/m²/day
        _td      = (_t_max - _t_min).clip(lower=0.0)
        _Ra      = (_sol_mj / 0.75).clip(lower=1.0)
        prod_ann["et0_annual_mean"] = (
            0.0023 * (_t_mean + 17.8) * (_td ** 0.5) * _Ra
        ).clip(lower=0.0).round(3)
        # ETc = ET₀ × Kc(mid): 시즌 평균 기준
        _kc_mid = config.kc_stages.get("mid", 1.0)
        prod_ann["etc_annual_mean"] = (
            prod_ann["et0_annual_mean"] * _kc_mid
        ).round(3)
        # ET demand ratio: 실제 공급량 proxy (CO₂ 농도 상관 — 기공 저항)
        # etc_ratio = etc / (solar_rad × 0.0015) → 증산 포화도 지표
        _et_demand = (_sol_wm2 * 0.0015).clip(lower=0.1)
        prod_ann["et_demand_ratio"] = (
            prod_ann["etc_annual_mean"] / _et_demand
        ).clip(0.1, 10.0)
        logger.info(
            "  [ET₀ 피처] et0_annual_mean / etc_annual_mean / et_demand_ratio 추가 "
            "(Kc_mid=%.2f, mean ET₀=%.2f mm/day)",
            _kc_mid, prod_ann["et0_annual_mean"].mean(),
        )

    # ④-b 임계 이벤트 피처 (개화기 저온 · 착과기 고온 · DLI · VPD 이탈)
    prod_ann = _add_critical_event_features(
        env_monthly, prod_ann, config.crop_ko
    )

    # ⑤ 재배메타 (연간 키: year_farm_id)
    if cultiv_meta:
        _GREENHOUSE_MAP = {"유리": 1, "플라스틱": 2, "비닐": 3}
        def _meta_get_ann(row, field, default=0):
            ykey = f"{int(row['year'])}_{row['farm_id']}"
            val = cultiv_meta.get(ykey, cultiv_meta.get(row["farm_id"], {})).get(field)
            return val if val is not None else default

        # 품종 raw 텍스트 수집
        prod_ann["_variety_raw"] = prod_ann.apply(
            lambda r: _meta_get_ann(r, "variety", ""), axis=1
        )
        prod_ann["greenhouse_code"] = prod_ann.apply(
            lambda r: _GREENHOUSE_MAP.get(_meta_get_ann(r, "greenhouse_type", ""), 0), axis=1
        )
        prod_ann["plant_month"] = prod_ann.apply(
            lambda r: _meta_get_ann(r, "plant_month", 0), axis=1
        )

        # 품종 평균 yield 인코딩 — LOYO 누수 방지용 시계열 안전 expanding mean
        # transform("mean") 은 test_year 데이터 포함 → LOYO 환경에서 leakage 발생.
        # 대신 각 row 이전 데이터만 사용하는 expanding mean + shift(1) 적용.
        _global_mean_variety = prod_ann["yield_per_m2"].astype(float).mean()
        prod_ann = prod_ann.sort_values(key_annual).reset_index(drop=True)
        # 품종별 expanding mean (sort 이미 완료, groupby + shift)
        prod_ann["variety_yield_mean"] = (
            prod_ann.groupby("_variety_raw")["yield_per_m2"]
            .transform(lambda x: x.astype(float).expanding().mean().shift(1))
            .fillna(_global_mean_variety)
        )
        # 품종 순위: expanding mean 기반 (현재 행 이전 데이터만)
        # 단순화: expanding mean 값 자체를 피처로 사용 (순위 필드는 leakage 위험 → 제거)
        prod_ann.drop(columns=["_variety_raw"], inplace=True)

        # plant_month 사인/코사인 (순환 특성 보존: 12월~1월 연속성)
        pm = prod_ann["plant_month"].astype(float).replace(0, np.nan)
        prod_ann["plant_month_sin"] = np.sin(2 * np.pi * pm / 12).fillna(0)
        prod_ann["plant_month_cos"] = np.cos(2 * np.pi * pm / 12).fillna(0)

    # ⑥ 면적 피처 (규모 효과: 대규모 농장은 집약도↑ or ↓)
    prod_ann["log_area_m2"] = np.log1p(prod_ann["area_m2"].astype(float))

    # ⑥-b 연도 트렌드 (스마트팜 기술 개선 + 데이터 수집 완성도 변화)
    _year_min, _year_max = int(prod_ann["year"].min()), int(prod_ann["year"].max())
    _year_range = max(_year_max - _year_min, 1)
    prod_ann["year_norm"] = (prod_ann["year"].astype(int) - _year_min) / _year_range

    # ⑦ Farm target encoding (시계열 안전 — expanding mean with shift)
    prod_ann = prod_ann.sort_values(key_annual).reset_index(drop=True)
    global_mean = prod_ann["yield_per_m2"].astype(float).mean()
    global_std  = prod_ann["yield_per_m2"].astype(float).std()

    prod_ann["farm_yield_hist_mean"] = (
        prod_ann.groupby("farm_id")["yield_per_m2"]
        .transform(lambda x: x.astype(float).expanding().mean().shift(1))
        .fillna(global_mean)
    )
    prod_ann["farm_yield_hist_cv"] = (
        prod_ann.groupby("farm_id")["yield_per_m2"]
        .transform(lambda x: x.astype(float).expanding().std().shift(1))
        .fillna(global_std)
    ) / (prod_ann["farm_yield_hist_mean"] + 1e-9)
    prod_ann["farm_obs_count"] = (
        prod_ann.groupby("farm_id")["yield_per_m2"]
        .transform(lambda x: x.expanding().count().shift(1).fillna(0))
    )

    # ④-c 딸기 전용 피처: 저온적산(냉장시간 프록시) + 주야간 온도진폭
    # 외기온(temp_external) 우선 사용 — 온실 내부온도는 난방으로 7℃ 이하가 거의 없어
    # chill_months≈0이 되므로 예측력 없음. 설향 품종 임계 8℃ 기준 (Fennell 2004).
    _has_ext_col = "temp_external" in env_monthly.columns if not env_monthly.empty else False
    _has_int_col = "temp_internal" in env_monthly.columns if not env_monthly.empty else False
    _has_temp_col = _has_ext_col or _has_int_col
    if config.crop_ko == "딸기" and _has_temp_col and not env_monthly.empty:
        em_straw = env_monthly.copy()
        em_straw = _norm_keys(em_straw)
        # 냉각 시간 proxy: 외기온(우선) 또는 내부온도 기준
        _chill_t_col = "temp_external" if _has_ext_col else "temp_internal"
        _chill_thresh = 8.0 if _has_ext_col else 7.0  # 외기온은 8℃, 내부는 7℃ 임계

        # 주요 냉각 기간(10~12월) 평균 외기온 — 화아분화 유도 강도
        _chill_season_months = [10, 11, 12]
        em_chill = em_straw[em_straw["month"].isin(_chill_season_months)] if "month" in em_straw.columns else em_straw

        _chill_agg = (
            em_chill.groupby(["farm_id", "year"])
            .agg(chill_months=(
                _chill_t_col,
                lambda x: (x < _chill_thresh).sum()
            ))
            .reset_index()
        )
        prod_ann = prod_ann.merge(_chill_agg, on=["farm_id", "year"], how="left")
        prod_ann["chill_months"] = prod_ann["chill_months"].fillna(0)

        # 냉각 기간 평균 외기온 — 낮을수록 chill 강도 높음
        if _has_ext_col:
            _ext_temp_agg = (
                em_chill.groupby(["farm_id", "year"])
                .agg(chill_period_ext_temp_mean=(
                    "temp_external", "mean"
                ))
                .reset_index()
            )
            prod_ann = prod_ann.merge(_ext_temp_agg, on=["farm_id", "year"], how="left")
            prod_ann["chill_period_ext_temp_mean"] = prod_ann["chill_period_ext_temp_mean"].fillna(10.0)
            # 연속 chill_unit proxy: 8℃ 이하 누적 적산 (℃·일)
            # chill_degree_days = max(0, thresh - T_mean) × days_in_month_fraction
            prod_ann["chill_degree_days"] = (
                _chill_thresh - prod_ann["chill_period_ext_temp_mean"]
            ).clip(lower=0) * 3.0  # ×3 (3 냉각 개월)

        # 온도 계절 표준편차 (서늘→따뜻 계절성 강도)
        _temp_std_agg = (
            em_straw.groupby(["farm_id", "year"])
            .agg(temp_internal_season_std=("temp_internal" if _has_int_col else _chill_t_col, "std"))
            .reset_index()
        )
        prod_ann = prod_ann.merge(_temp_std_agg, on=["farm_id", "year"], how="left")
        prod_ann["temp_internal_season_std"] = prod_ann["temp_internal_season_std"].fillna(0)

        logger.info("  [딸기 전용] chill_months(%s기준) + chill_degree_days + temp_season_std 추가",
                    _chill_t_col)

    # ④-e 논문 기반 생리학적 피처 (과학 피처 Phase 2)
    prod_ann = _add_science_features(env_monthly, prod_ann, config)

    # ⑦-b 상대 수확량 타겟 (yield_ratio): farm identity 제거
    # yield_ratio = 올해 수확량 / 농가 역대 평균 수확량
    # → 모델이 "이 농가는 원래 많이 수확" 대신 "이 환경 조건 → 평년比 몇%?" 를 학습
    # farm_yield_hist_mean(expanding, shift 1)을 분모로 사용 (누수 없음)
    _global_mean_for_ratio = prod_ann["yield_per_m2"].astype(float).mean()
    prod_ann["yield_ratio"] = (
        prod_ann["yield_per_m2"].astype(float)
        / (prod_ann["farm_yield_hist_mean"].clip(lower=0.01))
    ).clip(0.1, 5.0)
    # 첫 관측(farm_yield_hist_mean=global_mean) 행은 ratio=1에 수렴 → OK
    _ratio_nan_mask = (prod_ann["farm_obs_count"] == 0)
    prod_ann.loc[_ratio_nan_mask, "yield_ratio"] = 1.0   # 이력 없는 첫 행 → 1.0

    logger.info("  상대 수확량 타겟 yield_ratio 추가 (중앙값=%.3f)",
                prod_ann["yield_ratio"].median())

    # ⑦-b2 잔차 타겟 (yield_residual): farm baseline 제거 — 환경 편차 → 수확 편차 학습
    # yield_residual = yield_per_m2 - farm_yield_hist_mean  (expanding mean, shift 1 → 누수 없음)
    prod_ann["yield_residual"] = (
        prod_ann["yield_per_m2"].astype(float) - prod_ann["farm_yield_hist_mean"]
    )
    logger.info("  잔차 타겟 yield_residual 추가 (중앙값=%.3f, std=%.3f)",
                prod_ann["yield_residual"].median(),
                prod_ann["yield_residual"].std())

    # ⑦-b 농가 상대 환경 편차 피처 (within-farm z-score)
    # "올해 이 농가의 온도가 이 농가의 역대 평균 대비 얼마나 달랐는가?"
    # → farm_yield_hist_mean은 농가 정체성(farm identity)을 포착하지만
    #   환경 편차 피처는 연도별 변동(within-farm variation)을 포착 → 수확량 변동 예측력↑
    _env_ann_cols = [c for c in prod_ann.columns
                     if c.endswith("_mean") and c not in {"yield_per_m2"}
                     and pd.api.types.is_numeric_dtype(prod_ann[c])]
    _dev_added: list[str] = []
    for _ec in _env_ann_cols[:10]:   # 상위 10개 (과적합 방지)
        _farm_h_mean = (
            prod_ann.groupby("farm_id")[_ec]
            .transform(lambda x: x.astype(float).expanding().mean().shift(1))
        )
        _farm_h_std = (
            prod_ann.groupby("farm_id")[_ec]
            .transform(lambda x: x.astype(float).expanding().std().shift(1))
        )
        _dev_col = f"{_ec}_farm_dev"
        prod_ann[_dev_col] = (
            (prod_ann[_ec] - _farm_h_mean) / (_farm_h_std.clip(lower=1e-9))
        ).fillna(0).clip(-5, 5)  # 극값 클리핑
        _dev_added.append(_dev_col)
    if _dev_added:
        logger.info("  농가 상대 환경편차 피처 %d개 추가: %s",
                    len(_dev_added), _dev_added[:3])

    # ⑦-c 광합성 핵심 상호작용 피처
    # 온도×CO2 시너지, DLI×온도 (광량과 온도의 상호 의존적 영향)
    if "temp_internal_mean" in prod_ann.columns and "co2_ppm_mean" in prod_ann.columns:
        prod_ann["temp_co2_interact"] = (
            prod_ann["temp_internal_mean"] * prod_ann["co2_ppm_mean"] / 10000.0
        )
        logger.info("  상호작용 피처 추가: temp_co2_interact")
    if "dli_annual" in prod_ann.columns and "temp_internal_mean" in prod_ann.columns:
        prod_ann["dli_temp_interact"] = (
            prod_ann["dli_annual"] * prod_ann["temp_internal_mean"] / 100.0
        )
        logger.info("  상호작용 피처 추가: dli_temp_interact")
    if "flower_cold_months" in prod_ann.columns and "fruit_heat_months" in prod_ann.columns:
        prod_ann["stress_combined"] = (
            prod_ann["flower_cold_months"] + prod_ann["fruit_heat_months"]
        )
        logger.info("  상호작용 피처 추가: stress_combined")

    # ⑧ 농가 고정효과 proxy — leakage 제거 버전
    # farm_quality는 farm_yield_hist_mean(expanding mean, shift(1))과 동일하므로 제거.
    # 전체 기간 transform("mean")은 테스트 연도 데이터를 포함해 유출됨 → 삭제.

    logger.info("  Stage2 연간 행렬: %s (연평균 yield=%.3f kg/m²)",
                prod_ann.shape, prod_ann["yield_per_m2"].mean())
    return prod_ann


# ── SHAP 피처 선택 ────────────────────────────────────────────────────────────

def select_top_features(model, X: np.ndarray, feature_names: list[str],
                         top_n: int = 15, n_samples: int = 9999) -> list[str]:
    """피처 선택: SHAP → 컬럼 순 폴백.

    소샘플(n<250) 에서는 top_n을 10으로 자동 제한하여 과적합 방지.
    피처 수 > 샘플 수 × 0.2 이면 경고 후 축소.
    """
    # 소샘플 자동 제한
    if n_samples < 250:
        top_n = min(top_n, 10)
    elif n_samples < 500:
        top_n = min(top_n, 12)

    # p>n 위험 경고
    if len(feature_names) > n_samples * 0.2:
        effective_top_n = max(5, min(top_n, int(n_samples * 0.15)))
        if effective_top_n < top_n:
            logger.warning(
                "  ⚠ 피처수(%d) > n_samples(%d)×0.2 → top_n %d→%d 으로 추가 축소 (과적합 방지)",
                len(feature_names), n_samples, top_n, effective_top_n,
            )
            top_n = effective_top_n

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
        logger.warning("  SHAP 실패(%s) — 컬럼 순 top-%d 사용", e, top_n)
        return feature_names[:top_n]


# ── 학습 ──────────────────────────────────────────────────────────────────────

def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true > 0
    if not mask.any():
        return 999.9
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def train_stage2(
    df: pd.DataFrame,
    config: CropConfig,
    target_mode: str = "absolute",   # "absolute" | "residual"
) -> dict:
    """GroupKFold(year) + XGB early stopping + log1p + SHAP.

    CV 전략 변경: TimeSeriesSplit → GroupKFold(groups=year)
    - 연도 단위로 fold를 구성해 동일 연도 데이터가 train/val에 동시 등장하는
      데이터 누수를 방지한다.
    - 연도가 3개 미만인 경우 TimeSeriesSplit으로 폴백.

    target_mode:
        "absolute" : 기존 방식, yield_per_m2 직접 예측 (log1p 변환 포함)
        "residual" : yield_residual = yield_per_m2 - farm_yield_hist_mean 예측
                     → farm_yield_hist_mean을 피처에서 제외,
                        모델이 순수 환경→수확량 편차를 학습
    """
    from sklearn.model_selection import TimeSeriesSplit, GroupKFold
    from sklearn.metrics import r2_score, mean_squared_error as _mse_s2, mean_absolute_error as _mae_s2
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    # ── 타겟 설정 ─────────────────────────────────────────────────────────────
    if target_mode == "residual" and "yield_residual" in df.columns:
        target = "yield_residual"
        # 잔차 모드: farm_yield_hist_mean은 이미 타겟에 반영됨 → 피처에서 제외
        # 또한 farm_yield_hist_cv, farm_obs_count도 제외 (간접 농가 아이디 누수)
        _residual_exclude_extra = {
            "farm_yield_hist_mean", "farm_yield_hist_cv", "farm_obs_count",
        }
        logger.info("  [잔차 모드] target=yield_residual (farm baseline 제거)")
    else:
        target = "yield_per_m2"
        _residual_exclude_extra = set()
        if target_mode == "residual":
            logger.warning("  [잔차 모드] yield_residual 컬럼 없음 — absolute 모드 폴백")

    # yield_ratio = yield_per_m2 / farm_yield_hist_mean → 타겟 직접 파생 → 반드시 제외
    # yield_residual = yield_per_m2 - farm_yield_hist_mean → 동일 이유로 제외
    exclude = (
        {"farm_id", "year", "month", "yield_kg", "area_m2",
         "yield_per_m2", "yield_ratio", "yield_residual"}
        | _residual_exclude_extra
    )
    feature_cols = [c for c in df.columns if c not in exclude
                    and df[c].dtype in [np.float64, np.int64, "Int64", float, int]]

    # 추론용 farm encoding 테이블 (전체 학습 데이터 기반 — 추론 시 과거값으로 사용)
    valid_mask = df[target].astype(float) > 0
    _farm_stats = (
        df[valid_mask].groupby("farm_id")[target]
        .agg(mean="mean", std="std", count="count")
    )
    _global_mean = float(df[valid_mask][target].mean())
    _global_std  = float(df[valid_mask][target].std())
    farm_encoding = {
        "per_farm": _farm_stats["mean"].to_dict(),
        "per_farm_cv": (_farm_stats["std"] / (_farm_stats["mean"] + 1e-9)).to_dict(),
        "global_mean": _global_mean,
        "global_cv":   _global_std / (_global_mean + 1e-9),
    }

    # 타겟 유효 행 (yield > 0)
    mask = df[target].astype(float) > 0
    X_raw = df.loc[mask, feature_cols]
    y_raw = df.loc[mask, target].astype(float)
    n_samples = len(X_raw)

    logger.info("  유효 샘플: %d  피처: %d", n_samples, len(feature_cols))

    imputer = SimpleImputer(strategy="median")
    X = imputer.fit_transform(X_raw)
    y = y_raw.values

    # 소샘플에서 fold 수를 줄여 첫 fold 훈련 크기 확보
    if n_samples < 100:
        n_splits = 2
    elif n_samples < 300:
        n_splits = 3
    else:
        n_splits = 4

    # ── CV 전략: GroupKFold(year) 우선, 연도 부족 시 TimeSeriesSplit 폴백 ──────
    # SUPP_YEARS: 보조 데이터 연도 (단일 농가 등) — 항상 train 집합에만 포함,
    #             테스트 폴드로 격리되면 n_test=1 → R²=NaN 문제 방지
    _SUPP_YEARS = set(SUPP_YEARS) if SUPP_YEARS else set()

    _year_arr = df.loc[mask, "year"].astype(int).values if "year" in df.columns else None
    _n_unique_years = int(len(set(_year_arr))) if _year_arr is not None else 0

    # 테스트 폴드 후보 연도 (보조연도 제외)
    _cv_test_years = sorted(set(_year_arr) - _SUPP_YEARS) if _year_arr is not None else []

    if len(_cv_test_years) >= 3:
        # 진정한 Leave-One-Year-Out CV: 보조연도는 항상 train에 포함
        # 각 fold = 1년 test + (나머지 모든 연도 + 보조연도) train
        _n_cv_splits   = len(_cv_test_years)
        _manual_splits = []
        for _ty in _cv_test_years:
            _ti = np.where(_year_arr == _ty)[0]
            _tri = np.where(_year_arr != _ty)[0]   # 보조연도 포함 → always train
            if len(_ti) > 0:
                _manual_splits.append((_tri, _ti))
        _cv_splitter = None   # 수동 splits 사용 표시
        _cv_groups   = None
        logger.info(
            "  CV 전략: LOYO splits=%d (고유연도=%d, 보조연도=%s는 always-train)",
            _n_cv_splits, _n_unique_years, sorted(_SUPP_YEARS),
        )
    elif _n_unique_years >= 3:
        _n_cv_splits = _n_unique_years
        _cv_splitter = GroupKFold(n_splits=_n_cv_splits)
        _cv_groups   = _year_arr
        _manual_splits = None
        logger.info("  CV 전략: LOYO GroupKFold(year) splits=%d (고유연도=%d, 진정 leave-one-year-out)",
                    _n_cv_splits, _n_unique_years)
    else:
        _n_cv_splits = n_splits
        _cv_splitter   = TimeSeriesSplit(n_splits=_n_cv_splits)
        _cv_groups     = None
        _manual_splits = None
        logger.info("  CV 전략: TimeSeriesSplit splits=%d (연도부족=%d)",
                    _n_cv_splits, _n_unique_years)

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
        _rmse_fb2 = float(np.sqrt(_mse_s2(y, y_pred)))
        _mae_fb2  = float(_mae_s2(y, y_pred))
        return {
            "type": "ridge_fallback",
            "model": model, "imputer": imputer, "scaler": scaler,
            "feature_cols": feature_cols,
            "log_transform": True,
            "cv_r2_mean": round(r2, 3), "cv_r2_std": 0.0,
            "mape": round(mape, 1), "n_train": n_samples,
            "train_rmse": round(_rmse_fb2, 4), "train_mae": round(_mae_fb2, 4),
            "farm_encoding": farm_encoding,
        }

    try:
        import xgboost as xgb

        # 샘플 크기에 따른 하이퍼파라미터 자동 조정
        # 소샘플 LOYO CV 과적합 방지 목표:
        #   - train R²>>1 but CV MAPE>>train MAPE 패턴 차단
        #   - reg_lambda(L2) + reg_alpha(L1) 추가
        #   - colsample_bytree/subsample 축소 (랜덤성 강화)
        #   - n<100: 극소샘플 → max_depth=2, 강제 gamma(최소분할이득), 더 강한 L2
        if n_samples < 100:
            # 극소샘플: 결정트리 깊이 최소화 + 매우 강한 정규화
            xgb_lr       = 0.05
            xgb_depth    = 2     # ↓ 3→2: depth 1단 줄임 (leaf 수 4→ 최대)
            xgb_mcw      = 8     # ↑ 5→8: 1 fold에서 최소 leaf 4샘플 이상 보장
            xgb_es       = 15
            xgb_sub      = 0.6   # ↓ 0.7→0.6
            xgb_colsamp  = 0.5   # ↓ 0.6→0.5: 50% 컬럼만 사용 (랜덤 강화)
            xgb_reg_l2   = 5.0   # ↑ 3.0→5.0: 매우 강한 L2
            xgb_reg_l1   = 1.0   # ↑ 0.5→1.0: 피처 선택성 강화
            xgb_gamma    = 0.5   # 새 추가: 분기 최소 이득 (0이면 자유분기)
            xgb_n_est    = 200   # ↓ 500→200: 과적합 전 조기 종료 유도
        elif n_samples < 250:
            # 소샘플: 강력한 정규화
            xgb_lr       = 0.08
            xgb_depth    = 3
            xgb_mcw      = 5     # ↑ 2→5: 최소 leaf 크기 확대
            xgb_es       = 20
            xgb_sub      = 0.7   # ↓ 0.9→0.7
            xgb_colsamp  = 0.6   # ↓ 0.8→0.6
            xgb_reg_l2   = 3.0   # L2 추가
            xgb_reg_l1   = 0.5   # L1 추가
            xgb_gamma    = 0.2
            xgb_n_est    = 300
        elif n_samples < 600:
            xgb_lr       = 0.08
            xgb_depth    = 3
            xgb_mcw      = 4     # ↑ 3→4
            xgb_es       = 30
            xgb_sub      = 0.75  # ↓ 0.85→0.75
            xgb_colsamp  = 0.7   # ↓ 0.8→0.7
            xgb_reg_l2   = 2.0
            xgb_reg_l1   = 0.3
            xgb_gamma    = 0.1
            xgb_n_est    = 400
        else:
            xgb_lr       = 0.05
            xgb_depth    = 4
            xgb_mcw      = 5
            xgb_es       = 50
            xgb_sub      = 0.8
            xgb_colsamp  = 0.8
            xgb_reg_l2   = 1.0
            xgb_reg_l1   = 0.1
            xgb_gamma    = 0.0
            xgb_n_est    = 500
        logger.info(
            "  XGB 파라미터: lr=%.2f depth=%d mcw=%d es=%d sub=%.2f "
            "λ=%.1f α=%.1f γ=%.1f n_est=%d (n=%d)",
            xgb_lr, xgb_depth, xgb_mcw, xgb_es, xgb_sub,
            xgb_reg_l2, xgb_reg_l1, xgb_gamma, xgb_n_est, n_samples
        )

        # ── CV split 제공자 (수동 splits / GroupKFold / TimeSeriesSplit 통일) ──────
        def _cv_split_iter(X_mat, y_vec, groups=None):
            """_manual_splits 우선, 없으면 _cv_splitter 사용."""
            if _manual_splits is not None:
                return iter(_manual_splits)
            return iter(_cv_splitter.split(X_mat, y_vec, groups=groups))

        cv_r2, cv_mape, best_iters = [], [], []
        xgb_val_preds: list[tuple] = []  # (y_true_v, y_xgb_pred) per fold — 앙상블용

        for fold, (tr_idx, val_idx) in enumerate(_cv_split_iter(X, y, groups=_cv_groups)):
            X_tr, X_val = X[tr_idx], X[val_idx]
            y_tr, y_val = np.log1p(y[tr_idx]), np.log1p(y[val_idx])

            fold_m = xgb.XGBRegressor(
                n_estimators=xgb_n_est,
                early_stopping_rounds=xgb_es,
                learning_rate=xgb_lr, max_depth=xgb_depth,
                subsample=xgb_sub, colsample_bytree=xgb_colsamp,
                min_child_weight=xgb_mcw,
                reg_lambda=xgb_reg_l2, reg_alpha=xgb_reg_l1,
                gamma=xgb_gamma,
                random_state=42, verbosity=0,
            )
            fold_m.fit(X_tr, y_tr,
                       eval_set=[(X_val, y_val)],
                       verbose=False)

            y_pred_v = np.expm1(fold_m.predict(X_val))
            y_true_v = np.expm1(y_val)
            xgb_val_preds.append((y_true_v, y_pred_v))   # 앙상블 계산용 저장
            r2   = float(r2_score(y_true_v, y_pred_v))
            mape = _mape(y_true_v, y_pred_v)
            cv_r2.append(r2)
            cv_mape.append(mape)
            best_iters.append(fold_m.best_iteration)
            logger.info("  Fold %d XGB R²=%.3f MAPE=%.1f%% (n_trees=%d)",
                        fold + 1, r2, mape, fold_m.best_iteration)

        cv_r2_mean  = float(np.mean(cv_r2))
        cv_mape_mean = float(np.mean(cv_mape))
        best_n = max(30, int(np.median(best_iters)))
        logger.info("  XGB CV R²=%.3f  MAPE=%.1f%%  best_n=%d",
                    cv_r2_mean, cv_mape_mean, best_n)

        # ── LightGBM CV + 앙상블 CV ────────────────────────────────────────────
        lgb_cv_r2_mean, lgb_cv_mape_mean, lgb_best_n = -999.0, 999.0, 50
        ens_cv_r2_mean, ens_cv_mape_mean = -999.0, 999.0
        _lgb_available = False
        try:
            import lightgbm as _lgb
            _lgb_available = True

            _lgb_cv_r2, _lgb_cv_mape, _lgb_best_iters = [], [], []
            _ens_cv_r2, _ens_cv_mape = [], []
            _num_leaves = min(31, max(7, 2 ** xgb_depth - 1))
            # 소샘플에서는 LGB도 min_data_in_leaf 강화 (xgb_mcw×2)
            _lgb_min_data = max(5, xgb_mcw * 2) if n_samples < 250 else max(5, xgb_mcw)

            for _fold2, (_tr2, _vl2) in enumerate(_cv_split_iter(X, y, groups=_cv_groups)):
                _lgb_m = _lgb.LGBMRegressor(
                    n_estimators=xgb_n_est, learning_rate=xgb_lr,
                    max_depth=xgb_depth, num_leaves=_num_leaves,
                    min_child_samples=_lgb_min_data,
                    min_split_gain=xgb_gamma,          # LGB gamma 상응 파라미터
                    subsample=xgb_sub, colsample_bytree=xgb_colsamp,
                    reg_lambda=xgb_reg_l2, reg_alpha=xgb_reg_l1,
                    random_state=42, verbosity=-1, n_jobs=1,
                )
                _lgb_m.fit(
                    X[_tr2], np.log1p(y[_tr2]),
                    eval_set=[(X[_vl2], np.log1p(y[_vl2]))],
                    callbacks=[
                        _lgb.early_stopping(xgb_es, verbose=False),
                        _lgb.log_evaluation(-1),
                    ],
                )
                _y_lgb = np.expm1(_lgb_m.predict(X[_vl2]))
                _y_tv, _y_xgb = xgb_val_preds[_fold2]
                _y_ens = 0.5 * _y_xgb + 0.5 * _y_lgb

                _r2_lgb = float(r2_score(_y_tv, _y_lgb))
                _r2_ens = float(r2_score(_y_tv, _y_ens))
                _lgb_cv_r2.append(_r2_lgb)
                _lgb_cv_mape.append(_mape(_y_tv, _y_lgb))
                _ens_cv_r2.append(_r2_ens)
                _ens_cv_mape.append(_mape(_y_tv, _y_ens))
                _lgb_best_iters.append(_lgb_m.best_iteration_ or xgb_es)

            lgb_cv_r2_mean  = float(np.mean(_lgb_cv_r2))
            lgb_cv_mape_mean = float(np.mean(_lgb_cv_mape))
            ens_cv_r2_mean  = float(np.mean(_ens_cv_r2))
            ens_cv_mape_mean = float(np.mean(_ens_cv_mape))
            lgb_best_n = max(30, int(np.median(_lgb_best_iters)))
            logger.info("  LGB  CV R²=%.3f  MAPE=%.1f%%  best_n=%d",
                        lgb_cv_r2_mean, lgb_cv_mape_mean, lgb_best_n)
            logger.info("  ENS  CV R²=%.3f  MAPE=%.1f%%",
                        ens_cv_r2_mean, ens_cv_mape_mean)
        except ImportError:
            logger.info("  LightGBM 없음 — XGB 단독 사용")
        except Exception as _e_lgb:
            logger.warning("  LGB 학습 오류(%s) — XGB 단독 사용", _e_lgb)

        # 모델 후보 중 최우수 CV R² 선택 (XGB / LGB / 앙상블)
        _candidates = {
            "xgb":              (cv_r2_mean,      cv_mape_mean),
            "lgb":              (lgb_cv_r2_mean,  lgb_cv_mape_mean),
            "xgb_lgb_ensemble": (ens_cv_r2_mean,  ens_cv_mape_mean),
        }
        _best_tree_type = max(_candidates, key=lambda k: _candidates[k][0])
        _best_tree_r2, _best_tree_mape = _candidates[_best_tree_type]
        logger.info("  트리 모델 최우수: %s (CV R²=%.3f)", _best_tree_type, _best_tree_r2)

        # ── Ridge CV 비교: XGB early stopping이 너무 이른 경우(소샘플) Ridge가 더 안정적 ──
        from sklearn.preprocessing import StandardScaler as _StdScaler
        _scaler_r = _StdScaler()
        X_sc_r = _scaler_r.fit_transform(X)
        _ridge_alphas = [0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0]
        best_r_alpha, best_r_cv_r2, best_r_cv_mape = 10.0, -999.0, 999.0

        for _alpha in _ridge_alphas:
            _fold_r2s, _fold_mapes = [], []
            for _tr, _vl in _cv_split_iter(X_sc_r, y, groups=_cv_groups):
                _rm = Ridge(alpha=_alpha)
                _rm.fit(X_sc_r[_tr], np.log1p(y[_tr]))
                _yp = np.expm1(_rm.predict(X_sc_r[_vl]))
                _yt = y[_vl]
                _fold_r2s.append(float(r2_score(_yt, _yp)))
                _fold_mapes.append(_mape(_yt, _yp))
            _a_r2   = float(np.mean(_fold_r2s))
            _a_mape = float(np.mean(_fold_mapes))
            if _a_r2 > best_r_cv_r2:
                best_r_cv_r2, best_r_cv_mape, best_r_alpha = _a_r2, _a_mape, _alpha

        logger.info("  Ridge 최적: alpha=%.1f  CV R²=%.3f  MAPE=%.1f%%",
                    best_r_alpha, best_r_cv_r2, best_r_cv_mape)

        # ── 최우수 모델 선택: XGB / LGB / 앙상블 / Ridge ─────────────────────
        # 기준: CV R² 최대화, MAPE는 현재 최우수 트리 대비 15% 이내 악화 허용
        _ref_r2   = _best_tree_r2    # 최우수 트리 CV R²를 기준으로 Ridge 비교
        _ref_mape = _best_tree_mape
        _mape_tolerance = _ref_mape * 1.15

        # Ridge는 트리보다 CV R²가 높아야 AND MAPE 허용 범위 내여야 선택
        _ridge_eligible = (
            best_r_cv_r2 > _ref_r2
            and best_r_cv_mape <= _mape_tolerance
        )
        logger.info("  Ridge 선택 여부: R²↑=%s (%.3f>%.3f)  MAPE 허용(%.1f%%≤%.1f%%)=%s",
                    best_r_cv_r2 > _ref_r2, best_r_cv_r2, _ref_r2,
                    best_r_cv_mape, _mape_tolerance, best_r_cv_mape <= _mape_tolerance)

        if _ridge_eligible:
            logger.info("  → Ridge 모델 선택 (CV R²=%.3f > 트리 %.3f, MAPE OK)",
                        best_r_cv_r2, _ref_r2)
            _final_ridge = Ridge(alpha=best_r_alpha)
            _final_ridge.fit(X_sc_r, np.log1p(y))
            _yp_all = np.expm1(_final_ridge.predict(X_sc_r))
            _tr_r2  = float(r2_score(y, _yp_all))
            _tr_mape = _mape(y, _yp_all)
            _tr_rmse_r = float(np.sqrt(_mse_s2(y, _yp_all)))
            _tr_mae_r  = float(_mae_s2(y, _yp_all))
            logger.info("  Ridge 훈련 R²=%.3f  MAPE=%.1f%%  RMSE=%.4f  MAE=%.4f",
                        _tr_r2, _tr_mape, _tr_rmse_r, _tr_mae_r)
            return {
                "type": "ridge_cv_winner",
                "model": _final_ridge,
                "imputer": imputer,
                "scaler": _scaler_r,
                "feature_cols": feature_cols,
                "log_transform": True,
                "cv_r2_mean":   round(best_r_cv_r2,   3),
                "cv_r2_std":    0.0,
                "cv_mape_mean": round(best_r_cv_mape,  1),
                "final_r2":     round(_tr_r2,  3),
                "mape":         round(_tr_mape, 1),
                "train_rmse":   round(_tr_rmse_r, 4),
                "train_mae":    round(_tr_mae_r, 4),
                "n_train": n_samples,
                "all_feature_cols": feature_cols,
                "shap_top_n": 0,
                "farm_encoding": farm_encoding,
            }

        # ── LGB 단독 또는 앙상블이 XGB보다 나은 경우 → 즉시 반환 ─────────────
        if _lgb_available and _best_tree_type in ("lgb", "xgb_lgb_ensemble"):
            logger.info("  → %s 선택 (CV R²=%.3f > XGB=%.3f)",
                        _best_tree_type, _best_tree_r2, cv_r2_mean)

            # 최종 전체 데이터 학습
            _xgb_final = xgb.XGBRegressor(
                n_estimators=best_n, learning_rate=xgb_lr, max_depth=xgb_depth,
                subsample=xgb_sub, colsample_bytree=xgb_colsamp,
                min_child_weight=xgb_mcw,
                reg_lambda=xgb_reg_l2, reg_alpha=xgb_reg_l1,
                gamma=xgb_gamma,
                random_state=42, verbosity=0,
            )
            _xgb_final.fit(X, np.log1p(y))

            _lgb_final = _lgb.LGBMRegressor(
                n_estimators=lgb_best_n, learning_rate=xgb_lr,
                max_depth=xgb_depth, num_leaves=_num_leaves,
                min_child_samples=_lgb_min_data,
                min_split_gain=xgb_gamma,
                subsample=xgb_sub, colsample_bytree=xgb_colsamp,
                reg_lambda=xgb_reg_l2, reg_alpha=xgb_reg_l1,
                random_state=42, verbosity=-1, n_jobs=1,
            )
            _lgb_final.fit(X, np.log1p(y))

            if _best_tree_type == "lgb":
                _yp_all = np.expm1(_lgb_final.predict(X))
                _sel_r2   = lgb_cv_r2_mean
                _sel_mape = lgb_cv_mape_mean
            else:  # ensemble
                _yp_all = 0.5 * np.expm1(_xgb_final.predict(X)) + \
                          0.5 * np.expm1(_lgb_final.predict(X))
                _sel_r2   = ens_cv_r2_mean
                _sel_mape = ens_cv_mape_mean

            _tr_r2   = float(r2_score(y, _yp_all))
            _tr_mape = _mape(y, _yp_all)
            _tr_rmse_ens = float(np.sqrt(_mse_s2(y, _yp_all)))
            _tr_mae_ens  = float(_mae_s2(y, _yp_all))
            logger.info("  %s 훈련 R²=%.3f  MAPE=%.1f%%  RMSE=%.4f  MAE=%.4f",
                        _best_tree_type, _tr_r2, _tr_mape, _tr_rmse_ens, _tr_mae_ens)

            # SHAP 피처 선택은 XGB 모델 기준 (LGB SHAP도 유사)
            top_n = 8 if n_samples < 150 else (10 if n_samples < 300 else 15)
            shap_selected = select_top_features(_xgb_final, X, feature_cols, top_n,
                                                n_samples=n_samples)
            _ALWAYS_INCLUDE = [
                "farm_yield_hist_mean", "farm_yield_hist_cv",
                "variety_yield_mean", "log_area_m2",
            ]
            always_in = [f for f in _ALWAYS_INCLUDE if f in feature_cols]
            selected_set = dict.fromkeys(shap_selected)
            for f in always_in:
                selected_set.setdefault(f, None)
            selected_features = list(selected_set.keys())

            sel_idx = [feature_cols.index(f) for f in selected_features if f in feature_cols]
            X_sel   = X[:, sel_idx]
            imp_sel = SimpleImputer(strategy="median").fit(X_raw[selected_features])

            # 피처 선택 후 최종 재학습
            _xgb_sel = xgb.XGBRegressor(
                n_estimators=best_n, learning_rate=xgb_lr, max_depth=xgb_depth,
                subsample=xgb_sub, colsample_bytree=xgb_colsamp,
                min_child_weight=xgb_mcw,
                reg_lambda=xgb_reg_l2, reg_alpha=xgb_reg_l1,
                gamma=xgb_gamma,
                random_state=42, verbosity=0,
            )
            _xgb_sel.fit(X_sel, np.log1p(y))

            _lgb_sel = _lgb.LGBMRegressor(
                n_estimators=lgb_best_n, learning_rate=xgb_lr,
                max_depth=xgb_depth, num_leaves=_num_leaves,
                min_child_samples=_lgb_min_data,
                min_split_gain=xgb_gamma,
                subsample=xgb_sub, colsample_bytree=xgb_colsamp,
                reg_lambda=xgb_reg_l2, reg_alpha=xgb_reg_l1,
                random_state=42, verbosity=-1, n_jobs=1,
            )
            _lgb_sel.fit(X_sel, np.log1p(y))

            # Quantile 모델 (XGB 기준 — 앙상블/LGB 경로도 XGB로 quantile 계산)
            _q_models_ens: dict = {}
            try:
                for _qa, _qname in [(0.10, "q10"), (0.90, "q90")]:
                    _qm = xgb.XGBRegressor(
                        objective="reg:quantileerror", quantile_alpha=_qa,
                        n_estimators=best_n, learning_rate=xgb_lr,
                        max_depth=xgb_depth, subsample=xgb_sub,
                        colsample_bytree=xgb_colsamp, min_child_weight=xgb_mcw,
                        reg_lambda=xgb_reg_l2, gamma=xgb_gamma,
                        random_state=42, verbosity=0,
                    )
                    _qm.fit(X_sel, np.log1p(y))
                    _q_models_ens[_qname] = _qm
                logger.info("  Quantile 모델 P10/P90 학습 완료 (%s)", _best_tree_type)
            except Exception as _eq2:
                logger.info("  Quantile 모델 생략(%s)", _eq2)

            return {
                "type": _best_tree_type,
                "model": _xgb_sel,       # XGB 모델 (앙상블 시 model_lgb와 함께 사용)
                "model_lgb": _lgb_sel,   # LGB 모델 (single LGB 모드에서도 저장)
                "model_q10": _q_models_ens.get("q10"),
                "model_q90": _q_models_ens.get("q90"),
                "imputer": imp_sel,
                "feature_cols": selected_features,
                "log_transform": True,
                "best_n_estimators": best_n,
                "lgb_best_n": lgb_best_n,
                "cv_r2_mean":   round(_sel_r2,   3),
                "cv_r2_std":    0.0,
                "cv_mape_mean": round(_sel_mape,  1),
                "final_r2":     round(_tr_r2,  3),
                "mape":         round(_tr_mape, 1),
                "train_rmse":   round(_tr_rmse_ens, 4),
                "train_mae":    round(_tr_mae_ens, 4),
                "n_train": n_samples,
                "all_feature_cols": feature_cols,
                "shap_top_n": top_n,
                "farm_encoding": farm_encoding,
            }

        logger.info("  → XGB 단독 선택 (CV R²=%.3f 최우수)", cv_r2_mean)

        # 전체 데이터로 최종 학습 (best_n + 동일 파라미터)
        final_model = xgb.XGBRegressor(
            n_estimators=best_n,
            learning_rate=xgb_lr, max_depth=xgb_depth,
            subsample=xgb_sub, colsample_bytree=xgb_colsamp,
            min_child_weight=xgb_mcw,
            reg_lambda=xgb_reg_l2, reg_alpha=xgb_reg_l1,
            gamma=xgb_gamma,
            random_state=42, verbosity=0,
        )
        final_model.fit(X, np.log1p(y))

        # SHAP 피처 선택 (폴백: 컬럼 순 top-N)
        top_n = 8 if n_samples < 150 else (10 if n_samples < 300 else 15)
        shap_selected = select_top_features(final_model, X, feature_cols, top_n,
                                            n_samples=n_samples)

        # 항상 포함할 고효과 피처 (SHAP 순위와 무관하게 강제 포함)
        _ALWAYS_INCLUDE = [
            "farm_yield_hist_mean", # 농가 이력 평균 (expanding mean, 누수 없음)
            "farm_yield_hist_cv",   # 농가 이력 변동계수 (일관성 지표)
            "variety_yield_mean",   # 품종 효과 (시계열 안전 expanding mean)
            "log_area_m2",          # 규모 효과
            "year_norm",            # 연도 트렌드 (기술 개선)
        ]
        always_in = [f for f in _ALWAYS_INCLUDE if f in feature_cols]
        # SHAP 선택 피처 + always_include 합집합
        selected_set = dict.fromkeys(shap_selected)   # 순서 보존 dict
        for f in always_in:
            selected_set.setdefault(f, None)
        selected_features = list(selected_set.keys())
        logger.info("  최종 피처 %d개 (SHAP %d + 강제포함 %d): %s",
                    len(selected_features), len(shap_selected),
                    len([f for f in always_in if f not in shap_selected]),
                    [f for f in always_in if f not in shap_selected])

        # 선택 피처로 재학습
        sel_idx  = [feature_cols.index(f) for f in selected_features
                    if f in feature_cols]
        X_sel    = X[:, sel_idx]
        imp_sel  = SimpleImputer(strategy="median").fit(X_raw[selected_features])

        final_sel = xgb.XGBRegressor(
            n_estimators=best_n, learning_rate=xgb_lr, max_depth=xgb_depth,
            subsample=xgb_sub, colsample_bytree=xgb_colsamp,
            min_child_weight=xgb_mcw,
            reg_lambda=xgb_reg_l2, reg_alpha=xgb_reg_l1,
            gamma=xgb_gamma,
            random_state=42, verbosity=0,
        )
        final_sel.fit(X_sel, np.log1p(y))

        # ── Quantile 예측 구간 모델 (P10 / P90) ─────────────────────────────
        # reg:quantileerror = XGBoost 2.0+ 분위수 회귀
        _q_models: dict = {}
        try:
            for _qa, _qname in [(0.10, "q10"), (0.90, "q90")]:
                _qm = xgb.XGBRegressor(
                    objective="reg:quantileerror",
                    quantile_alpha=_qa,
                    n_estimators=best_n, learning_rate=xgb_lr,
                    max_depth=xgb_depth, subsample=xgb_sub,
                    colsample_bytree=xgb_colsamp, min_child_weight=xgb_mcw,
                    reg_lambda=xgb_reg_l2, gamma=xgb_gamma,
                    random_state=42, verbosity=0,
                )
                _qm.fit(X_sel, np.log1p(y))
                _q_models[_qname] = _qm
            logger.info("  Quantile 모델 P10/P90 학습 완료")
        except Exception as _eq:
            logger.info("  Quantile 모델 생략(%s) — XGBoost 버전 미지원", _eq)

        # 최종 검증
        y_pred_final = np.expm1(final_sel.predict(X_sel))
        final_r2   = float(r2_score(y, y_pred_final))
        final_mape = _mape(y, y_pred_final)
        _final_rmse = float(np.sqrt(_mse_s2(y, y_pred_final)))
        _final_mae  = float(_mae_s2(y, y_pred_final))

        return {
            "type": "xgb",
            "model": final_sel,
            "model_q10": _q_models.get("q10"),
            "model_q90": _q_models.get("q90"),
            "imputer": imp_sel,
            "feature_cols": selected_features,
            "log_transform": True,
            "best_n_estimators": best_n,
            "cv_r2_mean":  round(cv_r2_mean, 3),
            "cv_r2_std":   round(float(np.std(cv_r2)), 3),
            "cv_mape_mean": round(cv_mape_mean, 1),
            "final_r2":    round(final_r2, 3),
            "mape":        round(final_mape, 1),
            "train_rmse":  round(_final_rmse, 4),
            "train_mae":   round(_final_mae, 4),
            "n_train": n_samples,
            "all_feature_cols": feature_cols,
            "shap_top_n": top_n,
            "farm_encoding": farm_encoding,
        }

    except ImportError:
        logger.warning("  XGBoost 없음 — Ridge 폴백")
        scaler = StandardScaler()
        X_sc = scaler.fit_transform(X)
        cv_r2, cv_mape = [], []
        model = Ridge(alpha=10.0)
        for tr_idx, val_idx in _cv_split_iter(X_sc, y, groups=_cv_groups):
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
            "farm_encoding": farm_encoding,
        }


# ── 배포 게이트 ───────────────────────────────────────────────────────────────

def check_gate(result: dict) -> bool:
    """배포 게이트 (2-rule OR logic): LOYO CV 기반 현실적 기준.

    Rule A: CV MAPE ≤ 110% AND CV R² ≥ -0.20
         → 절대 오차가 낮고 (모델이 발산 안 함) 예측 방향성 있음
    Rule B: CV R² ≥ 0.0
         → 모델이 단순 평균 예측보다 높은 설명력 보유 (MAPE 무관하게 허용)

    두 규칙 중 하나만 만족해도 PASS.

    배경:
    - LOYO CV MAPE는 항상 훈련 MAPE보다 높음 (연간 데이터 과적합 특성상 불가피)
    - 완숙토마토처럼 CV R²>0이지만 MAPE가 높은 경우를 포용
    - 방울토마토처럼 CV MAPE 200%+인 경우는 명확히 FAIL
    """
    cv_mape = result.get("cv_mape_mean")
    tr_mape = result.get("mape", 999.0)
    mape    = cv_mape if cv_mape is not None else tr_mape
    r2      = result.get("cv_r2_mean", -999.0)
    src     = "CV" if cv_mape is not None else "train"

    rule_a = (mape <= 110.0) and (r2 >= -0.20)
    rule_b = (r2 >= 0.0)
    gate_passed = rule_a or rule_b

    logger.info("  게이트 Rule-A (MAPE≤110%%&R²≥-0.20): MAPE(%s)=%.1f%%  R²=%.3f  → %s",
                src, mape, r2, "✅ PASS" if rule_a else "❌ FAIL")
    logger.info("  게이트 Rule-B (R²≥0.0):               R²=%.3f → %s",
                r2, "✅ PASS" if rule_b else "❌ FAIL")
    logger.info("  게이트 최종: %s", "✅ PASS" if gate_passed else "❌ FAIL")
    return gate_passed


# ── 메인 ──────────────────────────────────────────────────────────────────────

def run_crop(crop_ko: str, use_cache: bool = True) -> dict | None:
    config = CROP_CONFIGS.get(crop_ko)
    if not config:
        logger.error("지원하지 않는 작목: %s", crop_ko)
        return None

    logger.info("=" * 55)
    logger.info("Stage 2 학습: %s", crop_ko)
    logger.info("=" * 55)

    default_area = AREA_DEFAULTS.get(crop_ko, 1200.0)

    logger.info("[1] 환경 데이터 로드")
    env_m = load_env_monthly(crop_ko, use_cache=use_cache)

    logger.info("[2] 생육 데이터 로드")
    growth_m = load_growth_monthly(crop_ko, config.growth_cols, use_cache=use_cache)

    logger.info("[3] 수확량 데이터 로드")
    area_map = load_area_map(crop_ko)
    prod_m = load_production_monthly(crop_ko, area_map, default_area, use_cache=use_cache)
    if prod_m.empty:
        logger.error("  수확량 데이터 없음 — 스킵")
        return None

    logger.info("[3b] 재배정보 메타 로드 (품종·온실유형·정식월)")
    cultiv_meta = load_cultiv_meta(crop_ko)
    logger.info("  재배메타: %d농가", len(cultiv_meta))

    logger.info("[4a] Stage2 행렬 구성 — 월별 모드")
    df_monthly = build_stage2_matrix(env_m, growth_m, prod_m, config, cultiv_meta=cultiv_meta)

    logger.info("[4b] Stage2 행렬 구성 — 연간(작기) 모드")
    df_annual  = build_stage2_matrix_annual(env_m, growth_m, prod_m, config, cultiv_meta=cultiv_meta)

    # 두 모드 중 MAPE가 낮은 모델 선택
    result_monthly = train_stage2(df_monthly, config, target_mode="absolute") if not df_monthly.empty else None
    result_annual  = train_stage2(df_annual,  config, target_mode="absolute") if not df_annual.empty  else None

    # ── 잔차 모드 비교 (연간 데이터에서만) ──────────────────────────────────
    # yield_residual = yield_per_m2 - farm_yield_hist_mean: farm identity 제거
    # → LOYO CV에서 R² 개선 기대 (연도별 편차 설명 능력 집중 평가)
    result_residual = None
    if not df_annual.empty and "yield_residual" in df_annual.columns:
        logger.info("[4c] 잔차 모드 학습 — 농가 baseline 제거 후 환경 편차 예측")
        result_residual = train_stage2(df_annual, config, target_mode="residual")
        if result_residual:
            res_cv_r2   = result_residual.get("cv_r2_mean", -999.0)
            res_cv_mape = result_residual.get("cv_mape_mean", 999.0)
            logger.info("  잔차 모드: CV R²=%.3f  CV MAPE=%.1f%%", res_cv_r2, res_cv_mape)

    if result_monthly and result_annual:
        # CV MAPE 우선 (없으면 training MAPE 폴백)
        m_cv_mape = result_monthly.get("cv_mape_mean", result_monthly.get("mape", 999.0))
        a_cv_mape = result_annual.get("cv_mape_mean",  result_annual.get("mape",  999.0))
        if a_cv_mape < m_cv_mape:
            result = result_annual
            agg_mode = "annual"
            logger.info("[5] 연간 모드 선택 (annual CV_MAPE=%.1f%% < monthly CV_MAPE=%.1f%%)",
                        a_cv_mape, m_cv_mape)
        else:
            result = result_monthly
            agg_mode = "monthly"
            logger.info("[5] 월별 모드 선택 (monthly CV_MAPE=%.1f%% ≤ annual CV_MAPE=%.1f%%)",
                        m_cv_mape, a_cv_mape)
    elif result_annual:
        result = result_annual; agg_mode = "annual"
    elif result_monthly:
        result = result_monthly; agg_mode = "monthly"
    else:
        return None

    # ── 잔차 모드와 비교: CV R²이 더 높으면 잔차 모드 선택 ─────────────────────
    if result_residual:
        res_cv_r2  = result_residual.get("cv_r2_mean",   -999.0)
        cur_cv_r2  = result.get("cv_r2_mean",            -999.0)
        res_cv_mape = result_residual.get("cv_mape_mean", 999.0)
        cur_cv_mape = result.get("cv_mape_mean",          999.0)
        # 잔차 모드 우선 조건: CV R²이 현재 모드보다 0.05 이상 높음
        if res_cv_r2 > cur_cv_r2 + 0.05:
            result   = result_residual
            agg_mode = "annual_residual"
            logger.info(
                "[5-R] 잔차 모드 선택 (CV R²=%.3f > absolute %.3f, MAPE=%.1f%%)",
                res_cv_r2, cur_cv_r2, res_cv_mape,
            )
        else:
            logger.info(
                "[5-R] absolute 모드 유지 (CV R²=%.3f ≥ residual %.3f)",
                cur_cv_r2, res_cv_r2,
            )

    logger.info("[6] 배포 게이트 검사")
    gate_passed = check_gate(result)

    # 아티팩트 저장
    art_dir  = get_artifact_dir(config.crop_en)
    pkl_path = art_dir / "stage2_yield.pkl"
    meta_path = art_dir / "stage2_meta.json"

    save_keys = {"model", "model_lgb", "model_q10", "model_q90",
                 "imputer", "scaler", "feature_cols",
                 "log_transform", "best_n_estimators", "lgb_best_n", "farm_encoding"}
    bundle = {k: v for k, v in result.items() if k in save_keys}
    with open(pkl_path, "wb") as f:
        pickle.dump(bundle, f)

    # ── m2_yield_model.pkl 동기화 저장 (포맷 C: m2_yield.py가 직접 로드) ─────
    # m2_yield.py는 "feature_cols" + "imputer" 키를 포맷 C로 감지해 stage2 모델을 직접 사용.
    # 이로써 profit_optimizer.py가 실제 학습된 M2 모델을 사용할 수 있음.
    # 잔차 모드(annual_residual)에서 log_transform=True를 유지하면
    # 음수 잔차에 log1p 적용 → NaN → TypeError 발생.
    # 잔차 모드는 스케일이 ±수십 kg/m² 이므로 log 변환 불필요.
    _log_transform_save = (
        False if agg_mode == "annual_residual"
        else bundle.get("log_transform", True)
    )
    m2_bundle = {
        "feature_cols":      bundle.get("feature_cols", []),
        "imputer":           bundle.get("imputer"),
        "model":             bundle.get("model"),       # XGB
        "model_lgb":         bundle.get("model_lgb"),   # LGB (있으면)
        "log_transform":     _log_transform_save,
        "farm_encoding":     bundle.get("farm_encoding", {}),
        "cv_mape_mean":      result.get("cv_mape_mean"),
        "mape":              result.get("mape"),
        "gate_pass":         gate_passed,
        "agg_mode":          agg_mode,
    }
    m2_pkl_path = art_dir / "m2_yield_model.pkl"
    with open(m2_pkl_path, "wb") as f:
        pickle.dump(m2_bundle, f)
    # 캐시 무효화 (m2_yield.py 내부 _cache 리셋)
    try:
        from models import m2_yield as _m2mod
        _m2mod._cache.pop(config.crop_en, None)
    except Exception:
        pass
    logger.info("  m2_yield_model.pkl 동기화 저장 완료 (포맷 C)")

    meta = {
        "crop_ko": crop_ko,
        "crop_en": config.crop_en,
        "stage": 2,
        "model_type": result.get("type"),
        "feature_count": len(result.get("feature_cols", [])),
        "n_train": result.get("n_train"),
        "log_transform": result.get("log_transform", True),
        "best_n_estimators": result.get("best_n_estimators"),
        "lgb_best_n": result.get("lgb_best_n"),
        "has_lgb": result.get("model_lgb") is not None,
        "has_quantile": result.get("model_q10") is not None,
        "cv_r2_mean":  result.get("cv_r2_mean"),
        "cv_r2_std":   result.get("cv_r2_std"),
        "cv_mape_mean": result.get("cv_mape_mean"),
        "mape": result.get("mape"),
        "train_rmse": result.get("train_rmse"),    # 훈련 데이터 RMSE kg/m²
        "train_mae":  result.get("train_mae"),     # 훈련 데이터 MAE kg/m²
        "gate_passed": gate_passed,
        "agg_mode": agg_mode,
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
    parser.add_argument("--no-cache", action="store_true",
                        help="Parquet 캐시를 무시하고 ZIP에서 재로드")
    args = parser.parse_args()

    use_cache = not args.no_cache
    targets = list(CROP_CONFIGS.keys()) if args.crop == "all" else [args.crop]
    results = {}
    for crop in targets:
        r = run_crop(crop, use_cache=use_cache)
        if r:
            results[crop] = r

    logger.info("\n=== Stage 2 완료 ===")
    for crop, r in results.items():
        logger.info("  %-10s CV R²=%.3f  MAPE=%.1f%%  PASS=%s",
                    crop, r.get("cv_r2_mean", 0), r.get("mape", 0), r["gate_passed"])


if __name__ == "__main__":
    main()
