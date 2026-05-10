"""
scripts/extract_rda_stats.py

농진청 스마트팜 5년 패널(2018~2022) ZIP에서
  - 재배정보_YYYY.CSV  → api/data/farm_registry.json
  - 생산_YYYY.csv      → api/data/price_stats.json
                          api/data/yield_stats.json

실행:
    python scripts/extract_rda_stats.py

요구사항:
    pip install pandas numpy
"""

from __future__ import annotations

import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

# ── 경로 설정 ─────────────────────────────────────────────────────────────────

ROOT      = Path(__file__).parent.parent
DATA_DIR  = ROOT / "기초자료" / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터"
OUT_DIR   = ROOT / "api" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

YEARS     = [2018, 2019, 2020, 2021, 2022]
ENCODING  = "euc-kr"


def norm_key(v) -> str:
    """조인 키 정규화: float 2.0 → '2', int 2 → '2', '2' → '2'."""
    try:
        return str(int(float(str(v).strip())))
    except (ValueError, TypeError):
        return str(v).strip()


# ── ZIP에서 CSV 읽기 ──────────────────────────────────────────────────────────

def _decode_zip_name(raw_name: str) -> str:
    """ZIP 파일명이 EUC-KR 원시 바이트를 latin-1로 읽혔을 때 복원."""
    try:
        return raw_name.encode("latin-1").decode("euc-kr")
    except Exception:
        return raw_name


def read_csv_from_zip(zip_path: Path, name_pattern: str, encoding: str = ENCODING) -> pd.DataFrame | None:
    """ZIP 내에서 name_pattern(한글 포함) 을 포함하는 CSV를 찾아 DataFrame 반환."""
    if not zip_path.exists():
        print(f"  [WARN] ZIP 없음: {zip_path}")
        return None
    with zipfile.ZipFile(zip_path) as zf:
        matches = []
        for info in zf.infolist():
            decoded = _decode_zip_name(info.filename)
            if name_pattern in decoded and decoded.lower().endswith(".csv"):
                matches.append((info.filename, decoded))
        if not matches:
            print(f"  [WARN] '{name_pattern}' 파일 없음 in {zip_path.name}")
            return None
        raw_name, display_name = matches[0]
        print(f"  읽기: {zip_path.name}/{display_name}")
        raw = zf.read(raw_name)
        return pd.read_csv(io.BytesIO(raw), encoding=encoding, low_memory=False)


# ── 재배정보 처리 ─────────────────────────────────────────────────────────────

