"""Wageningen Autonomous Greenhouse Challenge 데이터 어댑터.

Wageningen 4TU 공개 데이터셋을 농진청 RDA 포맷으로 변환.
등록 불필요, 완전 무료.

지원 데이터셋:
  1st Edition (2018): 오이     DOI 10.4121/uuid:e4987a7b-04dd-4c89-9b18-883aad30ba9a
  2nd Edition (2019): 방울토마토 DOI 10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7
  4th Edition (2024): 드워프토마토 DOI 10.4121/fa102772-32db-4b30-bace-12f2016722ce

다운로드 방법:
  1. 아래 download_wageningen() 함수 직접 호출 (자동 다운로드)
  2. 또는 수동: https://data.4tu.nl/ 에서 zip 다운로드 후 wageningen_dir에 저장

Wageningen 2nd Edition 컬럼 (방울토마토, 5분 간격):
  time, comp_nr, air_temp, air_hum, co2_dose, light_sum, fruit_harvest_weight,
  fruit_harvest_num, setpoints_temp, setpoints_co2, ...

사용법:
  # 자동 다운로드 + 변환
  from scripts.data_integration.wageningen_adapter import download_and_convert
  df_env, df_prod = download_and_convert(edition=2, out_dir='기초자료/wageningen')

  # 이미 다운로드된 경우
  from scripts.data_integration.wageningen_adapter import convert_wageningen
  result = convert_wageningen('기초자료/wageningen/2nd_edition', edition=2)
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Wageningen 데이터셋 다운로드 URL (4TU.ResearchData 직접 링크)
_DATASET_URLS = {
    1: {
        "url": "https://data.4tu.nl/file/e4987a7b-04dd-4c89-9b18-883aad30ba9a/1",
        "crop_ko": "오이",
        "year": 2018,
        "description": "1st Edition — Cucumber (2018, 4개월)",
    },
    2: {
        "url": "https://data.4tu.nl/file/88d22c60-21b3-4ea8-90db-20249a5be2a7/1",
        "crop_ko": "방울토마토",
        "year": 2019,
        "description": "2nd Edition — Cherry Tomato (2019, 2개월)",
    },
    4: {
        "url": "https://data.4tu.nl/file/fa102772-32db-4b30-bace-12f2016722ce/1",
        "crop_ko": "완숙토마토",
        "year": 2024,
        "description": "4th Edition — Dwarf Tomato (2024)",
    },
}

# Wageningen 컬럼 → 내부 컬럼 매핑
_ENV_MAP_2ND = {
    "air_temp":         "temp_internal",
    "air_hum":          "humidity_int",
    "co2_dose":         "co2_ppm",      # ppm
    "co2_concentration":"co2_ppm",
    "light_sum":        "solar_rad",    # J/cm² → W/m² 변환 필요
    "radiation":        "solar_rad",
    "par":              "solar_rad",    # µmol → W/m²
    "outside_temp":     "temp_external",
    "outside_hum":      "temp_external",
}
_PROD_MAP_2ND = {
    "fruit_harvest_weight": "yield_kg",
    "harvest_weight_gr":    "yield_kg",   # 그램 → kg 변환
    "cumul_harvest_weight": "yield_kg",
}


def _safe_read(path: Path) -> pd.DataFrame:
    for enc in ["utf-8", "utf-8-sig", "latin-1"]:
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except Exception:
            continue
    raise ValueError(f"읽기 실패: {path}")


def _normalize_col(c: str) -> str:
    import re
    return re.sub(r"[\s\-/]", "_", c.lower().strip())


def download_and_convert(
    edition: int,
    out_dir: Path,
    force: bool = False,
) -> dict[str, pd.DataFrame]:
    """Wageningen 데이터 자동 다운로드 + 변환.

    Args:
        edition: 1, 2, 4
        out_dir: 저장 디렉토리
        force: True이면 이미 있어도 재다운로드

    Returns:
        {'env': df_env, 'prod': df_prod}
    """
    try:
        import urllib.request as _ur
    except ImportError:
        raise ImportError("urllib.request 필요 (표준 라이브러리)")

    info = _DATASET_URLS.get(edition)
    if info is None:
        raise ValueError(f"지원하지 않는 버전: {edition}. 지원: {list(_DATASET_URLS.keys())}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"wageningen_ed{edition}.zip"

    # 다운로드
    if not zip_path.exists() or force:
        logger.info("[Wageningen] 다운로드 중... %s", info["description"])
        logger.info("  URL: %s", info["url"])
        try:
            _ur.urlretrieve(info["url"], zip_path)
            logger.info("  완료: %s (%.1f MB)", zip_path.name,
                        zip_path.stat().st_size / 1e6)
        except Exception as e:
            logger.error("  다운로드 실패: %s", e)
            logger.info("  수동 다운로드: https://data.4tu.nl/ 에서 직접 내려받아")
            logger.info("  %s 에 저장하세요.", zip_path)
            raise

    # 압축 해제
    extract_dir = out_dir / f"ed{edition}"
    if not extract_dir.exists() or force:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
        logger.info("[Wageningen] 압축 해제 완료: %s", extract_dir)

    return convert_wageningen(extract_dir, edition=edition, out_dir=out_dir,
                               crop_ko=info["crop_ko"], year=info["year"])


def convert_wageningen(
    data_dir: Path,
    edition: int = 2,
    crop_ko: str = "방울토마토",
    year: int = 2019,
    out_dir: Optional[Path] = None,
) -> dict[str, pd.DataFrame]:
    """압축 해제된 Wageningen 데이터 → RDA 포맷 변환.

    Wageningen 데이터 특성:
    - 5분 간격 센서 데이터 (매우 상세)
    - 온실 구획(compartment) 별 구분
    - 일별 수확량 기록
    - farm_id = wageningen_{edition}_{comp_nr}

    Args:
        data_dir: 압축 해제 폴더
        edition: 데이터셋 버전
        crop_ko: 한국어 작목명
        year: 데이터 연도
        out_dir: 저장 경로

    Returns:
        {'env': df_env, 'prod': df_prod, 'env_monthly': df_monthly}
    """
    data_dir = Path(data_dir)
    csv_files = list(data_dir.rglob("*.csv"))
    logger.info("[Wageningen] %d개 CSV in %s", len(csv_files), data_dir)

    env_frames, prod_frames = [], []

    for csv_path in csv_files:
        try:
            df = _safe_read(csv_path)
        except Exception as e:
            logger.warning("  스킵 %s: %s", csv_path.name, e)
            continue

        if df.empty:
            continue

        # 컬럼명 정규화
        df.columns = [_normalize_col(c) for c in df.columns]

        # 시간 컬럼 감지
        time_col = next((c for c in df.columns
                         if any(kw in c for kw in ["time", "date", "timestamp"])), None)
        if time_col:
            df[time_col] = pd.to_datetime(df[time_col], errors="coerce")

        # 수확량 컬럼 감지
        has_yield = any(
            any(kw in c for kw in ["harvest", "yield", "fruit_weight"])
            for c in df.columns
        )

        if has_yield:
            prod_frames.append((csv_path, df, time_col))
        else:
            env_frames.append((csv_path, df, time_col))

    # ── 환경 변환 ─────────────────────────────────────────────────────────────
    all_env = []
    for path, df, tcol in env_frames:
        # 구획 번호 (comp_nr, greenhouse_id 등)
        comp_col = next((c for c in df.columns if "comp" in c or "greenhouse" in c
                         or "section" in c), None)

        # 환경 컬럼 매핑
        rename_map: dict[str, str] = {}
        for orig_col in df.columns:
            for src_key, target in _ENV_MAP_2ND.items():
                if src_key in orig_col:
                    rename_map[orig_col] = target
                    break

        if not rename_map:
            continue

        df = df.rename(columns=rename_map)

        # Light J/cm² → W/m² (1 J/cm² per 5min = 1e4/300 W/m² = 33.3 W/m²)
        if "solar_rad" in df.columns:
            med = df["solar_rad"].median()
            if med and med < 100:  # J/cm² 범위
                df["solar_rad"] = df["solar_rad"] * 33.3
            elif med and med > 100000:  # µmol 누적일 경우
                df["solar_rad"] = df["solar_rad"] / 2000.0

        # 월별 집계 → RDA 포맷 행렬 구성
        if tcol and tcol in df.columns:
            df["year"] = df[tcol].dt.year.fillna(year).astype(int)
            df["month"] = df[tcol].dt.month

        # comp별 farm_id
        if comp_col and comp_col in df.columns:
            df["farm_id"] = df[comp_col].astype(str).apply(
                lambda x: f"wag{edition}_comp{x}"
            )
        else:
            df["farm_id"] = f"wag{edition}_all"

        all_env.append(df)

    df_env_raw = pd.concat(all_env, ignore_index=True) if all_env else pd.DataFrame()

    # 월별 집계 (RDA 포맷에 맞춤)
    df_env_monthly = pd.DataFrame()
    if not df_env_raw.empty and "year" in df_env_raw.columns:
        env_num_cols = [c for c in df_env_raw.columns
                        if c in ("temp_internal", "humidity_int", "co2_ppm",
                                 "solar_rad", "temp_external")]
        agg_dict = {}
        for col in env_num_cols:
            if col in df_env_raw.columns:
                agg_dict[col] = "mean"

        if agg_dict and "farm_id" in df_env_raw.columns:
            df_env_monthly = (
                df_env_raw.groupby(["farm_id", "year", "month"])
                .agg(**{col: (col, fn) for col, fn in agg_dict.items()})
                .reset_index()
            )
            df_env_monthly["source"] = f"wageningen_ed{edition}"
            logger.info("[Wageningen] 월별 환경 집계: %d행", len(df_env_monthly))

    # ── 생산 변환 ──────────────────────────────────────────────────────────────
    all_prod = []
    for path, df, tcol in prod_frames:
        rename_map: dict[str, str] = {}
        for orig_col in df.columns:
            for src_key, target in _PROD_MAP_2ND.items():
                if src_key in orig_col:
                    rename_map[orig_col] = target
                    break

        if "yield_kg" not in rename_map.values():
            continue

        df = df.rename(columns=rename_map)

        # 그램 → kg 변환 (값이 1000 이상이면 그램)
        if "yield_kg" in df.columns:
            med = df["yield_kg"].median()
            if med and med > 500:
                df["yield_kg"] = df["yield_kg"] / 1000.0

        comp_col = next((c for c in df.columns if "comp" in c), None)
        if comp_col:
            df["farm_id"] = df[comp_col].astype(str).apply(
                lambda x: f"wag{edition}_comp{x}"
            )
        else:
            df["farm_id"] = f"wag{edition}_all"

        if tcol and tcol in df.columns:
            df["year"] = df[tcol].dt.year.fillna(year).astype(int)
            df["month"] = df[tcol].dt.month

        df["품목"] = crop_ko
        # Wageningen 실험 면적 (compartment 당 약 100~200m²)
        df["area_m2"] = 144.0  # 2nd edition: 4×36m² compartments
        df["source"] = f"wageningen_ed{edition}"
        all_prod.append(df)

    df_prod = pd.concat(all_prod, ignore_index=True) if all_prod else pd.DataFrame()

    # 월별 생산 집계
    df_prod_monthly = pd.DataFrame()
    if not df_prod.empty and "year" in df_prod.columns:
        df_prod_monthly = (
            df_prod.groupby(["farm_id", "year", "month"])
            .agg(yield_kg=("yield_kg", "sum"), area_m2=("area_m2", "first"))
            .reset_index()
        )
        df_prod_monthly["품목"] = crop_ko
        df_prod_monthly["source"] = f"wageningen_ed{edition}"
        logger.info("[Wageningen] 월별 생산 집계: %d행", len(df_prod_monthly))

    # ── 저장 ──────────────────────────────────────────────────────────────────
    result = {
        "env": df_env_raw,
        "env_monthly": df_env_monthly,
        "prod": df_prod,
        "prod_monthly": df_prod_monthly,
    }

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if not df_env_monthly.empty:
            p = out_dir / f"환경_wageningen_ed{edition}.csv"
            df_env_monthly.to_csv(p, index=False, encoding="utf-8-sig")
            logger.info("  저장: %s", p.name)
        if not df_prod_monthly.empty:
            p = out_dir / f"생산_wageningen_ed{edition}.csv"
            df_prod_monthly.to_csv(p, index=False, encoding="utf-8-sig")
            logger.info("  저장: %s", p.name)

    return result
