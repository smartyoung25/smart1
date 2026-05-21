"""AIHub 스마트팜 데이터셋 어댑터.

AIHub 지능형 스마트팜 데이터셋을 농진청 RDA 포맷(환경/생육/생산 CSV)으로 변환.

지원 데이터셋:
  #534  지능형 스마트팜(토마토)
  #535  지능형 스마트팜(파프리카)
  #71523 지능형 스마트팜(딸기/오이)

AIHub 다운로드 방법:
  1. https://aihub.or.kr 회원가입 → 로그인
  2. 위 데이터셋 페이지에서 [데이터 신청] 클릭 (승인 1~3일)
  3. 승인 후 다운로드 → 압축 해제 → 아래 경로에 배치:
       기초자료/aihub/토마토/        (완숙토마토)
       기초자료/aihub/파프리카/
       기초자료/aihub/딸기/

사용법:
    python scripts/data_integration/run_integration.py --source aihub --crop 파프리카

AIHub 센서 CSV 컬럼 (예상):
    측정일시, 농장ID, 내부온도, 내부습도, CO2농도, 일사량, EC, 지온, 수확량, 재배면적
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# AIHub → 내부 컬럼 매핑 후보 (복수 이름 허용 — 버전별 차이 대응)
_ENV_COL_MAP = {
    "내부온도":     "temp_internal",
    "내부_온도":    "temp_internal",
    "온도_내부":    "temp_internal",
    "air_temp":    "temp_internal",
    "temperature": "temp_internal",
    "내부습도":     "humidity_int",
    "내부_습도":    "humidity_int",
    "습도_내부":    "humidity_int",
    "humidity":    "humidity_int",
    "co2농도":      "co2_ppm",
    "co2_농도":     "co2_ppm",
    "co2":         "co2_ppm",
    "이산화탄소":   "co2_ppm",
    "일사량":       "solar_rad",
    "광량":         "solar_rad",
    "solar_rad":   "solar_rad",
    "ppfd":         "solar_rad",   # µmol/m²/s → 근사 W/m²로 환산
    "ec":           "ec_dsm",
    "ec농도":       "ec_dsm",
    "전기전도도":   "ec_dsm",
    "지온":         "soil_temp",
    "배지온도":     "soil_temp",
    "외부온도":     "temp_external",
    "외부_온도":    "temp_external",
    "온도_외부":    "temp_external",
}
_PROD_COL_MAP = {
    "수확량":     "yield_kg",
    "수확중량":   "yield_kg",
    "총수확량":   "yield_kg",
    "harvest_weight": "yield_kg",
    "재배면적":   "area_m2",
    "면적":       "area_m2",
    "area":       "area_m2",
}
_META_COL_MAP = {
    "농장id":     "farm_id",
    "농장_id":    "farm_id",
    "farm_id":    "farm_id",
    "작기번호":   "season_no",
    "작기":       "season_no",
    "품목":       "crop_name",
    "품종":       "variety",
    "정식일":     "plant_date",
    "이식일":     "plant_date",
}
# 작목 한글 → 영문 키
_CROP_EN = {
    "딸기": "strawberry", "토마토": "tomato", "완숙토마토": "tomato",
    "방울토마토": "cherry_tomato", "참외": "melon", "파프리카": "paprika",
    "오이": "cucumber",
}
# RDA 출력 폴더 이름
_AIHUB_SOURCE_TAG = "aihub"


def _norm_col(c: str) -> str:
    """컬럼 이름 정규화: 소문자, 공백·특수문자 제거."""
    return re.sub(r"[\s\(\)\[\]_\-/]", "", str(c).lower())


def _map_columns(df: pd.DataFrame, col_map: dict) -> dict[str, str]:
    """df 컬럼 → 내부 이름 매핑 사전 반환."""
    norm_map = {_norm_col(k): v for k, v in col_map.items()}
    result: dict[str, str] = {}
    for col in df.columns:
        nc = _norm_col(col)
        if nc in norm_map:
            result[col] = norm_map[nc]
    return result


def _detect_time_col(df: pd.DataFrame) -> Optional[str]:
    for c in df.columns:
        nc = _norm_col(c)
        if any(kw in nc for kw in ["측정일시", "datetime", "timestamp", "date", "time", "일자"]):
            return c
    return None


def _detect_farm_col(df: pd.DataFrame) -> Optional[str]:
    for c in df.columns:
        nc = _norm_col(c)
        if any(kw in nc for kw in ["농장id", "farmid", "farm_id", "농장번호", "farmno"]):
            return c
    return None


def _safe_read_csv(path: Path) -> pd.DataFrame:
    for enc in ["utf-8-sig", "utf-8", "euc-kr", "cp949"]:
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(f"읽기 실패: {path}")


def convert_aihub_to_rda(
    aihub_dir: Path,
    crop_ko: str,
    out_dir: Optional[Path] = None,
    year_override: Optional[int] = None,
) -> dict[str, pd.DataFrame]:
    """AIHub 폴더 → RDA 포맷 환경/생육/생산 DataFrame 변환.

    Args:
        aihub_dir: AIHub 다운로드 압축 해제 폴더
        crop_ko: 한국어 작목명 ('파프리카', '딸기' 등)
        out_dir: 저장 경로 (None이면 저장 안 함)
        year_override: 연도 강제 지정 (파일에 연도 없을 때)

    Returns:
        {'env': df_env, 'growth': df_growth, 'prod': df_prod}
    """
    aihub_dir = Path(aihub_dir)
    if not aihub_dir.exists():
        raise FileNotFoundError(f"AIHub 폴더 없음: {aihub_dir}")

    # CSV 파일 수집
    csv_files = list(aihub_dir.rglob("*.csv"))
    if not csv_files:
        raise ValueError(f"CSV 파일 없음: {aihub_dir}")
    logger.info("[AIHub] %d개 CSV 발견 in %s", len(csv_files), aihub_dir)

    # 파일을 환경/생육/생산으로 분류
    env_frames, growth_frames, prod_frames = [], [], []

    for csv_path in csv_files:
        try:
            df = _safe_read_csv(csv_path)
        except Exception as e:
            logger.warning("  스킵 %s: %s", csv_path.name, e)
            continue

        if df.empty:
            continue

        norm_cols = [_norm_col(c) for c in df.columns]

        # 분류 기준: 수확량 컬럼 존재 → 생산, 생육 지표(초장, 엽수 등) → 생육, 나머지 → 환경
        has_yield = any(
            any(kw in nc for kw in ["수확량", "수확중량", "harvestweight"])
            for nc in norm_cols
        )
        has_growth = any(
            any(kw in nc for kw in ["초장", "엽수", "줄기직경", "stemdia", "leafcount"])
            for nc in norm_cols
        )

        if has_yield:
            prod_frames.append((csv_path, df))
        elif has_growth:
            growth_frames.append((csv_path, df))
        else:
            env_frames.append((csv_path, df))

    logger.info("  분류: 환경=%d, 생육=%d, 생산=%d 파일",
                len(env_frames), len(growth_frames), len(prod_frames))

    # ── 환경 DataFrame 변환 ────────────────────────────────────────────────────
    env_rows = []
    for path, df in env_frames:
        col_map = _map_columns(df, _ENV_COL_MAP)
        time_col = _detect_time_col(df)
        farm_col = _detect_farm_col(df)
        if not col_map or time_col is None:
            logger.debug("  환경 컬럼 매핑 실패: %s", path.name)
            continue

        df = df.rename(columns=col_map)
        # 시간 파싱
        df["측정시각"] = pd.to_datetime(df[time_col], errors="coerce")
        df["연도"] = df["측정시각"].dt.year.fillna(year_override or 2023).astype(int)
        df["월"] = df["측정시각"].dt.month

        # farm_id
        if farm_col:
            df["농장ID"] = df[farm_col].astype(str).apply(
                lambda x: f"aihub_{x}"
            )
        else:
            df["농장ID"] = f"aihub_{path.stem}"

        # PPFD → W/m² 근사 (1 µmol/m²/s ≈ 0.22 W/m² for white LED)
        if "solar_rad" in df.columns:
            median_val = df["solar_rad"].median()
            if median_val and median_val > 3000:  # µmol 범위
                df["solar_rad"] = df["solar_rad"] * 0.22
                logger.info("  PPFD → W/m² 변환 적용 (×0.22)")

        env_rows.append(df)

    df_env = pd.concat(env_rows, ignore_index=True) if env_rows else pd.DataFrame()

    # ── 생산 DataFrame 변환 ───────────────────────────────────────────────────
    prod_rows = []
    for path, df in prod_frames:
        col_map = _map_columns(df, _PROD_COL_MAP)
        time_col = _detect_time_col(df)
        farm_col = _detect_farm_col(df)
        if "yield_kg" not in col_map.values():
            logger.debug("  생산 수확량 컬럼 없음: %s", path.name)
            continue

        df = df.rename(columns=col_map)
        if time_col:
            df["측정일자"] = pd.to_datetime(df[time_col], errors="coerce")
            df["연도"] = df["측정일자"].dt.year.fillna(year_override or 2023).astype(int)
            df["월"] = df["측정일자"].dt.month

        if farm_col:
            df["농장ID"] = df[farm_col].astype(str).apply(lambda x: f"aihub_{x}")
        else:
            df["농장ID"] = f"aihub_{path.stem}"

        df["품목"] = crop_ko
        if "area_m2" not in df.columns:
            df["area_m2"] = 1000.0   # 기본값

        prod_rows.append(df)

    df_prod = pd.concat(prod_rows, ignore_index=True) if prod_rows else pd.DataFrame()

    results = {"env": df_env, "growth": pd.DataFrame(), "prod": df_prod}

    # ── 저장 ──────────────────────────────────────────────────────────────────
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for key, frame in results.items():
            if not frame.empty:
                save_path = out_dir / f"{key}_{_AIHUB_SOURCE_TAG}_{crop_ko}.csv"
                frame.to_csv(save_path, index=False, encoding="utf-8-sig")
                logger.info("  저장: %s (%d행)", save_path.name, len(frame))

    logger.info("[AIHub] 변환 완료 — 환경=%d행, 생산=%d행",
                len(df_env), len(df_prod))
    return results