def extract_farm_registry() -> dict:
    """
    재배정보_YYYY.CSV → 농가 메타 정보 통합.
    동일 농가(도+시군+농가명+품목)는 가장 최근 연도 우선.
    """
    print("\n[1] 재배정보 추출 중...")
    rows: list[dict] = []

    for year in YEARS:
        zip_path = DATA_DIR / f"스마트팜_{year}.zip"
        df = read_csv_from_zip(zip_path, "재배정보")
        if df is None:
            continue

        df.columns = df.columns.str.strip()

        # 컬럼 정규화 (연도별 미세 차이 대응)
        col_map = {
            "지역(도)": "sido", "도": "sido",
            "시군": "sigungu",
            "농가명": "farm_code",
            "품목": "crop",
            "품종": "variety",
            "전체면적": "total_area_m2",   "총면적(㎡)": "total_area_m2",
            "식부면적": "plant_area_m2",   "식부면적(㎡)": "plant_area_m2",
            "재식밀도": "plant_density",
            "정식일": "transplant_date",
            "작기": "season",
            "온실종류": "greenhouse_type",
        }
        df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})
        df["year"] = year

        required = {"sido", "sigungu", "farm_code", "crop", "plant_area_m2"}
        missing = required - set(df.columns)
        if missing:
            print(f"  [WARN] {year} 재배정보 누락 컬럼: {missing}")
            continue

        rows.append(df)

    if not rows:
        print("  [ERROR] 재배정보 데이터 없음")
        return {}

    all_df = pd.concat(rows, ignore_index=True)

    # 숫자 변환
    all_df["plant_area_m2"] = pd.to_numeric(all_df.get("plant_area_m2"), errors="coerce")
    all_df["total_area_m2"] = pd.to_numeric(all_df.get("total_area_m2", np.nan), errors="coerce")

    # 품목별 면적 통계
    area_stats = (
        all_df.groupby("crop")["plant_area_m2"]
        .agg(["mean", "median", "std", "count"])
        .round(1)
        .rename(columns={"mean": "avg_m2", "median": "median_m2", "std": "std_m2", "count": "n_farms"})
        .to_dict(orient="index")
    )

    # 개별 농가 레코드 (가장 최근 연도 기준 중복 제거)
    all_df = all_df.sort_values("year", ascending=False)
    deduped = all_df.drop_duplicates(subset=["sido", "sigungu", "farm_code", "crop", "season"])

    farms: dict[str, dict] = {}
    for _, row in deduped.iterrows():
        key = f"{row.get('sido','')}_{row.get('sigungu','')}_{row.get('crop','')}_{row.get('farm_code','')}_{row.get('season','')}"
        farms[key] = {
            "sido": str(row.get("sido", "")),
            "sigungu": str(row.get("sigungu", "")),
            "crop": str(row.get("crop", "")),
            "farm_code": str(row.get("farm_code", "")),
            "season": str(row.get("season", "")),
            "plant_area_m2": float(row["plant_area_m2"]) if pd.notna(row.get("plant_area_m2")) else None,
            "total_area_m2": float(row["total_area_m2"]) if pd.notna(row.get("total_area_m2")) else None,
            "transplant_date": str(row.get("transplant_date", "")),
            "greenhouse_type": str(row.get("greenhouse_type", "")),
            "variety": str(row.get("variety", "")),
            "year": int(row["year"]),
        }

    result = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "total_farms": len(farms),
        "area_stats_by_crop": area_stats,
        "farms": farms,
    }
    print(f"  → {len(farms)}개 농가 메타 추출 완료")
    return result


# ── 생산(출하) 데이터 처리 ────────────────────────────────────────────────────

