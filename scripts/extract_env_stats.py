"""환경 통계 추출 스크립트 — 농진청 5년 패널 (2018~2022)

입력 : 기초자료/.../스마트팜_{year}/환경_{year}/환경_{year}.csv  (5개)
       기초자료/.../스마트팜_{year}/생산_{year}/생산_{year}.csv   (5개, 수확량 상관용)
출력 : api/data/env_stats.json

구조:
{
  "딸기": {
    "월별_분포": {
      "1": {"temp_internal": {"mean": 17.2, "p25": 15.1, "p75": 19.3, "p95": 21.5}},
      ...
    },
    "최적_범위": {
      "temp_internal": [15.0, 20.0],   ← P25~P75 전체 기간 기준
      ...
    },
    "조정_델타": {
      "temp_internal": [−2.0, −1.0, +1.0, +2.0],   ← 최적범위 폭의 25% 단위
      ...
    },
    "수확량_상관": {
      "temp_internal": 0.41,   ← Pearson r (env 월평균 vs 출하량)
      ...
    }
  },
  ...
}

실행:
    python scripts/extract_env_stats.py
"""
from __future__ import annotations

import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

# ── 경로 설정 ────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "기초자료" / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터"
OUT_PATH = ROOT / "api" / "data" / "env_stats.json"
YEARS    = [2018, 2019, 2020, 2021, 2022]

# ── 컬럼 매핑: CSV 원본명 → canonical_name ───────────────────────────────────
ENV_COL_MAP = {
    "온도_내부":       "temp_internal",
    "상대습도_내부":   "humidity_int",
    "잔존CO2":        "co2_ppm",
    "토양온도":        "soil_temp",
    "일사량_외부":     "solar_rad",
    "온도_외부":       "temp_external",
    "풍속_외부":       "wind_speed_ext",
}

# ── 유효 범위 (이상치 제거용) ─────────────────────────────────────────────────
VALID_RANGES = {
    "temp_internal":  (-5.0,  55.0),
    "humidity_int":   (0.0,  100.0),
    "co2_ppm":        (0.0, 5000.0),
    "soil_temp":      (-5.0,  50.0),
    "solar_rad":      (0.0, 1500.0),
    "temp_external":  (-20.0, 45.0),
    "wind_speed_ext": (0.0,   30.0),
}

# ── 지원 작목 ────────────────────────────────────────────────────────────────
TARGET_CROPS = {"딸기", "방울토마토", "완숙토마토", "오이", "참외"}


