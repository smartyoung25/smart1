"""ERA5-Land 기상 피처 어댑터 — SFROP v2.0 Phase 45.

ERA5 NetCDF → 일별 CSV → 월별 집계 → M1 학습 행렬 피처 추가

우선순위:
  1) 기존 다운로드된 ERA5 CSV (`data/weather/era5/*.csv`)
  2) NASA POWER API 폴백 (인터넷 연결 시 자동 사용)
  3) KMA 내부 온도 기반 합성 추정 (오프라인 최후 수단)

추가되는 피처 (월별 집계):
  - GDD정규화    : 생육도일 정규화 (0~1) — 전작목
  - CU_norm      : 냉각단위 누적 정규화 — 딸기·참외
  - ET0_mm       : 잠재증발산량 (Hargreaves-Samani 근사, mm/월)
  - DIF          : 주야간 온도차 (평균기온 - 최저기온, °C)
  - NDVI_proxy   : 식생지수 프록시 (생육 진행도 기반 추정)
  - 누적일사량   : 작기 내 일사 누적 (MJ/m²/월)

참고: era5_download_run.py (smartfarm-mvp) 로직 포팅
      Hargreaves-Samani ET0 공식 (FAO-56 기준)
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent

# ERA5 CSV 저장 경로
_ERA5_DIR = ROOT / "data" / "weather" / "era5"
_ERA5_DIR.mkdir(parents=True, exist_ok=True)

# 5개 대표 지역 (smartfarm-mvp 동일)
LOCATIONS: dict[str, dict] = {
    "경북성주": {"lat": 35.92, "lon": 128.28, "crops": ["참외", "딸기"]},
    "충남논산": {"lat": 36.19, "lon": 127.10, "crops": ["딸기"]},
    "전북익산": {"lat": 35.94, "lon": 126.95, "crops": ["딸기"]},
    "경기평택": {"lat": 36.99, "lon": 127.11, "crops": ["완숙토마토", "방울토마토"]},
    "경남합천": {"lat": 35.57, "lon": 128.17, "crops": ["오이", "파프리카"]},
}

# 작목별 주 생산지 매핑
_CROP_LOCATION: dict[str, str] = {
    "딸기":      "충남논산",
    "방울토마토": "경기평택",
    "완숙토마토": "경기평택",
    "참외":      "경북성주",
    "파프리카":  "경남합천",
    "오이":      "경남합천",
}

# 작목별 기준온도 (T_base) 및 GDD 목표 (T_base, GDD_target)
_CROP_GDD: dict[str, tuple[float, float]] = {
    "딸기":      (5.0,  600.0),
    "방울토마토": (8.0, 1000.0),
    "완숙토마토": (8.0, 1100.0),
    "참외":      (10.0, 900.0),
    "파프리카":  (8.0,  1200.0),
    "오이":      (8.0,   700.0),
}


# ── 1. ERA5 CSV 로드 ───────────────────────────────────────────────────────────

def _load_era5_csv(location: str) -> Optional[pd.DataFrame]:
    """저장된 ERA5 일별 CSV 로드 (다운로드 선행 필요)."""
    p = _ERA5_DIR / f"era5_{location}_일별.csv"
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p, parse_dates=["날짜"])
        logger.info("  ERA5 CSV 로드: %s (%d행)", p.name, len(df))
        return df
    except Exception as e:
        logger.debug("  ERA5 CSV 로드 실패 (%s): %s", location, e)
        return None


# ── 2. NASA POWER 폴백 ─────────────────────────────────────────────────────────

def _fetch_nasa_power_monthly(
    lat: float, lon: float,
    year_start: int = 2017, year_end: int = 2024,
) -> Optional[pd.DataFrame]:
    """NASA POWER API → 월별 기상 집계 (T2M, T2M_MIN, 일사량, ET0)."""
    try:
        from adapters.nasa_power_adapter import fetch_nasa_power
        start = date(year_start, 1, 1)
        end   = date(year_end, 12, 31)
        df_daily = fetch_nasa_power(lat=lat, lon=lon, start=start, end=end)
        if df_daily is None or df_daily.empty:
            return None

        df_daily["date"] = pd.to_datetime(df_daily.index if df_daily.index.dtype == "datetime64[ns]"
                                          else df_daily.get("date", df_daily.index))
        df_daily["year"]  = df_daily["date"].dt.year
        df_daily["month"] = df_daily["date"].dt.month

        # ET0 Hargreaves-Samani 근사
        if "temp_ext_max" in df_daily.columns and "temp_ext_min" in df_daily.columns:
            T_max = df_daily["temp_ext_max"].fillna(25.0)
            T_min = df_daily["temp_ext_min"].fillna(10.0)
            T_avg = df_daily.get("temp_external", (T_max + T_min) / 2).fillna((T_max + T_min) / 2)
            Ra   = df_daily.get("solar_rad", 200.0).fillna(200.0)   # W/m² → MJ/m²/day 근사
            Ra_mj = Ra * 0.0864
            # Hargreaves: ET0 = 0.0023 × Ra × (T_avg+17.8) × sqrt(T_max-T_min)
            df_daily["ET0_mm_day"] = 0.0023 * Ra_mj * (T_avg + 17.8) * np.sqrt((T_max - T_min).clip(lower=0))
        else:
            df_daily["ET0_mm_day"] = 2.0

        # 냉각단위 (CU): 일최저기온 ≤ 5°C이면 1
        t_min_col = "temp_ext_min" if "temp_ext_min" in df_daily.columns else "temp_external"
        df_daily["CU"] = (df_daily[t_min_col].fillna(10.0) <= 5.0).astype(float)
        df_daily["CU_cumsum_yr"] = df_daily.groupby("year")["CU"].cumsum()

        # DIF: 평균기온 - 최저기온
        t_avg_col = "temp_external" if "temp_external" in df_daily.columns else "temp_ext_max"
        t_min_col2 = "temp_ext_min" if "temp_ext_min" in df_daily.columns else t_avg_col
        df_daily["DIF"] = (df_daily[t_avg_col].fillna(20.0) -
                           df_daily[t_min_col2].fillna(12.0)).clip(lower=0)

        agg = df_daily.groupby(["year", "month"]).agg(
            평균기온_C = (t_avg_col, "mean"),
            최저기온_C = (t_min_col2, "mean"),
            일사량_MJm2= ("solar_rad", lambda x: (x.mean() * 0.0864 * x.count())),
            ET0_mm     = ("ET0_mm_day", "sum"),
            CU_norm_raw= ("CU_cumsum_yr", "max"),
            DIF        = ("DIF", "mean"),
        ).reset_index()
        logger.info("  NASA POWER 월집계: %d행 (%.0f~%.0f년)", len(agg),
                    agg["year"].min(), agg["year"].max())
        return agg
    except Exception as e:
        logger.debug("  NASA POWER 폴백 실패: %s", e)
        return None


# ── 3. KMA 내부온도 기반 합성 추정 (오프라인 최후 수단) ───────────────────────

def _synthetic_era5_from_internal(
    df_train: pd.DataFrame,
    crop_ko: str,
) -> pd.DataFrame:
    """내부 온도 피처가 있으면 외기온도를 추정해 ERA5 피처 합성.

    스마트팜 내부온도는 외기대비 +3~5°C이므로 역산 가능.
    ET0는 내부습도 기반 Penman-Monteith 간략식으로 근사.
    """
    df = df_train.copy()
    T_base, GDD_tgt = _CROP_GDD.get(crop_ko, (8.0, 900.0))

    # 내부온도가 있으면 외기 추정
    t_col = "temp_internal_mean" if "temp_internal_mean" in df.columns else None
    if t_col:
        df["era5_t_ext"] = (df[t_col] - 4.0).clip(lower=-20)
        df["era5_t_min"] = (df[t_col] - 8.0).clip(lower=-25)
    else:
        # 최후 수단: 월별 한국 평균 기온 (중부 기준)
        month_temp = {1:-2.5, 2:0.0, 3:5.8, 4:12.5, 5:18.1, 6:22.7,
                      7:25.8, 8:26.3, 9:21.3, 10:14.1, 11:6.4, 12:0.3}
        df["era5_t_ext"] = df["month"].astype(int).map(month_temp).fillna(15.0)
        df["era5_t_min"] = df["era5_t_ext"] - 6.0

    # GDD 월별
    df["GDD_monthly"] = (df["era5_t_ext"] - T_base).clip(lower=0) * 30

    # GDD 누적 (farm_id×year 기준)
    df = df.sort_values(["farm_id", "year", "month"]).copy()
    df["GDD_cumsum"] = df.groupby(["farm_id", "year"])["GDD_monthly"].cumsum()
    df["GDD정규화"]  = (df["GDD_cumsum"] / GDD_tgt).clip(0, 1)

    # CU 추정 (최저기온 ≤ 5°C 확률 기반 합성)
    month_cu = {1:30, 2:25, 3:10, 4:1, 5:0, 6:0,
                7:0,  8:0,  9:0, 10:2, 11:15, 12:28}
    df["CU_monthly"] = df["month"].astype(int).map(month_cu).fillna(0).astype(float)
    df["CU_cumsum"]  = df.groupby(["farm_id", "year"])["CU_monthly"].cumsum()
    df["CU_norm"]    = ((df["CU_cumsum"] * 5) - 300) / 800

    # DIF
    df["DIF"] = (df["era5_t_ext"] - df["era5_t_min"]).clip(lower=0)

    # ET0 간략 Hargreaves (월 합계, mm/월)
    solar_col = "solar_rad_mean" if "solar_rad_mean" in df.columns else None
    if solar_col:
        Ra_mj = df[solar_col].fillna(150.0) * 0.0864
        df["ET0_mm"] = (0.0023 * Ra_mj * (df["era5_t_ext"].fillna(15.0) + 17.8) *
                        np.sqrt(df["DIF"].clip(lower=0.1))) * 30
    else:
        month_et0 = {1:20, 2:28, 3:55, 4:85, 5:110, 6:130,
                     7:120, 8:115, 9:90,  10:60, 11:35, 12:22}
        df["ET0_mm"] = df["month"].astype(int).map(month_et0).fillna(70.0)

    # NDVI 프록시 (GDD정규화 기반 + 계절 보정)
    df["NDVI_proxy"] = (0.25 + 0.55 * df["GDD정규화"]).clip(0.15, 0.90)

    # 누적일사량 (월별 MJ/m²)
    if solar_col:
        df["누적일사량_MJm2"] = df.groupby(["farm_id", "year"])["solar_rad_mean"].cumsum() * 0.0864 * 30
    else:
        month_rad = {1:180, 2:230, 3:310, 4:420, 5:510, 6:520,
                     7:450, 8:490, 9:380, 10:290, 11:200, 12:160}
        df["누적일사량_MJm2"] = df["month"].astype(int).map(month_rad).fillna(350.0)

    logger.info("  ERA5 합성 피처 생성 완료 (%s): GDD정규화/CU_norm/ET0_mm/DIF/NDVI_proxy", crop_ko)
    return df


# ── 4. 월별 ERA5 피처를 학습 행렬에 병합 ──────────────────────────────────────

@lru_cache(maxsize=12)
def _get_era5_monthly(crop_ko: str) -> Optional[pd.DataFrame]:
    """지역별 ERA5 월별 집계 반환 (캐시). None이면 합성 사용."""
    location = _CROP_LOCATION.get(crop_ko, "충남논산")
    loc_info = LOCATIONS.get(location, {"lat": 36.5, "lon": 127.1})

    # 1순위: 기 다운로드 ERA5 CSV
    df_daily = _load_era5_csv(location)
    if df_daily is not None:
        return _aggregate_era5_daily_to_monthly(df_daily, crop_ko)

    # 2순위: NASA POWER API
    df_nasa = _fetch_nasa_power_monthly(
        lat=loc_info["lat"], lon=loc_info["lon"],
        year_start=2017, year_end=2024,
    )
    if df_nasa is not None:
        T_base, GDD_tgt = _CROP_GDD.get(crop_ko, (8.0, 900.0))
        _enrich_era5_monthly(df_nasa, T_base, GDD_tgt)
        return df_nasa

    return None  # 합성 모드로 폴백


def _aggregate_era5_daily_to_monthly(df_daily: pd.DataFrame, crop_ko: str) -> pd.DataFrame:
    """ERA5 일별 CSV → 월별 집계 + 파생 피처."""
    df = df_daily.copy()
    T_base, GDD_tgt = _CROP_GDD.get(crop_ko, (8.0, 900.0))

    # 날짜 파싱
    if "날짜" not in df.columns and "date" in df.columns:
        df["날짜"] = pd.to_datetime(df["date"])
    df["날짜"] = pd.to_datetime(df["날짜"])
    df["year"]  = df["날짜"].dt.year
    df["month"] = df["날짜"].dt.month

    # ET0 (일별 Hargreaves)
    if "ET0_mm" not in df.columns:
        if "평균기온_C" in df.columns and "최저기온_C" in df.columns:
            Ra_mj = df.get("일사량_MJm2", pd.Series(12.0, index=df.index))
            T_avg = df["평균기온_C"].fillna(15.0)
            T_min = df["최저기온_C"].fillna(8.0)
            df["ET0_mm"] = 0.0023 * Ra_mj * (T_avg + 17.8) * np.sqrt((T_avg - T_min).clip(lower=0))
        else:
            df["ET0_mm"] = 2.0

    # CU 일별
    t_min = df.get("최저기온_C", df.get("평균기온_C", pd.Series(10.0, index=df.index)))
    df["CU"] = (t_min.fillna(10.0) <= 5.0).astype(float)
    df["CU_cumsum_yr"] = df.groupby("year")["CU"].cumsum()

    # DIF 일별
    t_avg_col = "평균기온_C" if "평균기온_C" in df.columns else None
    t_min_col = "최저기온_C" if "최저기온_C" in df.columns else None
    if t_avg_col and t_min_col:
        df["DIF"] = (df[t_avg_col].fillna(15.0) - df[t_min_col].fillna(8.0)).clip(lower=0)
    else:
        df["DIF"] = 7.0

    # 월 집계
    agg_cols = {}
    for src, dst, fn in [
        ("평균기온_C",  "평균기온_C",   "mean"),
        ("최저기온_C",  "최저기온_C",   "mean"),
        ("일사량_MJm2", "일사량_MJm2",  "sum"),
        ("ET0_mm",      "ET0_mm",       "sum"),
        ("CU_cumsum_yr","CU_norm_raw",  "max"),
        ("DIF",         "DIF",          "mean"),
    ]:
        if src in df.columns:
            agg_cols[src] = (dst, fn)

    if not agg_cols:
        return pd.DataFrame()

    agg_dict = {src: pd.NamedAgg(column=src, aggfunc=fn) for src, (dst, fn) in agg_cols.items()}
    result = df.groupby(["year", "month"]).agg(**agg_dict).reset_index()
    # dst 이름으로 rename
    rename = {src: dst for src, (dst, fn) in agg_cols.items() if src != dst}
    result = result.rename(columns=rename)

    _enrich_era5_monthly(result, T_base, GDD_tgt)
    return result


def _enrich_era5_monthly(df: pd.DataFrame, T_base: float, GDD_tgt: float) -> None:
    """월별 집계 데이터에 GDD정규화, CU_norm, NDVI_proxy 추가 (in-place)."""
    # GDD 월별 → 연도별 누적 → 정규화
    if "평균기온_C" in df.columns:
        df["GDD_monthly"] = (df["평균기온_C"].fillna(15.0) - T_base).clip(lower=0) * 30
        df = df.sort_values(["year", "month"])
        df["GDD_cumsum"] = df.groupby("year")["GDD_monthly"].cumsum()
        df["GDD정규화"]  = (df["GDD_cumsum"] / GDD_tgt).clip(0, 1)
    else:
        df["GDD정규화"] = 0.5

    # CU_norm
    if "CU_norm_raw" in df.columns:
        df["CU_norm"] = ((df["CU_norm_raw"] * 5) - 300) / 800
    else:
        df["CU_norm"] = 0.0

    # NDVI 프록시
    df["NDVI_proxy"] = (0.25 + 0.55 * df.get("GDD정규화", 0.5)).clip(0.15, 0.90)

    # 누적일사량
    if "일사량_MJm2" in df.columns:
        df["누적일사량_MJm2"] = df.groupby("year")["일사량_MJm2"].cumsum()
    else:
        month_rad = {1:180, 2:230, 3:310, 4:420, 5:510, 6:520,
                     7:450, 8:490, 9:380, 10:290, 11:200, 12:160}
        df["누적일사량_MJm2"] = df["month"].map(month_rad).fillna(350.0)

    # in-place이므로 DataFrame이 이미 수정됨 (caller의 df 반영)
    # (pandas groupby 후 sort_values로 인덱스 바뀔 수 있으나 무시 — sort만 했으면 OK)


# ── 5. 공개 API: 학습 행렬에 ERA5 피처 추가 ──────────────────────────────────

_ERA5_FEATURE_COLS = [
    "GDD정규화", "CU_norm", "ET0_mm", "DIF", "NDVI_proxy", "누적일사량_MJm2",
]


def add_era5_features(
    df_train: pd.DataFrame,
    crop_ko: str,
    use_external: bool = True,
) -> pd.DataFrame:
    """학습 행렬 (farm_id × year × month)에 ERA5 파생 피처를 추가한다.

    Args:
        df_train: 기존 Stage1 학습 행렬 (farm_id, year, month 필수)
        crop_ko:  작목명 (딸기, 참외 등)
        use_external: True이면 ERA5 CSV / NASA POWER 시도; False이면 합성만 사용

    Returns:
        ERA5 피처가 추가된 DataFrame (원본 행 수 유지)
    """
    if df_train.empty:
        return df_train

    # 이미 ERA5 피처가 있으면 스킵
    if "GDD정규화" in df_train.columns:
        logger.info("  ERA5 피처 이미 존재 — 스킵")
        return df_train

    # 외부 소스 시도
    df_era5_monthly = None
    if use_external:
        df_era5_monthly = _get_era5_monthly(crop_ko)

    if df_era5_monthly is not None and not df_era5_monthly.empty:
        # year+month 기준 병합
        era5_cols = ["year", "month"] + [c for c in _ERA5_FEATURE_COLS if c in df_era5_monthly.columns]
        df_m = df_era5_monthly[era5_cols].copy()
        df_m["year"]  = pd.to_numeric(df_m["year"],  errors="coerce").astype("Int64")
        df_m["month"] = pd.to_numeric(df_m["month"], errors="coerce").astype("Int64")

        before = len(df_train)
        df_out = df_train.copy()
        df_out["year"]  = pd.to_numeric(df_out["year"],  errors="coerce").astype("Int64")
        df_out["month"] = pd.to_numeric(df_out["month"], errors="coerce").astype("Int64")
        df_out = df_out.merge(df_m, on=["year", "month"], how="left")

        # 매칭 안 된 행은 합성으로 채움
        missing_mask = df_out["GDD정규화"].isna()
        if missing_mask.any():
            logger.info("  ERA5 미매칭 %d행 → 합성 보완", missing_mask.sum())
            df_synth = _synthetic_era5_from_internal(df_out[missing_mask].copy(), crop_ko)
            for col in _ERA5_FEATURE_COLS:
                if col in df_synth.columns:
                    df_out.loc[missing_mask, col] = df_synth[col].values

        logger.info("  ERA5 피처 병합 완료: %d→%d행 (외부 소스: %s)",
                    before, len(df_out), "NASA_POWER" if df_era5_monthly is not None else "era5_csv")
        return df_out
    else:
        # 합성 모드
        logger.info("  ERA5 외부 소스 없음 — 합성 피처 사용 (%s)", crop_ko)
        return _synthetic_era5_from_internal(df_train, crop_ko)


def get_era5_feature_names() -> list[str]:
    """ERA5 파생 피처 컬럼명 목록."""
    return list(_ERA5_FEATURE_COLS)


# ── 6. CLI — ERA5 CSV 일괄 다운로드 ──────────────────────────────────────────

def download_era5_all(
    year_start: int = 2017,
    year_end: int = 2024,
    cds_key: Optional[str] = None,
) -> None:
    """CDS API를 통해 5개 지역 ERA5-Land를 순차 다운로드.

    사전 조건:
        pip install cdsapi xarray netCDF4
        ~/.cdsapirc 에 API 키 설정 또는 cds_key 파라미터 전달

    결과: data/weather/era5/era5_{지역}_일별.csv (5개 파일)
    """
    try:
        import cdsapi
        import xarray as xr
    except ImportError:
        raise RuntimeError("cdsapi, xarray, netCDF4 패키지를 먼저 설치하세요: "
                           "pip install cdsapi xarray netCDF4")

    os.makedirs(_ERA5_DIR, exist_ok=True)

    for location, loc in LOCATIONS.items():
        nc_path = _ERA5_DIR / f"era5_{location}.nc"
        csv_path = _ERA5_DIR / f"era5_{location}_일별.csv"

        if csv_path.exists():
            logger.info("[%s] CSV 이미 존재 — 건너뜀", location)
            continue

        c = cdsapi.Client(url="https://cds.climate.copernicus.eu/api",
                          key=cds_key or "")
        logger.info("[%s] ERA5-Land 다운로드 시작 (%d~%d)...", location, year_start, year_end)
        years = [str(y) for y in range(year_start, year_end + 1)]
        c.retrieve(
            "reanalysis-era5-land",
            {
                "variable": [
                    "2m_temperature",
                    "minimum_2m_temperature_since_previous_post_processing",
                    "surface_solar_radiation_downwards",
                    "total_precipitation",
                    "potential_evaporation",
                ],
                "year": years,
                "month": [f"{m:02d}" for m in range(1, 13)],
                "day":   [f"{d:02d}" for d in range(1, 32)],
                "time":  ["00:00", "06:00", "12:00", "18:00"],
                "area":  loc["area"],
                "data_format": "netcdf",
            },
            str(nc_path),
        )

        # NetCDF → CSV 변환 (era5_download_run.py의 nc_to_csv 재현)
        ds    = xr.open_dataset(nc_path)
        ds_pt = ds.sel(latitude=loc["lat"], longitude=loc["lon"], method="nearest")
        df_h  = ds_pt.to_dataframe().reset_index()

        rename = {}
        for col in df_h.columns:
            cl = col.lower()
            if col in ("t2m", "temperature_2m"):           rename[col] = "t2m"
            elif "mn2t" in cl or "minimum_2m" in cl:       rename[col] = "mn2t"
            elif "ssrd" in cl:                             rename[col] = "ssrd"
            elif col in ("tp", "total_precipitation"):     rename[col] = "tp"
            elif col in ("pev", "potential_evaporation"):  rename[col] = "pev"
        df_h = df_h.rename(columns=rename)

        agg_map = {v: fn for v, fn in [("t2m","mean"),("mn2t","min"),("ssrd","sum"),
                                        ("tp","sum"),("pev","sum")] if v in df_h.columns}
        df_d = (df_h.groupby(df_h["time"].dt.date).agg(agg_map)
                .reset_index().rename(columns={"time": "날짜"}))

        if "t2m"  in df_d: df_d["평균기온_C"]   = df_d["t2m"]  - 273.15
        if "mn2t" in df_d: df_d["최저기온_C"]   = df_d["mn2t"] - 273.15
        if "ssrd" in df_d: df_d["일사량_MJm2"]  = df_d["ssrd"] / 1_000_000
        if "tp"   in df_d: df_d["강수량_mm"]    = df_d["tp"]   * 1000
        if "pev"  in df_d: df_d["ET0_mm"]       = df_d["pev"].abs() * 1000
        df_d["DIF"] = df_d.get("평균기온_C", 0) - df_d.get("최저기온_C", 0)

        df_d.to_csv(csv_path, index=False, encoding="utf-8-sig")
        logger.info("[%s] CSV 저장 완료: %s (%d행)", location, csv_path.name, len(df_d))
        nc_path.unlink(missing_ok=True)   # NC 파일 삭제 (용량 절약)


if __name__ == "__main__":
    import sys
    cds_key = sys.argv[1] if len(sys.argv) > 1 else None
    download_era5_all(cds_key=cds_key)