def extract_price_yield_stats(farm_registry: dict) -> tuple[dict, dict]:
    """
    생산_YYYY.csv → 품목별 kg당 판매단가 + kg/m²/작기 수확량 통계.
    재배정보와 (도+시군+농가명+작기) 기준으로 조인해 면적 정보 결합.
    """
    print("\n[2] 생산·가격 통계 추출 중...")

    # 재배정보에서 (sido+sigungu+crop+farm_code+season) → 면적 매핑
    area_lookup: dict[tuple, float] = {}
    for key, meta in farm_registry.get("farms", {}).items():
        k = (meta["sido"], meta["sigungu"], meta["crop"],
             norm_key(meta["farm_code"]), norm_key(meta["season"]))
        if meta["plant_area_m2"]:
            area_lookup[k] = meta["plant_area_m2"]

    all_rows: list[dict] = []

    for year in YEARS:
        zip_path = DATA_DIR / f"스마트팜_{year}.zip"
        df = read_csv_from_zip(zip_path, "생산")
        if df is None:
            continue

        df.columns = df.columns.str.strip()

        # 컬럼 정규화
        col_map = {
            "도": "sido", "지역(도)": "sido",
            "시군": "sigungu",
            "품목": "crop",
            "작기": "season",
            "농가명": "farm_code",
            "출하일자": "ship_date",
            "총출하량": "qty_kg", "총출하량(kg)": "qty_kg",
            "판매금액": "revenue_krw", "판매금액(원)": "revenue_krw",
        }
        df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})
        df["year"] = year

        required = {"crop", "qty_kg", "revenue_krw"}
        if not required.issubset(df.columns):
            print(f"  [WARN] {year} 생산 누락 컬럼: {required - set(df.columns)}")
            continue

        df["qty_kg"] = pd.to_numeric(df["qty_kg"], errors="coerce")
        df["revenue_krw"] = pd.to_numeric(df["revenue_krw"], errors="coerce")

        # 0kg 또는 0원 제거
        df = df[(df["qty_kg"] > 0) & (df["revenue_krw"] > 0)].copy()
        df["price_krw_kg"] = df["revenue_krw"] / df["qty_kg"]

        # 비현실적 단가 필터 (100 ~ 100,000 원/kg)
        df = df[(df["price_krw_kg"] >= 100) & (df["price_krw_kg"] <= 100_000)]

        all_rows.append(df)

    if not all_rows:
        print("  [ERROR] 생산 데이터 없음")
        return {}, {}

    prod_df = pd.concat(all_rows, ignore_index=True)
    print(f"  → 총 {len(prod_df):,}건 출하 레코드")

    # ── 품목별 단가 통계 ────────────────────────────────────────────────────────
    price_stats: dict[str, dict] = {}
    for crop, grp in prod_df.groupby("crop"):
        prices = grp["price_krw_kg"].dropna()
        if len(prices) < 5:
            continue
        price_stats[crop] = {
            "mean_krw_kg":   round(float(prices.mean()), 0),
            "median_krw_kg": round(float(prices.median()), 0),
            "std_krw_kg":    round(float(prices.std()), 0),
            "p25_krw_kg":    round(float(prices.quantile(0.25)), 0),
            "p75_krw_kg":    round(float(prices.quantile(0.75)), 0),
            "min_krw_kg":    round(float(prices.min()), 0),
            "max_krw_kg":    round(float(prices.max()), 0),
            "n_records":     int(len(prices)),
            "years_covered": sorted(grp["year"].unique().tolist()),
        }

    # ── 농가×작기별 총출하량 집계 후 면적과 조인 → kg/m² ────────────────────────
    season_prod = (
        prod_df.groupby(["sido", "sigungu", "crop", "farm_code", "season", "year"])
        ["qty_kg"].sum().reset_index()
    )

    yield_rows: list[dict] = []
    for _, row in season_prod.iterrows():
        k = (str(row.get("sido", "")).strip(), str(row.get("sigungu", "")).strip(),
             str(row["crop"]).strip(), norm_key(row["farm_code"]), norm_key(row["season"]))
        area = area_lookup.get(k)
        if area and area > 0:
            yield_rows.append({
                "crop": row["crop"],
                "yield_kg_m2": row["qty_kg"] / area,
                "qty_kg": row["qty_kg"],
                "area_m2": area,
                "year": row["year"],
            })

    yield_stats: dict[str, dict] = {}
    if yield_rows:
        yield_df = pd.DataFrame(yield_rows)
        # 비현실적 수치 필터 (0.1 ~ 50 kg/m²/작기)
        yield_df = yield_df[(yield_df["yield_kg_m2"] >= 0.1) & (yield_df["yield_kg_m2"] <= 50)]

        for crop, grp in yield_df.groupby("crop"):
            ys = grp["yield_kg_m2"].dropna()
            if len(ys) < 3:
                continue
            yield_stats[crop] = {
                "avg_kg_m2_season":    round(float(ys.mean()), 2),
                "median_kg_m2_season": round(float(ys.median()), 2),
                "std_kg_m2_season":    round(float(ys.std()), 2),
                "p25_kg_m2_season":    round(float(ys.quantile(0.25)), 2),
                "p75_kg_m2_season":    round(float(ys.quantile(0.75)), 2),
                "n_farm_seasons":      int(len(ys)),
                "years_covered":       sorted(grp["year"].unique().tolist()),
            }

    print(f"  → {len(price_stats)}개 품목 단가 통계 완료")
    print(f"  → {len(yield_stats)}개 품목 수확량 통계 완료 ({len(yield_rows)}개 농가×작기 조인)")

    return price_stats, yield_stats


# ── 연도별 단가 추이 (가격 예측용) ────────────────────────────────────────────

