"""농림부 소득조사 parquet → M2 학습용 harvest 레코드 변환 ETL.

입력: data/collected/harvest_import/*.parquet  (year=YYYY/crop=XXX 파티션 파일)
출력: data/collected/harvest/income_survey_harvest.parquet
     columns: farm_id, crop, year, yield_kg, area_sqm, yield_per_10a, revenue_krw

핵심 컬럼 (소득조사 원부):
  frm_id          농가ID
  crpnm           작물명 (상세, 예: "딸기(킹스베리)")
  yr              조사연도
  prdv_qty_kg_ea  생산량(kg)
  srvar_tot_sqm   조사면적(㎡)
  totrev_amt_wn   총수입(원)
  inc_amt_wn      소득(원)
"""
from __future__ import annotations
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
IN_DIR = ROOT / "data" / "collected" / "harvest_import"
OUT_DIR = ROOT / "data" / "collected" / "harvest"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 작물명 매핑 (소득조사 crpnm 키워드 → 우리 작목명) ──────────────────────────
# 긴 패턴 우선 (방울토마토 → 완숙토마토보다 먼저)
_CROP_MAP: list[tuple[str, str]] = [
    ("방울",    "방울토마토"),
    ("완숙",    "완숙토마토"),
    ("토마토",  "완숙토마토"),
    ("딸기",    "딸기"),
    ("참외",    "참외"),
    ("파프리카", "파프리카"),
    ("오이",    "오이"),
    ("감귤",    "감귤"),
    ("한라봉",  "감귤"),
    ("천혜향",  "감귤"),
    ("레드향",  "감귤"),
    ("황금향",  "감귤"),
    ("양배추",  "양배추"),
    ("배추",    "배추"),
    ("마늘",    "마늘"),
    ("양파",    "양파"),
    ("고추",    "고추"),
    ("가지",    "가지"),
    ("무",      "무"),
    ("콩",      "콩"),
    ("대두",    "콩"),
]

def _map_crop(name: str | None) -> str | None:
    if not name:
        return None
    n = str(name)
    for kw, crop in _CROP_MAP:
        if kw in n:
            return crop
    return None


def load_parquets(in_dir: Path) -> pd.DataFrame:
    frames = []
    for p in sorted(in_dir.glob("*.parquet")):
        try:
            df = pd.read_parquet(p)
            # 파티션 연도를 파일명에서 추출 (2022_frtr.parquet → yr=2022 보완)
            m = re.search(r"(\d{4})", p.stem)
            if m and "yr" not in df.columns:
                df["yr"] = int(m.group(1))
            frames.append(df)
            print(f"  로드: {p.name} ({len(df)}행)")
        except Exception as e:
            print(f"  오류: {p.name} — {e}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def transform(raw: pd.DataFrame) -> pd.DataFrame:
    needed = ["frm_id", "crpnm", "yr", "prdv_qty_kg_ea", "totrev_amt_wn"]
    missing = [c for c in needed if c not in raw.columns]
    if missing:
        raise ValueError(f"필수 컬럼 없음: {missing}")

    extra = []
    if "inc_amt_wn" in raw.columns:
        extra.append("inc_amt_wn")
    if "ctynm" in raw.columns:
        extra.append("ctynm")
    if "dtnm" in raw.columns:
        extra.append("dtnm")
    # srvar_tot_sqm 없으면 stdar_py(표준면적 평) 폴백
    area_src = "srvar_tot_sqm" if "srvar_tot_sqm" in raw.columns else None
    if "stdar_py" in raw.columns:
        extra.append("stdar_py")
    if area_src:
        extra.append(area_src)

    df = raw[needed + extra].copy()
    df = df.rename(columns={
        "frm_id":           "farm_id",
        "crpnm":            "crpnm_raw",
        "yr":               "year",
        "prdv_qty_kg_ea":   "yield_kg",
        "totrev_amt_wn":    "revenue_krw",
        "inc_amt_wn":       "income_krw",
    })
    if area_src:
        df = df.rename(columns={area_src: "area_sqm"})
    else:
        df["area_sqm"] = float("nan")

    # 작물 매핑
    df["crop"] = df["crpnm_raw"].apply(_map_crop)
    df = df.dropna(subset=["crop"])

    # 수치 변환
    for col in ["yield_kg", "area_sqm", "revenue_krw"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # srvar_tot_sqm 없는 구형 파일(2007~2015)은 면적 정보 없음
    # stdar_py=300평(990㎡)는 표준 조사단위이지 실제 경작면적이 아님
    # → 전체 경작지 생산량을 990㎡로 나누면 yield_per_10a가 3배+ 과대 추정됨
    # 따라서 srvar_tot_sqm(실면적) 있는 행만 유효로 처리
    df["_has_real_area"] = area_src is not None
    if "stdar_py" in df.columns:
        # stdar_py 폴백은 계산에 사용하지 않고 area_sqm=NaN 유지
        pass

    # 유효 행 필터
    df = df[df["yield_kg"] > 0].copy()
    df = df[df["area_sqm"] > 0].copy()

    # 10a(1000㎡)당 수확량 계산
    df["yield_per_10a"] = (df["yield_kg"] / df["area_sqm"] * 1000).round(2)

    # 이상치 제거 (10a당 100kg 미만 또는 100,000kg 초과는 입력 오류)
    df = df[(df["yield_per_10a"] >= 100) & (df["yield_per_10a"] <= 100000)]

    out_cols = ["farm_id", "crop", "year", "yield_kg", "area_sqm",
                "yield_per_10a", "revenue_krw"]
    if "income_krw" in df.columns:
        out_cols.append("income_krw")
    for loc_col in ["ctynm", "dtnm"]:
        if loc_col in df.columns:
            out_cols.append(loc_col)

    return df[out_cols].reset_index(drop=True)


def main():
    print("=== 소득조사 ETL ===")
    print("1. parquet 로드...")
    raw = load_parquets(IN_DIR)
    if raw.empty:
        print("로드된 데이터 없음.")
        return

    print(f"\n전체 {len(raw):,}행 로드 완료")
    print(f"작물명 샘플: {raw['crpnm'].dropna().unique()[:15].tolist()}")

    print("\n2. 변환 중...")
    out = transform(raw)
    print(f"유효 레코드: {len(out):,}행")

    print("\n작목별 농가·연도 현황:")
    summary = out.groupby("crop").agg(
        농가수=("farm_id", "nunique"),
        연도수=("year", "nunique"),
        연도범위=("year", lambda x: f"{x.min()}~{x.max()}"),
        평균수확량_kg=("yield_per_10a", "mean"),
    ).round(1)
    print(summary.to_string())

    out_path = OUT_DIR / "income_survey_harvest.parquet"
    out.to_parquet(out_path, index=False)
    print(f"\n저장 완료: {out_path} ({len(out):,}행)")


if __name__ == "__main__":
    main()
