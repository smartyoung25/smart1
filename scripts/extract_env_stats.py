"""환경 통계 추출 스크립트 — 농진청 5년 패널 (2018~2022)
메모리 효율: 청크 단위 처리, 연도별 집계 후 병합

입력 : 기초자료/.../스마트팜_{year}/환경_{year}/환경_{year}.csv  (5개)
출력 : api/data/env_stats.json
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "기초자료" / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터"
OUT_PATH = ROOT / "api" / "data" / "env_stats.json"
YEARS    = [2018, 2019, 2020, 2021, 2022]
CHUNK    = 80_000
SAMPLE_N = 8_000   # 연도당 퍼센타일 샘플 수

ENV_COL_MAP = {
    "온도_내부":     "temp_internal",
    "상대습도_내부": "humidity_int",
    "잔존CO2":       "co2_ppm",
    "토양온도":      "soil_temp",
    "일사량_외부":   "solar_rad",
    "온도_외부":     "temp_external",
    "풍속_외부":     "wind_speed",
}
VALID_RANGES = {
    "temp_internal": (-5.0,  55.0),
    "humidity_int":  (0.0,  100.0),
    "co2_ppm":       (0.0, 5000.0),
    "soil_temp":     (-5.0,  50.0),
    "solar_rad":     (0.0, 1500.0),
    "temp_external": (-20.0, 45.0),
    "wind_speed":    (0.0,   30.0),
}
TARGET_CROPS = {"딸기", "방울토마토", "완숙토마토", "오이", "참외"}


def process_year(year: int, all_agg, all_magg, sample_rows):
    path = DATA_DIR / f"스마트팜_{year}" / f"환경_{year}" / f"환경_{year}.csv"
    if not path.exists():
        print(f"  [skip] {path.name} 없음")
        return

    total = 0
    reservoir: list = []   # 저수지 샘플링용
    rng = np.random.default_rng(year)

    for chunk in pd.read_csv(path, encoding="cp949", chunksize=CHUNK,
                             low_memory=False, on_bad_lines="skip"):
        total += len(chunk)

        # 시간 → 월
        tc = "측정시간" if "측정시간" in chunk.columns else "측정일시"
        chunk["month"] = pd.to_datetime(chunk.get(tc), errors="coerce").dt.month if tc in chunk.columns else np.nan

        # 작목
        cc = next((c for c in chunk.columns if "품목" in c), None)
        if cc is None:
            continue
        chunk["_crop"] = chunk[cc].astype(str).str.strip()
        chunk = chunk[chunk["_crop"].isin(TARGET_CROPS)]
        if chunk.empty:
            continue

        # canonical 변환
        for orig, canon in ENV_COL_MAP.items():
            if orig in chunk.columns:
                chunk[canon] = pd.to_numeric(chunk[orig], errors="coerce")
                lo, hi = VALID_RANGES[canon]
                chunk.loc[~chunk[canon].between(lo, hi), canon] = np.nan

        canon_cols = [c for c in ENV_COL_MAP.values() if c in chunk.columns]

        # 전체 통계 누산
        for crop, cdf in chunk.groupby("_crop"):
            for col in canon_cols:
                v = cdf[col].dropna().values
                if len(v) == 0:
                    continue
                all_agg[crop][col]["n"]  += len(v)
                all_agg[crop][col]["s"]  += float(v.sum())
                all_agg[crop][col]["ss"] += float((v**2).sum())

        # 월별 누산
        for (crop, month), mdf in chunk.groupby(["_crop", "month"]):
            if pd.isna(month):
                continue
            for col in canon_cols:
                v = mdf[col].dropna().values
                if len(v) == 0:
                    continue
                all_magg[crop][int(month)][col]["n"] += len(v)
                all_magg[crop][int(month)][col]["s"] += float(v.sum())

        # 저수지 샘플 수집
        small = chunk[["_crop", "month"] + canon_cols].copy()
        reservoir.append(small)

    # 샘플 제한 (메모리)
    if reservoir:
        combined = pd.concat(reservoir, ignore_index=True)
        if len(combined) > SAMPLE_N * 5:
            combined = combined.sample(n=SAMPLE_N * 5, random_state=year)
        sample_rows.append(combined)
        del combined

    print(f"  환경_{year}.csv: {total:,}행 처리")


def build_stats(all_agg, all_magg, sample_df):
    result = {}
    canon_cols = list(ENV_COL_MAP.values())

    for crop in TARGET_CROPS:
        if crop not in all_agg:
            continue
        crop_stats = {"월별_분포": {}, "최적_범위": {}, "조정_델타": {}, "수확량_상관": {}}
        csamp = sample_df[sample_df["_crop"] == crop] if not sample_df.empty else pd.DataFrame()

        for col in canon_cols:
            if col not in all_agg[crop]:
                continue
            n, s, ss = all_agg[crop][col]["n"], all_agg[crop][col]["s"], all_agg[crop][col]["ss"]
            if n == 0:
                continue
            mean = s / n
            std  = max(0.0, ss / n - mean**2) ** 0.5

            if not csamp.empty and col in csamp.columns:
                v = csamp[col].dropna().values
                if len(v) >= 10:
                    p5, p25, p75, p95 = np.percentile(v, [5, 25, 75, 95])
                else:
                    p5, p25, p75, p95 = mean-1.65*std, mean-0.67*std, mean+0.67*std, mean+1.65*std
            else:
                p5, p25, p75, p95 = mean-1.65*std, mean-0.67*std, mean+0.67*std, mean+1.65*std

            crop_stats["최적_범위"][col] = [round(float(p25), 2), round(float(p75), 2)]
            width = max(0.5, float(p75 - p25))
            step  = round(width / 4, 1)
            crop_stats["조정_델타"][col] = [-2*step, -step, step, 2*step]

            # mean/std/p5/p95 도 저장 (anomaly_detector 용)
            crop_stats.setdefault("변수_통계", {})[col] = {
                "mean": round(float(mean), 2),
                "std":  round(float(std), 2),
                "p5":   round(float(p5), 2),
                "p95":  round(float(p95), 2),
            }

        # 월별 분포
        for month in sorted(all_magg.get(crop, {}).keys()):
            mkey = str(month)
            crop_stats["월별_분포"][mkey] = {}
            for col, mv in all_magg[crop][month].items():
                if mv["n"] > 0:
                    crop_stats["월별_분포"][mkey][col] = {
                        "mean": round(mv["s"] / mv["n"], 2),
                        "n":    mv["n"],
                    }

        result[crop] = crop_stats
    return result


def main():
    print("=== extract_env_stats.py (메모리 효율 버전) ===\n")

    all_agg  = defaultdict(lambda: defaultdict(lambda: {"n": 0, "s": 0.0, "ss": 0.0}))
    all_magg = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"n": 0, "s": 0.0})))
    sample_rows: list = []

    for year in YEARS:
        print(f"[{year}]")
        process_year(year, all_agg, all_magg, sample_rows)

    print("\n[통계 계산 중...]")
    sample_df = pd.concat(sample_rows, ignore_index=True) if sample_rows else pd.DataFrame()
    env_stats = build_stats(dict(all_agg), dict(all_magg), sample_df)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(env_stats, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 저장: {OUT_PATH}")
    for crop, cs in env_stats.items():
        print(f"  {crop}: 최적범위 {len(cs.get('최적_범위',{}))}개 변수")


if __name__ == "__main__":
    main()