def extract_yearly_price_trend() -> dict:
    """품목×연도별 평균 단가 — 가격 예측 모듈(M2) 기반 데이터."""
    print("\n[3] 연도별 단가 추이 추출 중...")
    rows: list[dict] = []

    for year in YEARS:
        zip_path = DATA_DIR / f"스마트팜_{year}.zip"
        df = read_csv_from_zip(zip_path, "생산")
        if df is None:
            continue
        df.columns = df.columns.str.strip()
        col_map = {"도": "sido", "품목": "crop", "작기": "season",
                   "총출하량": "qty_kg", "총출하량(kg)": "qty_kg",
                   "판매금액": "revenue_krw", "판매금액(원)": "revenue_krw"}
        df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})
        df["year"] = year
        df["qty_kg"] = pd.to_numeric(df.get("qty_kg"), errors="coerce")
        df["revenue_krw"] = pd.to_numeric(df.get("revenue_krw"), errors="coerce")
        df = df[(df["qty_kg"] > 0) & (df["revenue_krw"] > 0)].copy()
        df["price_krw_kg"] = df["revenue_krw"] / df["qty_kg"]
        df = df[(df["price_krw_kg"] >= 100) & (df["price_krw_kg"] <= 100_000)]
        rows.append(df)

    if not rows:
        return {}

    all_df = pd.concat(rows, ignore_index=True)
    trend: dict[str, dict] = {}
    for crop, grp in all_df.groupby("crop"):
        by_year = {}
        for year, ygrp in grp.groupby("year"):
            prices = ygrp["price_krw_kg"].dropna()
            if len(prices) >= 3:
                by_year[str(year)] = {
                    "mean": round(float(prices.mean()), 0),
                    "median": round(float(prices.median()), 0),
                    "n": int(len(prices)),
                }
        if by_year:
            trend[crop] = by_year

    print(f"  → {len(trend)}개 품목 연도별 추이 완료")
    return trend


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("농진청 5년 패널 데이터 추출 스크립트")
    print("=" * 60)

    # 1. 재배정보
    farm_registry = extract_farm_registry()
    out_path = OUT_DIR / "farm_registry.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(farm_registry, f, ensure_ascii=False, indent=2)
    print(f"\n  저장: {out_path}")

    # 2. 가격·수확량 통계
    price_stats, yield_stats = extract_price_yield_stats(farm_registry)
    yearly_trend = extract_yearly_price_trend()

    price_out = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "description": "농진청 스마트팜 5년 패널(2018~2022) 품목별 kg당 판매단가 통계",
        "by_crop": price_stats,
        "yearly_trend": yearly_trend,
    }
    path_price = OUT_DIR / "price_stats.json"
    with open(path_price, "w", encoding="utf-8") as f:
        json.dump(price_out, f, ensure_ascii=False, indent=2)
    print(f"  저장: {path_price}")

    yield_out = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "description": "농진청 스마트팜 5년 패널 품목별 kg/m²/작기 수확량 통계 (재배정보 조인)",
        "by_crop": yield_stats,
    }
    path_yield = OUT_DIR / "yield_stats.json"
    with open(path_yield, "w", encoding="utf-8") as f:
        json.dump(yield_out, f, ensure_ascii=False, indent=2)
    print(f"  저장: {path_yield}")

    # 요약 출력
    print("\n" + "=" * 60)
    print("추출 완료 요약")
    print("=" * 60)
    print(f"농가 메타:  {farm_registry.get('total_farms', 0)}개 농가")
    print(f"단가 통계:  {len(price_stats)}개 품목")
    for crop, s in sorted(price_stats.items()):
        print(f"  {crop:10s}: 평균 {s['mean_krw_kg']:,.0f}원/kg  (n={s['n_records']:,})")
    print(f"\n수확량 통계: {len(yield_stats)}개 품목")
    for crop, s in sorted(yield_stats.items()):
        print(f"  {crop:10s}: 평균 {s['avg_kg_m2_season']:.2f} kg/m²/작기  (n={s['n_farm_seasons']})")


if __name__ == "__main__":
    main()
