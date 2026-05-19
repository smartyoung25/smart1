"""Parquet 학습 캐시 빌드 스크립트.

ZIP 파일에서 월별 집계 데이터를 추출해 .cache/training/ 에 Parquet으로 저장.
이후 train_stage1_growth.py / train_stage2_yield.py 실행 시 캐시를 재사용하여
대용량 ZIP 재로딩 없이 고속 학습 가능.

실행:
    python scripts/build_training_cache.py            # 전체 작목
    python scripts/build_training_cache.py --crop 딸기
    python scripts/build_training_cache.py --force    # 기존 캐시 덮어쓰기
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.crop_config import (
    CROP_CONFIGS, ENV_COLS, ENV_HARD_BOUNDS, DATA_DIR, YEARS,
)

CACHE_DIR = ROOT / ".cache" / "training"


def _norm_farm_id(v: str) -> str:
    try:
        return str(int(float(str(v).strip())))
    except (ValueError, OverflowError):
        return str(v).strip()


def clip_iqr(s: pd.Series, factor: float = 1.5) -> pd.Series:
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    return s.clip(lower=q1 - factor * (q3 - q1), upper=q3 + factor * (q3 - q1))


def _norm_keys(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["year", "month"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float").astype("Int64")
    if "farm_id" in df.columns:
        df["farm_id"] = df["farm_id"].astype(str).str.strip().apply(_norm_farm_id)
    return df


def _read_crop_rows_chunked(year: int, crop_ko: str) -> list[pd.DataFrame]:
    """ZIP 내 모든 CSV에서 해당 작목 행만 청크 읽기로 추출."""
    zp = DATA_DIR / f"스마트팜_{year}.zip"
    if not zp.exists():
        return []
    frames: list[pd.DataFrame] = []
    with zipfile.ZipFile(zp) as zf:
        for info in zf.infolist():
            if not info.filename.lower().endswith(".csv"):
                continue
            try:
                raw = zf.read(info.filename)
                if info.file_size > 10_000_000:
                    # 대용량: 청크 읽기
                    buf_frames = []
                    for chunk in pd.read_csv(
                        io.BytesIO(raw), encoding="euc-kr",
                        low_memory=True, chunksize=50_000,
                    ):
                        if "품목" in chunk.columns:
                            dc = chunk[chunk["품목"].astype(str).str.strip() == crop_ko]
                            if len(dc) > 0:
                                buf_frames.append(dc.copy())
                    if buf_frames:
                        frames.append(pd.concat(buf_frames, ignore_index=True))
                else:
                    df = pd.read_csv(io.BytesIO(raw), encoding="euc-kr", low_memory=False)
                    if "품목" in df.columns:
                        dc = df[df["품목"].astype(str).str.strip() == crop_ko].copy()
                        if len(dc) > 0:
                            frames.append(dc)
            except Exception as exc:
                logger.debug("  [skip] %s/%s: %s", year, info.filename, exc)
    return frames


def build_env_cache(crop_ko: str, force: bool = False) -> Path:
    """환경 월별 집계 → env_{crop}.parquet"""
    cp = CACHE_DIR / f"env_{crop_ko}.parquet"
    if cp.exists() and not force:
        logger.info("  [env] 캐시 존재 스킵: %s", cp.name)
        return cp

    all_frames = []
    for year in YEARS:
        t = __import__("time").time()
        rows = _read_crop_rows_chunked(year, crop_ko)
        env_f = [f for f in rows if "측정시간" in f.columns]
        if not env_f:
            logger.info("  [env] %d년 없음", year)
            continue
        df = pd.concat(env_f, ignore_index=True)
        df["year"] = year
        time_col = "측정시간" if "측정시간" in df.columns else "측정일시"
        df["dt"] = pd.to_datetime(df[time_col], errors="coerce")
        df["month"] = df["dt"].dt.month
        farm_col = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
        df["farm_id"] = df[farm_col].astype(str).str.strip().apply(_norm_farm_id) \
            if farm_col else "unknown"
        for orig, canon in ENV_COLS.items():
            if orig in df.columns:
                df[canon] = pd.to_numeric(df[orig], errors="coerce")
                lo, hi = ENV_HARD_BOUNDS.get(canon, (-1e9, 1e9))
                df.loc[~df[canon].between(lo, hi), canon] = np.nan
        all_frames.append(df)
        logger.info("  [env] %d년 %d행 (%.1fs)", year, len(df), __import__("time").time() - t)

    if not all_frames:
        logger.warning("  [env] %s 환경 데이터 없음", crop_ko)
        return cp

    # 연도별로 이미 분리된 DataFrame을 각각 집계한 뒤 concat — 메모리 효율↑
    agg_frames = []
    for df in all_frames:
        env_vars = [c for c in ENV_COLS.values() if c in df.columns]
        for col in env_vars:
            df[col] = clip_iqr(df[col])
        agg = (df.groupby(["farm_id", "year", "month"])
               .agg({col: ["mean", "std"] for col in env_vars})
               .reset_index())
        agg.columns = ["_".join(c).strip("_") if c[1] else c[0] for c in agg.columns]
        agg_frames.append(agg)
    result = _norm_keys(pd.concat(agg_frames, ignore_index=True))
    result.to_parquet(cp, index=False)
    logger.info("  [env] 저장: %s (%d행)", cp.name, len(result))
    return cp


def build_growth_cache(crop_ko: str, growth_cols: list[str], force: bool = False) -> Path:
    """생육 월별 집계 → growth_{crop}.parquet"""
    cp = CACHE_DIR / f"growth_{crop_ko}.parquet"
    if cp.exists() and not force:
        logger.info("  [growth] 캐시 존재 스킵: %s", cp.name)
        return cp

    all_frames = []
    for year in YEARS:
        rows = _read_crop_rows_chunked(year, crop_ko)
        g_f = [f for f in rows
               if "조사일자" in f.columns and "측정시간" not in f.columns
               and any(c in f.columns for c in growth_cols)]
        if not g_f:
            continue
        df = pd.concat(g_f, ignore_index=True)
        df["dt"] = pd.to_datetime(df["조사일자"], errors="coerce")
        df["year"] = year
        df["month"] = df["dt"].dt.month
        farm_col = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
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
        logger.warning("  [growth] %s 생육 데이터 없음", crop_ko)
        return cp

    result = _norm_keys(pd.concat(all_frames, ignore_index=True))
    result.to_parquet(cp, index=False)
    logger.info("  [growth] 저장: %s (%d행)", cp.name, len(result))
    return cp


def build_production_cache(crop_ko: str, force: bool = False) -> Path:
    """수확량 월별 집계 → s2_prod_{crop}.parquet (면적 미적용 yield_kg)"""
    cp = CACHE_DIR / f"s2_prod_{crop_ko}.parquet"
    if cp.exists() and not force:
        logger.info("  [prod] 캐시 존재 스킵: %s", cp.name)
        return cp

    all_frames = []
    for year in YEARS:
        rows = _read_crop_rows_chunked(year, crop_ko)
        prod_f = [f for f in rows
                  if "출하일자" in f.columns and "총출하량" in f.columns]
        if not prod_f:
            continue
        df = pd.concat(prod_f, ignore_index=True)
        df["dt"] = pd.to_datetime(df["출하일자"], errors="coerce")
        df["year"] = year
        df["month"] = df["dt"].dt.month
        farm_col = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
        df["farm_id"] = df[farm_col].astype(str).str.strip().apply(_norm_farm_id) \
            if farm_col else "unknown"
        df["총출하량"] = pd.to_numeric(df.get("총출하량", 0), errors="coerce").fillna(0).clip(lower=0)
        agg = (df.groupby(["farm_id", "year", "month"])
               .agg({"총출하량": "sum"})
               .reset_index()
               .rename(columns={"총출하량": "yield_kg"}))
        all_frames.append(agg)

    if not all_frames:
        logger.warning("  [prod] %s 수확량 데이터 없음", crop_ko)
        return cp

    result = _norm_keys(pd.concat(all_frames, ignore_index=True))
    result.to_parquet(cp, index=False)
    logger.info("  [prod] 저장: %s (%d행)", cp.name, len(result))
    return cp


def main():
    parser = argparse.ArgumentParser(description="Parquet 학습 캐시 빌드")
    parser.add_argument("--crop", default="all", help="작목명 또는 'all'")
    parser.add_argument("--force", action="store_true", help="기존 캐시 덮어쓰기")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    crops = list(CROP_CONFIGS.keys()) if args.crop == "all" else [args.crop]

    import time
    t0 = time.time()
    for crop_ko in crops:
        config = CROP_CONFIGS.get(crop_ko)
        if not config:
            logger.warning("지원하지 않는 작목: %s", crop_ko)
            continue
        logger.info("=" * 50)
        logger.info("캐시 빌드: %s", crop_ko)
        logger.info("=" * 50)
        build_env_cache(crop_ko, force=args.force)
        build_growth_cache(crop_ko, config.growth_cols, force=args.force)
        build_production_cache(crop_ko, force=args.force)
        # Stage2 캐시도 동일 경로에 저장 (s2_ prefix)
        s2_env = CACHE_DIR / f"s2_env_{crop_ko}.parquet"
        s2_growth = CACHE_DIR / f"s2_growth_{crop_ko}.parquet"
        if not s2_env.exists() or args.force:
            env_cp = CACHE_DIR / f"env_{crop_ko}.parquet"
            if env_cp.exists():
                import shutil
                shutil.copy(env_cp, s2_env)
                logger.info("  [s2_env] env 캐시 복사: %s", s2_env.name)
        if not s2_growth.exists() or args.force:
            g_cp = CACHE_DIR / f"growth_{crop_ko}.parquet"
            if g_cp.exists():
                import shutil
                shutil.copy(g_cp, s2_growth)
                logger.info("  [s2_growth] growth 캐시 복사: %s", s2_growth.name)

    logger.info("\n=== 캐시 빌드 완료 (총 %.1fs) ===", time.time() - t0)
    logger.info("캐시 디렉터리: %s", CACHE_DIR)
    for f in sorted(CACHE_DIR.glob("*.parquet")):
        sz = f.stat().st_size // 1024
        logger.info("  %s  (%dKB)", f.name, sz)


if __name__ == "__main__":
    main()
