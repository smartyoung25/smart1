"""
scripts/extract_cost_params.py

농림수산식품교육문화정보원 농가경영정보(20230927) ZIP에서
  - 경영정보관리생산량.csv    → 등급별 판매단가 보강
  - 경영정보관리생산비경영비.csv  → 항목별 지출 통계
  - 농가기초원자재지출정보.csv    → 원자재(비료·농약 등) 지출
  - 농가양액지출정보.csv         → 양액 비용
  → api/data/cost_params.json

실행:
    python scripts/extract_cost_params.py
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

# ── 경로 ──────────────────────────────────────────────────────────────────────

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "기초자료" / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터"
OUT_DIR  = ROOT / "api" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ZIP_NAME  = "농림수산식품교육문화정보원_스마트팜 농가경영정보_20230927.zip"
ZIP_PATH  = DATA_DIR / ZIP_NAME
ENCODING  = "utf-8-sig"   # 농정원 CSV: UTF-8 with BOM (efbbbf 헤더 확인됨)


def _decode_zip_name(raw_name: str) -> str:
    try:
        return raw_name.encode("latin-1").decode("euc-kr")
    except Exception:
        return raw_name


def read_from_zip(zip_path: Path, name_pattern: str) -> pd.DataFrame | None:
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
            print(f"  [WARN] '{name_pattern}' 파일 없음")
            return None
        raw_name, display_name = matches[0]
        print(f"  읽기: {display_name}")
        raw = zf.read(raw_name)
        return pd.read_csv(io.BytesIO(raw), encoding=ENCODING, low_memory=False)


# ── 생산량 CSV → 등급별 단가 ─────────────────────────────────────────────────

def extract_grade_prices() -> dict:
    """등급별 kg당 판매단가 통계 (특상/상/중/하)."""
    print("\n[1] 등급별 판매단가 추출...")
    df = read_from_zip(ZIP_PATH, "경영정보관리생산량")
    if df is None:
        return {}

    df.columns = df.columns.str.strip()
    grade_cols = {
        "특상": ("특상등급출하량", "특상등급kg당금액"),
        "상":   ("상등급출하량",   "상등급kg당금액"),
        "중":   ("중등급출하량",   "중등급kg당금액"),
        "하":   ("하등급출하량",   "하등급kg당금액"),
    }

    result: dict[str, dict] = {}
    for grade, (qty_col, price_col) in grade_cols.items():
        if qty_col not in df.columns or price_col not in df.columns:
            continue
        qty   = pd.to_numeric(df[qty_col], errors="coerce")
        price = pd.to_numeric(df[price_col], errors="coerce")
        valid = (qty > 0) & (price > 0) & (price < 100_000)
        prices = price[valid].dropna()
        if len(prices) == 0:
            continue
        result[grade] = {
            "mean_krw_kg":   round(float(prices.mean()), 0),
            "median_krw_kg": round(float(prices.median()), 0),
            "std_krw_kg":    round(float(prices.std()), 0),
            "n":             int(len(prices)),
        }

    # 총 수입 및 전체 단가
    if "총출하량" in df.columns and "수입금액" in df.columns:
        qty_tot = pd.to_numeric(df["총출하량"], errors="coerce")
        rev_tot = pd.to_numeric(df["수입금액"], errors="coerce")
        valid = (qty_tot > 0) & (rev_tot > 0)
        overall_price = (rev_tot[valid] / qty_tot[valid]).dropna()
        overall_price = overall_price[(overall_price >= 100) & (overall_price <= 100_000)]
        if len(overall_price) > 0:
            result["전체"] = {
                "mean_krw_kg":   round(float(overall_price.mean()), 0),
                "median_krw_kg": round(float(overall_price.median()), 0),
                "std_krw_kg":    round(float(overall_price.std()), 0),
                "n":             int(len(overall_price)),
            }

    print(f"  → {len(result)}개 등급 단가 추출")
    return result


# ── 생산비 경영비 CSV → 항목별 지출 통계 ──────────────────────────────────────

def extract_production_costs() -> dict:
    """
    항목별(전기, 인건비, 농약, 비료 등) 월평균 지출 통계.
    작기 내 지출일자를 기준으로 농가×작기별 합산 후 월로 나눔.
    """
    print("\n[2] 생산비 경영비 항목별 추출...")
    df = read_from_zip(ZIP_PATH, "경영정보관리생산비경영비")
    if df is None:
        return {}

    df.columns = df.columns.str.strip()
    required = {"시설id", "작기일련번호", "작업코드명", "작업금액"}
    if not required.issubset(df.columns):
        print(f"  [WARN] 누락 컬럼: {required - set(df.columns)}")
        return {}

    df["작업금액"] = pd.to_numeric(df["작업금액"], errors="coerce")
    df = df[df["작업금액"] > 0].copy()

    # 항목명 정규화 매핑
    category_map = {
        "전기": "electricity",
        "수도": "water",
        "난방": "heating", "연료": "heating",
        "인건비": "labor", "고용": "labor",
        "농약": "pesticides",
        "비료": "fertilizer",
        "양액": "nutrients",
        "자재": "materials",
        "수선": "maintenance", "수리": "maintenance",
        "감가": "depreciation",
    }

    def map_category(name: str) -> str:
        name = str(name)
        for k, v in category_map.items():
            if k in name:
                return v
        return "other"

    df["category"] = df["작업코드명"].apply(map_category)

    # 농가×작기별 항목합산
    grouped = df.groupby(["시설id", "작기일련번호", "category"])["작업금액"].sum().reset_index()

    # 작기 기간 추정: 지출일자 min/max로 월수 계산
    cost_stats: dict[str, dict] = {}

    if "지출일자" in df.columns:
        df["지출일자"] = pd.to_datetime(df["지출일자"], errors="coerce")
        duration = (
            df.groupby(["시설id", "작기일련번호"])["지출일자"]
            .agg(lambda x: (x.max() - x.min()).days / 30.0)
            .clip(lower=1.0)
            .reset_index()
            .rename(columns={"지출일자": "months"})
        )
        grouped = grouped.merge(duration, on=["시설id", "작기일련번호"], how="left")
        grouped["months"] = grouped["months"].fillna(6.0)  # 기본 6개월 작기
        grouped["monthly_krw"] = grouped["작업금액"] / grouped["months"]
    else:
        grouped["monthly_krw"] = grouped["작업금액"] / 6.0

    for cat, grp in grouped.groupby("category"):
        monthly = grp["monthly_krw"].dropna()
        monthly = monthly[monthly > 0]
        if len(monthly) == 0:
            continue
        cost_stats[cat] = {
            "avg_monthly_krw":    round(float(monthly.mean()), 0),
            "median_monthly_krw": round(float(monthly.median()), 0),
            "std_monthly_krw":    round(float(monthly.std()), 0),
            "n_farm_seasons":     int(len(monthly)),
        }

    print(f"  → {len(cost_stats)}개 비용 항목 추출")
    return cost_stats


# ── 영농작업 인건비 상세 ───────────────────────────────────────────────────────

def extract_labor_costs() -> dict:
    """인건비 일당 통계 (작업인원수 × 작업금액)."""
    print("\n[3] 영농작업 인건비 추출...")
    df = read_from_zip(ZIP_PATH, "경영정보관리생산비영농작업")
    if df is None:
        return {}

    df.columns = df.columns.str.strip()
    required = {"작업금액", "작업인원수"}
    if not required.issubset(df.columns):
        print(f"  [WARN] 누락: {required - set(df.columns)}")
        return {}

    df["작업금액"] = pd.to_numeric(df["작업금액"], errors="coerce")
    df["작업인원수"] = pd.to_numeric(df["작업인원수"], errors="coerce")
    df = df[(df["작업금액"] > 0) & (df["작업인원수"] > 0)].copy()
    df["daily_rate"] = df["작업금액"] / df["작업인원수"]

    # 비현실적 값 제거 (5만 ~ 50만원/일)
    df = df[(df["daily_rate"] >= 50_000) & (df["daily_rate"] <= 500_000)]

    if df.empty:
        return {}

    rates = df["daily_rate"]
    result = {
        "avg_daily_krw":    round(float(rates.mean()), 0),
        "median_daily_krw": round(float(rates.median()), 0),
        "std_daily_krw":    round(float(rates.std()), 0),
        "n":                int(len(rates)),
    }
    print(f"  → 인건비 일당: 평균 {result['avg_daily_krw']:,.0f}원 (n={result['n']})")
    return result


# ── 양액 지출 ────────────────────────────────────────────────────────────────

def extract_nutrient_costs() -> dict:
    """양액 지출 월평균 통계."""
    print("\n[4] 양액 지출 추출...")
    df = read_from_zip(ZIP_PATH, "농가양액지출정보")
    if df is None:
        return {}

    df.columns = df.columns.str.strip()
    if "유지비용지출금액" not in df.columns:
        return {}

    df["유지비용지출금액"] = pd.to_numeric(df["유지비용지출금액"], errors="coerce")
    df = df[df["유지비용지출금액"] > 0]

    # 농가×작기별 합산
    total_by_season = df.groupby(["시설id", "작기일련번호"])["유지비용지출금액"].sum()
    monthly = total_by_season / 6.0  # 작기 6개월 가정

    result = {
        "avg_monthly_krw":    round(float(monthly.mean()), 0),
        "median_monthly_krw": round(float(monthly.median()), 0),
        "n_farm_seasons":     int(len(monthly)),
    }
    print(f"  → 양액 월평균: {result['avg_monthly_krw']:,.0f}원")
    return result


# ── 단위 면적당 비용 추정 (면적 없으므로 참고값) ──────────────────────────────

def build_unit_cost_rates(cost_stats: dict, labor: dict) -> dict:
    """
    CostBreakdown 계산에 사용할 단위 비율.
    면적 정보 없이 월 총비용 기준 → 참고용 비율만 도출.
    """
    total_monthly = sum(v.get("avg_monthly_krw", 0) for v in cost_stats.values())
    if total_monthly == 0:
        return {}

    rates: dict[str, dict] = {}
    for cat, v in cost_stats.items():
        rates[cat] = {
            "avg_monthly_krw": v["avg_monthly_krw"],
            "pct_of_total":    round(v["avg_monthly_krw"] / total_monthly * 100, 1),
        }

    # 인건비 일당 추가 (별도 참조)
    if labor and "labor" in rates:
        rates["labor"]["avg_daily_krw"] = labor.get("avg_daily_krw", 120_000)

    return rates


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("농가경영정보 비용 파라미터 추출 스크립트")
    print("=" * 60)

    grade_prices  = extract_grade_prices()
    cost_stats    = extract_production_costs()
    labor         = extract_labor_costs()
    nutrients     = extract_nutrient_costs()
    unit_rates    = build_unit_cost_rates(cost_stats, labor)

    # 농가경영정보에 전기·수도 단위 요금은 없으므로
    # KEPCO 2024 평균값을 참조 기본값으로 포함
    electricity_defaults = {
        "avg_rate_krw_kwh":      112.0,  # 한전 농업용(갑) 2024 평균
        "source":                "KEPCO_2024_농업용갑_참고값",
    }
    water_defaults = {
        "avg_rate_krw_m3":       620.0,  # 농업용 평균
        "source":                "지자체_농업용수_참고값",
    }

    output = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "description":  "농림수산식품교육문화정보원 농가경영정보(2023) 기반 비용 통계",
        "grade_prices_krw_kg": grade_prices,
        "monthly_costs_by_category": cost_stats,
        "labor_daily_rate": labor,
        "nutrient_monthly": nutrients,
        "unit_rates_with_pct": unit_rates,
        "reference_rates": {
            "electricity": electricity_defaults,
            "water":       water_defaults,
        },
    }

    out_path = OUT_DIR / "cost_params.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {out_path}")

    print("\n" + "=" * 60)
    print("비용 항목별 월평균 (참고)")
    print("=" * 60)
    for cat, v in sorted(cost_stats.items(), key=lambda x: -x[1]["avg_monthly_krw"]):
        print(f"  {cat:15s}: {v['avg_monthly_krw']:>10,.0f} 원/월  ({v.get('pct_of_total', unit_rates.get(cat, {}).get('pct_of_total', 0))}%)")
    if grade_prices:
        print("\n등급별 단가:")
        for g, v in grade_prices.items():
            print(f"  {g}등급: {v['mean_krw_kg']:,.0f} 원/kg  (n={v['n']})")


if __name__ == "__main__":
    main()