def _decode_zip_name(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("euc-kr", errors="replace")


def _read_csv_from_folder(folder: Path, filename: str) -> pd.DataFrame | None:
    """폴더에서 CSV 읽기 (이미 압축 해제된 경우)."""
    path = folder / filename
    if not path.exists():
        # 대소문자 무시 탐색
        matches = list(folder.glob(f"*{Path(filename).stem}*"))
        if not matches:
            return None
        path = matches[0]
    try:
        return pd.read_csv(path, encoding="euc-kr", low_memory=False)
    except Exception as e:
        print(f"  [warn] CSV 읽기 실패 {path}: {e}")
        return None


def _read_csv_from_zip(zip_path: Path, pattern: str) -> pd.DataFrame | None:
    """ZIP 파일에서 pattern 에 매칭되는 첫 번째 CSV 읽기."""
    if not zip_path.exists():
        return None
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                name = _decode_zip_name(info.filename.encode("latin-1"))
                if pattern.lower() in name.lower() and name.endswith(".csv"):
                    raw = zf.read(info.filename)
                    return pd.read_csv(io.BytesIO(raw), encoding="euc-kr", low_memory=False)
    except Exception as e:
        print(f"  [warn] ZIP 읽기 실패 {zip_path}: {e}")
    return None


def load_env_df(year: int) -> pd.DataFrame | None:
    """연도별 환경 CSV 로드 (폴더 우선, 없으면 ZIP)."""
    folder = DATA_DIR / f"스마트팜_{year}" / f"환경_{year}"
    df = _read_csv_from_folder(folder, f"환경_{year}.csv")
    if df is None:
        zip_path = DATA_DIR / f"스마트팜_{year}.zip"
        df = _read_csv_from_zip(zip_path, f"환경_{year}")
    if df is None:
        print(f"  [skip] 환경_{year}.csv 없음")
        return None
    print(f"  환경_{year}.csv: {len(df):,}행 로드")
    return df


def load_production_df(year: int) -> pd.DataFrame | None:
    """연도별 생산 CSV 로드."""
    folder = DATA_DIR / f"스마트팜_{year}" / f"생산_{year}"
    df = _read_csv_from_folder(folder, f"생산_{year}.csv")
    if df is None:
        zip_path = DATA_DIR / f"스마트팜_{year}.zip"
        df = _read_csv_from_zip(zip_path, f"생산_{year}")
    return df


def clean_env_df(df: pd.DataFrame) -> pd.DataFrame:
    """환경 데이터 정제: 컬럼 정규화, 이상치 제거, 작목 필터링."""
    # 측정시간 파싱
    if "측정시간" in df.columns:
        df["dt"] = pd.to_datetime(df["측정시간"], errors="coerce")
    elif "측정일시" in df.columns:
        df["dt"] = pd.to_datetime(df["측정일시"], errors="coerce")
    else:
        df["dt"] = pd.NaT

    df["month"] = df["dt"].dt.month

    # 작목 컬럼 정규화
    crop_col = next((c for c in df.columns if "품목" in c), None)
    if crop_col is None:
        return pd.DataFrame()
    df["crop"] = df[crop_col].astype(str).str.strip()
    df = df[df["crop"].isin(TARGET_CROPS)].copy()

    # 환경 변수 컬럼 → canonical
    for orig, canon in ENV_COL_MAP.items():
        if orig in df.columns:
            df[canon] = pd.to_numeric(df[orig], errors="coerce")
            lo, hi = VALID_RANGES.get(canon, (-999, 999))
            df.loc[~df[canon].between(lo, hi), canon] = np.nan

    return df


def compute_env_stats(env_frames: list[pd.DataFrame]) -> dict:
    """전체 연도 환경 데이터에서 작목별 통계 계산."""
    all_df = pd.concat([f for f in env_frames if f is not None and len(f) > 0], ignore_index=True)
    if all_df.empty:
        return {}

    canon_cols = [c for c in ENV_COL_MAP.values() if c in all_df.columns]
    result: dict = {}

    for crop, cdf in all_df.groupby("crop"):
        if crop not in TARGET_CROPS:
            continue

        crop_stats: dict = {"월별_분포": {}, "최적_범위": {}, "조정_델타": {}, "수확량_상관": {}}

        # 월별 분포
        for month in range(1, 13):
            mdf = cdf[cdf["month"] == month]
            if len(mdf) < 10:
                continue
            month_stats: dict = {}
            for col in canon_cols:
                s = mdf[col].dropna()
                if len(s) < 5:
                    continue
                month_stats[col] = {
                    "mean": round(float(s.mean()), 2),
                    "p25":  round(float(s.quantile(0.25)), 2),
                    "p75":  round(float(s.quantile(0.75)), 2),
                    "p95":  round(float(s.quantile(0.95)), 2),
                }
            if month_stats:
                crop_stats["월별_분포"][str(month)] = month_stats

        # 최적 범위 (전체 기간 P25~P75)
        for col in canon_cols:
            s = cdf[col].dropna()
            if len(s) < 20:
                continue
            p25 = round(float(s.quantile(0.25)), 2)
            p75 = round(float(s.quantile(0.75)), 2)
            crop_stats["최적_범위"][col] = [p25, p75]

            # 조정 델타: 범위 폭의 25% 단위 (−2스텝, −1스텝, +1스텝, +2스텝)
            step = round((p75 - p25) / 4, 2)
            if step > 0:
                crop_stats["조정_델타"][col] = [
                    round(-2 * step, 2), round(-step, 2),
                    round(+step, 2),     round(+2 * step, 2),
                ]

        result[crop] = crop_stats
        print(f"  [{crop}] 최적범위 {len(crop_stats['최적_범위'])}개 변수, 월별분포 {len(crop_stats['월별_분포'])}개월")

    return result


def compute_yield_correlation(
    env_frames: list[pd.DataFrame],
    prod_frames: list[pd.DataFrame],
) -> dict[str, dict[str, float]]:
    """환경 월평균 vs 월별 출하량 Pearson 상관계수 계산."""
    all_env  = pd.concat([f for f in env_frames if f is not None and len(f) > 0], ignore_index=True)
    all_prod = pd.concat([f for f in prod_frames if f is not None], ignore_index=True)
    if all_env.empty or all_prod.empty:
        return {}

    # 생산 데이터 정제
    crop_col = next((c for c in all_prod.columns if "품목" in c), None)
    date_col = next((c for c in all_prod.columns if "출하" in c or "일자" in c), None)
    qty_col  = next((c for c in all_prod.columns if "출하량" in c or "생산량" in c), None)
    if not all([crop_col, date_col, qty_col]):
        return {}

    all_prod = all_prod.rename(columns={crop_col: "crop", date_col: "date", qty_col: "qty"})
    all_prod["date"]  = pd.to_datetime(all_prod["date"], errors="coerce")
    all_prod["month"] = all_prod["date"].dt.month
    all_prod["year"]  = all_prod["date"].dt.year
    all_prod["qty"]   = pd.to_numeric(all_prod["qty"], errors="coerce")

    canon_cols = [c for c in ENV_COL_MAP.values() if c in all_env.columns]
    correlations: dict[str, dict[str, float]] = {}

    for crop in TARGET_CROPS:
        env_crop  = all_env[all_env["crop"] == crop].copy()
        prod_crop = all_prod[all_prod["crop"] == crop].copy()
        if env_crop.empty or prod_crop.empty:
            continue

        # 연도-월 단위 환경 평균
        env_crop["year"] = env_crop["dt"].dt.year
        env_monthly = env_crop.groupby(["year", "month"])[canon_cols].mean().reset_index()

        # 연도-월 단위 출하량 합계
        prod_monthly = prod_crop.groupby(["year", "month"])["qty"].sum().reset_index()

        merged = env_monthly.merge(prod_monthly, on=["year", "month"])
        if len(merged) < 5:
            continue

        crop_corr: dict[str, float] = {}
        for col in canon_cols:
            s = merged[[col, "qty"]].dropna()
            if len(s) >= 5:
                r = float(s[col].corr(s["qty"]))
                if not np.isnan(r):
                    crop_corr[col] = round(r, 3)

        if crop_corr:
            correlations[crop] = crop_corr
            print(f"  [{crop}] 수확량 상관계수: {crop_corr}")

    return correlations


def main():
    print("=" * 60)
    print("환경 통계 추출 시작")
    print("=" * 60)

    env_frames:  list[pd.DataFrame] = []
    prod_frames: list[pd.DataFrame] = []

    for year in YEARS:
        print(f"\n[{year}년]")
        env_df  = load_env_df(year)
        prod_df = load_production_df(year)

        if env_df is not None:
            env_df = clean_env_df(env_df)
            if not env_df.empty:
                env_frames.append(env_df)

        if prod_df is not None:
            prod_frames.append(prod_df)

    if not env_frames:
        print("\n[오류] 환경 데이터를 로드할 수 없습니다.")
        return

    print(f"\n총 환경 데이터: {sum(len(f) for f in env_frames):,}행")

    print("\n[1/2] 환경 통계 계산 중...")
    result = compute_env_stats(env_frames)

    print("\n[2/2] 수확량 상관계수 계산 중...")
    correlations = compute_yield_correlation(env_frames, prod_frames)
    for crop, corr in correlations.items():
        if crop in result:
            result[crop]["수확량_상관"] = corr

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 저장 완료: {OUT_PATH}")
    print(f"   작목 수: {len(result)}")
    for crop, stats in result.items():
        print(f"   [{crop}] 최적범위 {len(stats['최적_범위'])}변수, "
              f"상관 {len(stats['수확량_상관'])}변수, "
              f"월분포 {len(stats['월별_분포'])}개월")


if __name__ == "__main__":
    main()
