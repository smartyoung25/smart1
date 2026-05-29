"""M2 v4 - Optuna hyperparameter tuning.

Uses walk-forward CV (same as v2/v3) to minimise mean MAPE across folds.
Searches over XGBoost + LightGBM params jointly, then retrains final ensemble.
Outputs to models/artifacts/{crop_en}/candidate/ for model gate.
"""
import sys, os, gc, pickle, json, warnings
import numpy as np, pandas as pd
import optuna
from sklearn.metrics import mean_absolute_percentage_error, r2_score
import xgboost as xgb, lightgbm as lgb
warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)

crop = sys.argv[1]
N_TRIALS = int(sys.argv[2]) if len(sys.argv) > 2 else 60

_ROOT = __import__("pathlib").Path(__file__).parent.parent.parent  # C:\smart_farm
OUT  = str(_ROOT / "outputs" / "etl")
ARTS = str(_ROOT / "models" / "artifacts")
CROP_DIR = {"딸기":"strawberry","방울토마토":"cherry_tomato","완숙토마토":"tomato",
            "참외":"melon","파프리카":"paprika"}
art_dir  = f"{ARTS}/{CROP_DIR.get(crop,crop)}"
cand_dir = f"{art_dir}/candidate"
os.makedirs(cand_dir, exist_ok=True)

BASE_TEMP    = {"딸기":5.0,"방울토마토":10.0,"완숙토마토":10.0,"참외":10.0,"파프리카":10.0}
OPT_TEMP_MAX = {"딸기":25.0,"방울토마토":30.0,"완숙토마토":30.0,"참외":30.0,"파프리카":28.0}
base_temp    = BASE_TEMP.get(crop, 10.0)
opt_temp_max = OPT_TEMP_MAX.get(crop, 30.0)

print(f"\n[M2-v4 Optuna] {crop}  trials={N_TRIALS}")

# ── Data loading (identical to v3) ───────────────────────────────────────────
env  = pd.read_parquet(f"{OUT}/env_daily.parquet",  filters=[("crop","=",crop)])
prod = pd.read_parquet(f"{OUT}/prod_daily.parquet", filters=[("crop","=",crop)])
farm = pd.read_parquet(f"{OUT}/farm_meta.parquet")
farm = farm[farm["crop"]==crop]
env["date"]  = pd.to_datetime(env["date"])
prod["date"] = pd.to_datetime(prod["date"])

ENV_NUM = ["temp_internal_mean","temp_internal_max","temp_internal_min",
           "humidity_int_mean","co2_ppm_mean","solar_rad_mean","solar_rad_sum",
           "temp_external_mean","gdd_cumsum"]
grp_key = ["farm_id","crop","season","year"]

env_agg = {f"{c}_mean": pd.NamedAgg(c,"mean") for c in ENV_NUM if c in env.columns}
env_agg.update({f"{c}_std": pd.NamedAgg(c,"std") for c in ENV_NUM if c in env.columns})
if "gdd_cumsum" in env.columns: env_agg["gdd_max"] = pd.NamedAgg("gdd_cumsum","max")
env_agg["days"] = pd.NamedAgg("date","count")

def _gdd(s): return float(np.clip(s - base_temp, 0, None).sum())
def _cold(s): return float((s < base_temp).sum())
def _heat(s): return float((s > opt_temp_max).sum())

def build_features(env_df):
    base_s = env_df.groupby(grp_key).agg(**env_agg).reset_index()
    rows = []
    for name, g in env_df.groupby(grp_key):
        r = dict(zip(grp_key, name if isinstance(name,tuple) else (name,)))
        tm = g["temp_internal_mean"] if "temp_internal_mean" in g.columns else pd.Series([], dtype=float)
        r["gdd_recomputed"]   = _gdd(tm) if len(tm) else np.nan
        r["cold_day_count"]   = _cold(tm) if len(tm) else np.nan
        r["heat_stress_days"] = _heat(tm) if len(tm) else np.nan
        r["temp_std_daily"]   = float(tm.std()) if len(tm) else np.nan
        if "temp_internal_max" in g.columns and "temp_internal_min" in g.columns:
            r["temp_range_mean"] = float((g["temp_internal_max"]-g["temp_internal_min"]).mean())
        else: r["temp_range_mean"] = np.nan
        r["solar_rad_cumsum"] = float(g["solar_rad_sum"].sum()) if "solar_rad_sum" in g.columns else np.nan
        r["co2_ppm_std"]      = float(g["co2_ppm_mean"].std()) if "co2_ppm_mean" in g.columns else np.nan
        rows.append(r)
    extra = pd.DataFrame(rows)
    return base_s.merge(extra, on=grp_key, how="left")

