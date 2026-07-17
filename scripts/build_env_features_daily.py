"""1분 단위 원천 환경 → 생리학적 월별 피처.

★ 왜 필요한가 (실측 근거):
  기존 load_env_monthly 는 원천을 groupby(farm,year,month).mean() 으로 뭉갠다.
  그런데 원천은 **1분 단위**다(2021 딸기: 213,188행/33농가, 내부온도 99.1% 채워짐).
  월평균 온도 하나로는 수확량 신호가 사라진다 — 실측: 환경 반응 모델의 CV R² 가
  전 작목 음수(-0.24~-1.39)였고, temp_internal 과 수확량의 상관이 **-0.274**로
  부호까지 뒤집혔다(딸기는 겨울 촉성이라 고온기에 수확이 적다 — 온도 탓이 아니라 작기 탓).

  제품의 도메인 지식이 말하는 변수는 월평균이 아니다:
    · 일사 적산(J/cm²) — P1~P6 관수 트리거의 기준
    · DLI(PAR 계수 4.57) · VPD 밴드(0.4~0.6 kPa) · 주야 온도차(DIF)
  이들은 **분 단위에서만 계산 가능**하다. 월평균으로는 만들 수 없다.

★ 만드는 피처(월별, 농가별):
  누적/적산 : solar_cum_mj(월 누적 일사), dli_mean(일평균 DLI)
  분포/스트레스: temp_day_mean·temp_night_mean·dif_mean(주야차),
                heat_hours_pct(고온 시간비율), cold_hours_pct(저온)
  VPD       : vpd_mean, vpd_in_band_pct(0.4~0.6 kPa 체류 비율)
  CO2       : co2_day_mean(주간만 — 야간 CO₂는 광합성과 무관)

★ 한계(명시):
  · 결측률이 변수마다 다르다(외부온도 69%·일사 53%·토양온도 27%). 결측 많은 변수는
    월 집계 시 표본이 편중될 수 있어, 관측 수(n_obs)를 함께 남긴다.
  · 이 피처가 수확량을 설명하는지는 **별도 검증**이 답한다(train_env_response.py).
    피처를 만들었다고 인과가 생기지는 않는다.

사용:
  PYTHONPATH=C:/smart_farm python scripts/build_env_features_daily.py --crop 딸기
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

CACHE = ROOT / ".cache" / "training"

# 주간 정의 — 일출/일몰 대신 고정 시각(농가·계절별 편차는 감수, 단순·재현성 우선)
_DAY_START, _DAY_END = 8, 18
# 스트레스 임계 — 작목 공통 근사(작목별 최적범위는 crop_config 에 있으나
# 여기서는 '이탈 비율'만 재므로 넓은 공통값을 쓴다)
_HEAT_C, _COLD_C = 30.0, 8.0
# VPD 밴드 — 제품 KPI(CLAUDE.md): 0.4(하한)~0.6(상한) kPa
_VPD_LO, _VPD_HI = 0.4, 0.6
# DLI 변환: PAR 계수 4.57 μmol/J (CLAUDE.md — 누락 시 ~4.6배 과소 오류)
_PAR_COEF = 4.57


def _vpd(temp_c: pd.Series, rh_pct: pd.Series) -> pd.Series:
    """VPD(kPa) = SVP × (1 − RH/100). climate_plan.vpd() 와 같은 식."""
    svp = 0.6108 * np.exp(17.27 * temp_c / (temp_c + 237.3))
    return svp * (1.0 - rh_pct / 100.0)


def build(crop_ko: str, years: list[int] | None = None) -> pd.DataFrame:
    from scripts.train_stage2_yield import _read_crop_csvs, _norm_farm_id
    from models.crop_config import YEARS

    out = []
    for year in (years or YEARS):
        frames = _read_crop_csvs(year, crop_ko)
        env_f = [f for f in frames if "측정시간" in f.columns]
        if not env_f:
            continue
        df = pd.concat(env_f, ignore_index=True)
        df["dt"] = pd.to_datetime(df["측정시간"], errors="coerce")
        df = df[df["dt"].notna()].copy()
        if df.empty:
            continue
        fc = next((c for c in ["농가명", "농가ID"] if c in df.columns), None)
        df["farm_id"] = (df[fc].astype(str).str.strip().apply(_norm_farm_id)
                         if fc else "unknown")
        df["year"] = year
        df["month"] = df["dt"].dt.month
        df["hour"] = df["dt"].dt.hour
        df["date"] = df["dt"].dt.date

        for src, dst in (("온도_내부", "t_in"), ("상대습도_내부", "rh_in"),
                         ("잔존CO2", "co2"), ("일사량_외부", "solar"),
                         ("온도_외부", "t_out")):
            df[dst] = pd.to_numeric(df[src], errors="coerce") if src in df.columns else np.nan

        # 물리적으로 불가능한 값 제거 — 원천에 이상치가 있다
        df.loc[(df["t_in"] < -5) | (df["t_in"] > 55), "t_in"] = np.nan
        df.loc[(df["rh_in"] < 0) | (df["rh_in"] > 100), "rh_in"] = np.nan
        df.loc[(df["co2"] < 0) | (df["co2"] > 5000), "co2"] = np.nan
        df.loc[(df["solar"] < 0) | (df["solar"] > 1500), "solar"] = np.nan

        df["vpd"] = _vpd(df["t_in"], df["rh_in"])
        df["is_day"] = df["hour"].between(_DAY_START, _DAY_END - 1)

        # ── 일별 집계 먼저(일사 적산은 '하루' 단위가 의미 단위다) ──────────────
        g = df.groupby(["farm_id", "year", "month", "date"])
        daily = g.agg(
            t_day=("t_in", lambda s: s[df.loc[s.index, "is_day"]].mean()),
            t_night=("t_in", lambda s: s[~df.loc[s.index, "is_day"]].mean()),
            solar_mean=("solar", "mean"),
            solar_n=("solar", "count"),
            vpd_mean=("vpd", "mean"),
            vpd_in=("vpd", lambda s: float(s.between(_VPD_LO, _VPD_HI).mean() * 100)),
            heat_pct=("t_in", lambda s: float((s > _HEAT_C).mean() * 100)),
            cold_pct=("t_in", lambda s: float((s < _COLD_C).mean() * 100)),
            co2_day=("co2", lambda s: s[df.loc[s.index, "is_day"]].mean()),
            n_obs=("t_in", "count"),
        ).reset_index()

        # 일 누적 일사(MJ/m²) = 평균 W/m² × 86400초 / 1e6. 관측이 하루를 덮을 때만 유효.
        daily["solar_mj"] = daily["solar_mean"] * 86400 / 1e6
        # DLI(mol/m²/d) = 누적일사(MJ) × PAR계수 — CLAUDE.md 4.57
        daily["dli"] = daily["solar_mj"] * _PAR_COEF
        daily["dif"] = daily["t_day"] - daily["t_night"]

        # ── 월별 집계 ────────────────────────────────────────────────────────
        m = (daily.groupby(["farm_id", "year", "month"])
             .agg(solar_cum_mj=("solar_mj", "sum"),
                  dli_mean=("dli", "mean"),
                  temp_day_mean=("t_day", "mean"),
                  temp_night_mean=("t_night", "mean"),
                  dif_mean=("dif", "mean"),
                  heat_hours_pct=("heat_pct", "mean"),
                  cold_hours_pct=("cold_pct", "mean"),
                  vpd_mean=("vpd_mean", "mean"),
                  vpd_in_band_pct=("vpd_in", "mean"),
                  co2_day_mean=("co2_day", "mean"),
                  n_days=("date", "nunique"),
                  n_obs=("n_obs", "sum"))
             .reset_index())
        out.append(m)
        logger.info("  %d년: %d농가 · %d행", year, m["farm_id"].nunique(), len(m))

    if not out:
        return pd.DataFrame()
    res = pd.concat(out, ignore_index=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"env_daily_{crop_ko}.parquet"
    res.to_parquet(p)
    logger.info("  저장: %s (%d행)", p, len(res))
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop", default="딸기")
    a = ap.parse_args()
    df = build(a.crop)
    if df.empty:
        print("환경 원천 없음")
        return 1
    print(f"\n생리학적 월별 환경 피처 — {a.crop}  ({len(df)}행)\n")
    cols = ["solar_cum_mj", "dli_mean", "temp_day_mean", "temp_night_mean",
            "dif_mean", "heat_hours_pct", "cold_hours_pct",
            "vpd_mean", "vpd_in_band_pct", "co2_day_mean"]
    print(df[cols].describe().T[["count", "mean", "std", "min", "max"]].round(2).to_string())
    print(f"\n  농가 {df['farm_id'].nunique()} · 연도 {sorted(df['year'].unique())}")
    print(f"  월평균 관측수: {df['n_obs'].mean():,.0f} (1분 단위 원천)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
