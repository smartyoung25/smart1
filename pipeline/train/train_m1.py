"""M1 생육 예측 – autoregressive + 시계열 분할 버전"""
import sys, os, gc, pickle, json, warnings
import numpy as np, pandas as pd
from sklearn.metrics import r2_score, mean_absolute_error
import xgboost as xgb, lightgbm as lgb
warnings.filterwarnings("ignore")

crop = sys.argv[1]
DATA = "/sessions/lucid-affectionate-bardeen/mnt/smart_farm/engine/data"
ARTS = "/sessions/lucid-affectionate-bardeen/mnt/smart_farm/models/artifacts"
CROP_DIR = {"딸기":"strawberry","방울토마토":"cherry_tomato","완숙토마토":"tomato",
            "참외":"melon","파프리카":"paprika"}

art_dir = f"{ARTS}/{CROP_DIR.get(crop,crop)}"
os.makedirs(art_dir, exist_ok=True)

df = pd.read_parquet(f"{DATA}/m1_{crop}.parquet")
df["date"] = pd.to_datetime(df["date"])
df["season_num"] = pd.to_numeric(df["season"], errors="coerce").fillna(1)
df = df.sort_values(["farm_id","season_num","year","date"])
print(f"[M1] {crop}: {len(df):,}행")

TGT_ALL = ["plant_height","leaf_count","leaf_length","leaf_width","crown_diameter"]
ID_COLS = ["farm_id","crop","season","year","date","source"]

# autoregressive: 각 target의 lag7/lag14 추가
grp = df.groupby(["farm_id","season_num","year"])
for tgt in TGT_ALL:
    if tgt not in df.columns: continue
    s = grp[tgt]
    df[f"{tgt}_lag7"]  = s.shift(7)
    df[f"{tgt}_lag14"] = s.shift(14)

FEAT_COLS = [c for c in df.columns
             if c not in ID_COLS + TGT_ALL
             and df[c].dtype in [np.float64,np.float32,np.int64,np.int32]]
print(f"피처 수: {len(FEAT_COLS)}")

# 시계열 분할: 시간 기준 앞 80% → train, 뒤 20% → test
dates = df["date"].sort_values().unique()
cutoff = dates[int(len(dates)*0.8)]
tr_mask = df["date"] <= cutoff
va_mask = df["date"] >  cutoff
print(f"분할: train={tr_mask.sum():,} ({cutoff.date()} 이전) / val={va_mask.sum():,}")

XP = dict(n_estimators=200, max_depth=5, learning_rate=0.08,
          subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
          tree_method="hist", random_state=42, n_jobs=2, verbosity=0)
LP = dict(n_estimators=200, max_depth=5, learning_rate=0.08,
          num_leaves=31, subsample=0.8, colsample_bytree=0.8,
          min_child_samples=5, random_state=42, n_jobs=2, verbose=-1)

results, models = {}, {}

for tgt in TGT_ALL:
    if tgt not in df.columns or df[tgt].notna().sum() < 100:
        print(f"  SKIP {tgt}"); continue

    sub = df[FEAT_COLS+[tgt]].dropna(subset=[tgt])
    med = sub[FEAT_COLS].median()
    X = sub[FEAT_COLS].fillna(med)
    y = sub[tgt].values

    tr_i = df.index.isin(sub.index) & tr_mask
    va_i = df.index.isin(sub.index) & va_mask

    # sub에서 분할 인덱스 재계산
    sub2 = df[FEAT_COLS+[tgt]].copy()
    sub2 = sub2.dropna(subset=[tgt])
    tr_sub = sub2.index[df.loc[sub2.index,"date"] <= cutoff]
    va_sub = sub2.index[df.loc[sub2.index,"date"] >  cutoff]

    if len(tr_sub)<50 or len(va_sub)<20:
        print(f"  SKIP {tgt} (데이터부족)"); continue

    X_tr = sub2.loc[tr_sub,FEAT_COLS].fillna(med)
    y_tr = sub2.loc[tr_sub,tgt].values
    X_va = sub2.loc[va_sub,FEAT_COLS].fillna(med)
    y_va = sub2.loc[va_sub,tgt].values

    xm = xgb.XGBRegressor(**XP); xm.fit(X_tr, y_tr)
    lm = lgb.LGBMRegressor(**LP); lm.fit(X_tr, y_tr)
    px, pl = xm.predict(X_va), lm.predict(X_va)
    pe = 0.5*px + 0.5*pl

    r2e = r2_score(y_va, pe)
    r2x = r2_score(y_va, px)
    r2l = r2_score(y_va, pl)
    gate = "✅" if r2e >= 0.62 else "⚠"
    mae = mean_absolute_error(y_va, pe)
    print(f"  {tgt:<16}: R²={r2e:.4f} {gate}  XGB={r2x:.3f} LGB={r2l:.3f}  MAE={mae:.2f}")

    # 전체로 최종 학습
    X_all = sub2[FEAT_COLS].fillna(med)
    y_all = sub2[tgt].values
    xm_f = xgb.XGBRegressor(**XP); xm_f.fit(X_all, y_all)
    lm_f = lgb.LGBMRegressor(**LP); lm_f.fit(X_all, y_all)
    models[tgt] = {"xgb":xm_f,"lgb":lm_f,
                   "feat_cols":FEAT_COLS,"feat_median":med.to_dict(),"r2":r2e,"mae":mae}
    results[tgt] = {"r2_ensemble":round(r2e,4),"r2_xgb":round(r2x,4),
                    "r2_lgb":round(r2l,4),"mae":round(mae,4),
                    "gate_pass":r2e>=0.62,"n_train":len(y_all)}
    del xm, lm, xm_f, lm_f; gc.collect()

meta = {"crop":crop,"crop_en":CROP_DIR.get(crop,crop),
        "feat_cols":FEAT_COLS,"targets":results}
with open(f"{art_dir}/m1_growth_model.pkl","wb") as f:
    pickle.dump({"models":models,"meta":meta},f)
with open(f"{art_dir}/m1_meta.json","w",encoding="utf-8") as f:
    json.dump(meta,f,ensure_ascii=False,indent=2)

g = sum(1 for v in results.values() if v["gate_pass"])
print(f"  저장: {art_dir}/m1_growth_model.pkl | 게이트 {g}/{len(results)} 통과")