print("  피처 구성 중...")
env_s  = build_features(env)
prod_s = prod.groupby(grp_key).agg(
    yield_kg=("yield_kg","sum"), revenue_krw=("revenue_krw","sum"),
    ship_days=("date","count")).reset_index()

df = env_s.merge(prod_s, on=grp_key, how="inner")
df = df.merge(farm[["farm_id","crop","season","plant_area_m2"]].drop_duplicates(),
              on=["farm_id","crop","season"], how="left")
df = df[(df["yield_kg"]>0) & df["yield_kg"].notna()]
lo, hi = df["yield_kg"].quantile([0.02,0.98])
df = df[(df["yield_kg"]>=lo) & (df["yield_kg"]<=hi)].copy()

farm_hist = df.groupby("farm_id")["yield_kg"].agg(
    farm_yield_mean="mean", farm_yield_std="std", farm_n="count").reset_index()
df = df.merge(farm_hist, on="farm_id", how="left")
df["yield_ratio"]      = df["yield_kg"] / df["farm_yield_mean"].clip(lower=1)
df["log_yield"]        = np.log1p(df["yield_kg"])
df["log_yield_ratio"]  = np.log1p(df["yield_ratio"])
df["season_num"]       = pd.to_numeric(df["season"], errors="coerce").fillna(1)
df["log_area"]         = np.log1p(df["plant_area_m2"].fillna(df["plant_area_m2"].median()))
df["gdd_per_day"]      = df["gdd_recomputed"] / df["days"].clip(lower=1)
df["cold_day_frac"]    = df["cold_day_count"] / df["days"].clip(lower=1)
df["heat_stress_frac"] = df["heat_stress_days"] / df["days"].clip(lower=1)

EXCL = ["farm_id","crop","season","yield_kg","revenue_krw",
        "log_yield","log_yield_ratio","yield_ratio"]
FEAT = [c for c in df.columns if c not in EXCL
        and df[c].dtype in [np.float64,np.float32,np.int64,np.int32]]
print(f"  시즌 {len(df)} | 농가 {df['farm_id'].nunique()} | 피처 {len(FEAT)}")

years = sorted(df["year"].unique())

# ── Pick best target first (quick fixed-param pass, same as v3) ──────────────
def _quick_mape(tgt_key, params):
    mapes = []
    for i in range(2, len(years)):
        tr = df[df["year"].isin(years[:i])]
        va = df[df["year"]==years[i]]
        if len(va) < 3: continue
        med = tr[FEAT].median()
        m = xgb.XGBRegressor(**params, verbosity=0, n_jobs=2)
        m.fit(tr[FEAT].fillna(med), tr[tgt_key].values)
        pred_log = m.predict(va[FEAT].fillna(med))
        if tgt_key == "log_yield_ratio":
            pred_kg = np.expm1(pred_log) * va["farm_yield_mean"].values
        else:
            pred_kg = np.expm1(np.maximum(pred_log,0))
        mapes.append(mean_absolute_percentage_error(va["yield_kg"].values, np.maximum(pred_kg,1))*100)
        del m
    return float(np.mean(mapes)) if mapes else 999.0

_FIXED = dict(n_estimators=60, max_depth=3, learning_rate=0.1, subsample=0.7,
              colsample_bytree=0.7, reg_alpha=1.0, reg_lambda=5.0, min_child_weight=10,
              tree_method="hist", random_state=42)
best_tgt = min(["log_yield","log_yield_ratio"], key=lambda t: _quick_mape(t, _FIXED))
print(f"  best target: {best_tgt}")

