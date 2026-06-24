"""M1 피처 준비 – 작물별 분리 처리 (메모리 절약)"""
import sys, gc, warnings
import pandas as pd, numpy as np
warnings.filterwarnings("ignore")

crop = sys.argv[1]
_ROOT = __import__("pathlib").Path(__file__).parent.parent.parent  # C:\smart_farm
OUT  = str(_ROOT / "outputs" / "etl")
DATA = str(_ROOT / "engine" / "data")

ENV_BASE = ["temp_internal_mean","temp_internal_max","temp_internal_min",
            "humidity_int_mean","co2_ppm_mean","solar_rad_mean","solar_rad_sum",
            "temp_external_mean","soil_temp_mean","gdd_cumsum"]

# P4 관수 피처 — 수분 스트레스 지표 (관수통합관리시스템 연동)
IRR_BASE = ["wc_mean","wc_max","wc_min",
            "dr_pct_mean","ec_drain",
            "supply_total","irr_count","nl_pct"]

M1_TGTS  = ["plant_height","leaf_count","leaf_length","leaf_width","crown_diameter"]

# 1. env 로드 (해당 작물만)
env = pd.read_parquet(f"{OUT}/env_daily.parquet",
      filters=[("crop","=",crop)])
env["date"] = pd.to_datetime(env["date"])

# 2. growth 로드 (해당 작물만)
gr = pd.read_parquet(f"{OUT}/growth_daily.parquet",
     filters=[("crop","=",crop)])
gr["date"] = pd.to_datetime(gr["date"])
gr_cols = ["farm_id","crop","season","year","date"] + [c for c in M1_TGTS if c in gr.columns]
gr = gr[gr_cols]

# 3. 빈 데이터 가드
if env.empty:
    print(f"[prep_m1] {crop}: env_daily.parquet에 해당 작물 데이터 없음 — 건너뜀")
    sys.exit(1)
if gr.empty:
    print(f"[prep_m1] {crop}: growth_daily.parquet에 해당 작물 데이터 없음 — 건너뜀")
    sys.exit(1)

# 4. 병합
JOIN = ["farm_id","crop","season","year","date"]
df = env.merge(gr, on=JOIN, how="left")
df = df.sort_values(["farm_id","season","year","date"])
del env, gr; gc.collect()

# 4. ffill 환경 피처 + 관수 피처 (그룹 내)
env_cols = [c for c in df.columns if c in ENV_BASE]
df[env_cols] = df.groupby(["farm_id","season","year"])[env_cols].transform(
    lambda x: x.ffill().bfill())

# 관수 피처: 있는 컬럼만 ffill (없으면 NaN → 모델이 자동 처리)
irr_cols_avail = [c for c in df.columns if c in IRR_BASE]
if irr_cols_avail:
    df[irr_cols_avail] = df.groupby(["farm_id","season","year"])[irr_cols_avail].transform(
        lambda x: x.ffill().bfill())
    print(f"  관수 피처 {len(irr_cols_avail)}개 포함: {irr_cols_avail}")
else:
    print("  ⚠️  관수 피처 없음 — 환경 피처만으로 학습 (관수시스템 연동 시 자동 추가됨)")

# 5. lag / rolling (환경 피처 + 관수 피처)
grp = df.groupby(["farm_id","season","year"])
all_feat_base = ENV_BASE + [c for c in IRR_BASE if c in df.columns]
for col in all_feat_base:
    if col not in df.columns: continue
    s = grp[col]
    df[f"{col}_lag7"]   = s.shift(7)
    df[f"{col}_lag14"]  = s.shift(14)
    df[f"{col}_roll7"]  = s.shift(1).transform(lambda x: x.rolling(7, min_periods=3).mean())
    df[f"{col}_roll14"] = s.shift(1).transform(lambda x: x.rolling(14, min_periods=5).mean())
gc.collect()

# 6. M1 학습행: target이 하나라도 있는 행
tgt_cols = [c for c in M1_TGTS if c in df.columns]
mask = df[tgt_cols].notna().any(axis=1)
m1 = df[mask].copy()

print(f"{crop}: 전체{len(df):,}행 → M1학습{len(m1):,}행 | 컬럼{len(m1.columns)}개")
print(f"  target 분포: " + " | ".join(f"{c}:{m1[c].notna().sum()}" for c in tgt_cols))

import os
os.makedirs(DATA, exist_ok=True)
m1.to_parquet(f"{DATA}/m1_{crop}.parquet", index=False)
del df, m1; gc.collect()