# ── Optuna objective ─────────────────────────────────────────────────────────
def objective(trial):
    model_type = trial.suggest_categorical("model_type", ["xgb", "lgb", "ensemble"])
    max_depth  = trial.suggest_int("max_depth", 2, 6)
    lr         = trial.suggest_float("learning_rate", 0.02, 0.3, log=True)
    n_est      = trial.suggest_int("n_estimators", 40, 200)
    subsample  = trial.suggest_float("subsample", 0.5, 1.0)
    colsample  = trial.suggest_float("colsample_bytree", 0.5, 1.0)
    reg_alpha  = trial.suggest_float("reg_alpha", 0.01, 10.0, log=True)
    reg_lambda = trial.suggest_float("reg_lambda", 0.1, 20.0, log=True)
    mcw        = trial.suggest_int("min_child_weight", 3, 30)

    mapes = []
    for i in range(2, len(years)):
        tr = df[df["year"].isin(years[:i])]
        va = df[df["year"]==years[i]]
        if len(va) < 3: continue
        med = tr[FEAT].median()
        Xtr = tr[FEAT].fillna(med).values
        ytr = tr[best_tgt].values
        Xva = va[FEAT].fillna(med).values

        if model_type in ("xgb", "ensemble"):
            xm = xgb.XGBRegressor(
                n_estimators=n_est, max_depth=max_depth, learning_rate=lr,
                subsample=subsample, colsample_bytree=colsample,
                reg_alpha=reg_alpha, reg_lambda=reg_lambda, min_child_weight=mcw,
                tree_method="hist", random_state=42, n_jobs=2, verbosity=0)
            xm.fit(Xtr, ytr)
            pred_x = xm.predict(Xva)
            del xm

        if model_type in ("lgb", "ensemble"):
            num_leaves = max(7, 2**max_depth - 1)
            lm = lgb.LGBMRegressor(
                n_estimators=n_est, max_depth=max_depth, learning_rate=lr,
                num_leaves=num_leaves, subsample=subsample, colsample_bytree=colsample,
                reg_alpha=reg_alpha, reg_lambda=reg_lambda, min_child_samples=mcw,
                random_state=42, n_jobs=2, verbose=-1)
            lm.fit(Xtr, ytr)
            pred_l = lm.predict(Xva)
            del lm

        if model_type == "xgb":   pred_log = pred_x
        elif model_type == "lgb": pred_log = pred_l
        else:                     pred_log = 0.5*pred_x + 0.5*pred_l

        if best_tgt == "log_yield_ratio":
            pred_kg = np.expm1(pred_log) * va["farm_yield_mean"].values
        else:
            pred_kg = np.expm1(np.maximum(pred_log,0))
        mapes.append(mean_absolute_percentage_error(va["yield_kg"].values, np.maximum(pred_kg,1))*100)

    return float(np.mean(mapes)) if mapes else 999.0

print(f"  Optuna 탐색 중 (trials={N_TRIALS})...")
study = optuna.create_study(direction="minimize",
                            sampler=optuna.samplers.TPESampler(seed=42))
study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)

best = study.best_params
best_cv_mape = study.best_value
print(f"  최적 CV MAPE={best_cv_mape:.1f}%  params={best}")

# ── Final model with best params ─────────────────────────────────────────────
med_all = df[FEAT].median()
X_all   = df[FEAT].fillna(med_all).values
y_all   = df[best_tgt].values

model_type = best.get("model_type","ensemble")
n_est  = best["n_estimators"]; depth = best["max_depth"]; lr = best["learning_rate"]
sub    = best["subsample"];     col   = best["colsample_bytree"]
alpha  = best["reg_alpha"];     lam   = best["reg_lambda"]; mcw = best["min_child_weight"]

xm_f = xgb.XGBRegressor(n_estimators=n_est, max_depth=depth, learning_rate=lr,
    subsample=sub, colsample_bytree=col, reg_alpha=alpha, reg_lambda=lam,
    min_child_weight=mcw, tree_method="hist", random_state=42, n_jobs=2, verbosity=0)
xm_f.fit(X_all, y_all)

lm_f = lgb.LGBMRegressor(n_estimators=n_est, max_depth=depth, learning_rate=lr,
    num_leaves=max(7, 2**depth-1), subsample=sub, colsample_bytree=col,
    reg_alpha=alpha, reg_lambda=lam, min_child_samples=mcw,
    random_state=42, n_jobs=2, verbose=-1)
lm_f.fit(X_all, y_all)

if model_type == "xgb":   pred_tr = xm_f.predict(X_all)
elif model_type == "lgb": pred_tr = lm_f.predict(X_all)
else:                     pred_tr = 0.5*xm_f.predict(X_all) + 0.5*lm_f.predict(X_all)
tr_r2_final = r2_score(y_all, pred_tr)

farm_mean_map = df.groupby("farm_id")["yield_kg"].mean().to_dict()

pkg = {"xgb": xm_f, "lgb": lm_f,
       "feat_cols": FEAT, "feat_median": med_all.to_dict(),
       "target": best_tgt, "mape": best_cv_mape, "train_r2": tr_r2_final,
       "gate_pass": bool(best_cv_mape<=25),
       "farm_yield_mean": farm_mean_map,
       "best_params": best, "model_type": model_type}
meta = {"crop": crop, "crop_en": CROP_DIR.get(crop,crop),
        "version": "v4_optuna",
        "target": best_tgt, "feat_cols": FEAT,
        "mape": round(best_cv_mape,2), "train_r2": round(tr_r2_final,4),
        "gate_pass": bool(best_cv_mape<=25), "n_season": int(len(df)),
        "best_params": best, "model_type": model_type,
        "n_trials": N_TRIALS}

with open(f"{cand_dir}/m2_yield_model.pkl","wb") as f: pickle.dump(pkg,f)
with open(f"{cand_dir}/m2_meta.json","w",encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print(f"  저장 -> {cand_dir}  train-R2={tr_r2_final:.3f}")
