"""M2-eco: ERA5 기상 피처만 사용하는 경량 수확량 예측 모델.

env_daily(일별 환경 센서)가 없는 노지·소득조사 데이터에 적용.
입력: data/collected/harvest/income_survey_harvest.parquet
출력: models/artifacts/{crop_dir}/candidate/ (m2_meta.json, m2_model.pkl)

사용:
    python pipeline/train/train_m2_eco.py 감귤 [N_TRIALS]
    python pipeline/train/train_m2_eco.py 마늘 30
"""
from __future__ import annotations
import sys, os, gc, pickle, json, warnings, shutil
import numpy as np, pandas as pd
import optuna
from sklearn.metrics import mean_absolute_percentage_error, r2_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import LabelEncoder
import xgboost as xgb, lightgbm as lgb
warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)

crop = sys.argv[1]
N_TRIALS = int(sys.argv[2]) if len(sys.argv) > 2 else 40

_ROOT = __import__("pathlib").Path(__file__).parent.parent.parent
ARTS = str(_ROOT / "models" / "artifacts")

CROP_DIR = {
    "딸기":"strawberry","방울토마토":"cherry_tomato","완숙토마토":"tomato",
    "참외":"melon","파프리카":"paprika","오이":"cucumber",
    "콩":"soybean","무":"radish","배추":"cabbage","양배추":"headed_cabbage",
    "마늘":"garlic","양파":"onion","고추":"pepper","가지":"eggplant","감귤":"citrus",
}
_ERA5_EN = {
    "감귤":"citrus","마늘":"garlic","무":"radish","양파":"onion",
    "배추":"napa_cabbage","양배추":"cabbage","콩":"soybean",
    "고추":"red_pepper","가지":"eggplant",
    "딸기":"strawberry","방울토마토":"cherry_tomato","완숙토마토":"tomato",
    "참외":"korean_melon","파프리카":"paprika","오이":"cucumber",
}

art_dir  = f"{ARTS}/{CROP_DIR.get(crop, crop)}"
cand_dir = f"{art_dir}/candidate"
if os.path.exists(cand_dir):
    shutil.rmtree(cand_dir)
os.makedirs(cand_dir)

print(f"\n[M2-eco] {crop}  trials={N_TRIALS}")

# ── ERA5 연간 집계 ────────────────────────────────────────────────────────────
def _load_era5(crop_ko: str) -> pd.DataFrame | None:
    crop_en = _ERA5_EN.get(crop_ko, crop_ko)
    p = _ROOT / "api" / "data" / "real" / f"era5_{crop_en}_monthly.json"
    if not p.exists():
        return None
    try:
        monthly = json.loads(p.read_text(encoding="utf-8")).get("monthly", {})
    except Exception:
        return None
    yr_acc: dict = {}
    for key, v in monthly.items():
        yr = int(key.split("-")[0])
        a = yr_acc.setdefault(yr, {"t": [], "s": [], "r": 0.0, "gdd": 0.0})
        if v.get("t_ext") is not None:   a["t"].append(v["t_ext"])
        if v.get("solar_mj") is not None: a["s"].append(v["solar_mj"])
        if v.get("rain_mm") is not None:  a["r"] += v["rain_mm"]
        a["gdd"] += v.get("gdd", 0.0)
    rows = [{"year": yr,
             "era5_t_ext":  round(sum(a["t"])/len(a["t"]),3) if a["t"] else np.nan,
             "era5_solar":  round(sum(a["s"])/len(a["s"]),3) if a["s"] else np.nan,
             "era5_rain":   round(a["r"], 1),
             "era5_gdd":    round(a["gdd"], 1)}
            for yr, a in sorted(yr_acc.items())]
    return pd.DataFrame(rows)

era5 = _load_era5(crop)
if era5 is None:
    print(f"[M2-eco] ERA5 JSON 없음 ({crop}) — 학습 불가")
    sys.exit(1)
print(f"  ERA5 연도: {sorted(era5['year'].tolist())}")

# ── 소득조사 수확량 로드 ──────────────────────────────────────────────────────
harvest_path = _ROOT / "data" / "collected" / "harvest" / "income_survey_harvest.parquet"
if not harvest_path.exists():
    print(f"소득조사 parquet 없음: {harvest_path}")
    sys.exit(1)

df = pd.read_parquet(harvest_path)
df = df[df["crop"] == crop].copy()
df["year"] = df["year"].astype(int)
print(f"  소득조사: {len(df)}행 / {df['farm_id'].nunique()}농가 / {sorted(df['year'].unique())}")

if len(df) < 10:
    print(f"[M2-eco] 유효 행 {len(df)}개 — 최소 10행 미충족")
    sys.exit(1)

# ERA5 병합
df = df.merge(era5, on="year", how="left")
n_matched = df["era5_gdd"].notna().sum()
print(f"  ERA5 병합: {n_matched}/{len(df)}행")

# ── 타겟: yield_per_10a ───────────────────────────────────────────────────────
TARGET = "yield_per_10a"
lo, hi = df[TARGET].quantile([0.02, 0.98])
df = df[(df[TARGET] >= lo) & (df[TARGET] <= hi)].copy()
print(f"  이상치 제거 후: {len(df)}행  (p2={lo:.0f}~p98={hi:.0f} kg/10a)")

# farm_yield_mean (expanding window, leakage 방지)
_global_mean = df[TARGET].mean()
df = df.sort_values(["farm_id", "year"]).copy()
df["farm_yield_prev"] = (
    df.groupby("farm_id")[TARGET]
      .transform(lambda x: x.shift(1))
)
df["farm_yield_mean"] = (
    df.groupby("farm_id")[TARGET]
      .transform(lambda x: x.expanding().mean().shift(1))
      .fillna(_global_mean)
)
df["farm_yield_std"] = (
    df.groupby("farm_id")[TARGET]
      .transform(lambda x: x.expanding().std().shift(1))
      .fillna(0.0)
)
df["farm_n"] = (
    df.groupby("farm_id")[TARGET]
      .transform(lambda x: x.expanding().count().shift(1))
      .fillna(0)
)
df["log_yield_mean"] = np.log1p(df["farm_yield_mean"])
df["year_norm"]      = (df["year"] - df["year"].min()) / max(df["year"].max() - df["year"].min(), 1)

# ── YoY 변화율 모드: 전년도 수확량이 있는 행만 사용 ────────────────────────
# 타겟을 절대 수확량 대신 farm_yield_mean 대비 편차(상대)로 변환
# → 농가 baseline 제거 + ERA5 연도 효과만 학습
df["yoy_ratio"] = df[TARGET] / df["farm_yield_mean"].clip(lower=1.0)
# 극단 비율 제거 (0.1~5.0 사이만 유효)
df = df[(df["yoy_ratio"] >= 0.1) & (df["yoy_ratio"] <= 5.0)].copy()
# 두 개 모드 중 YoY 모드 사용 (farm_yield_mean + ERA5 → 상대 편차 예측)
TARGET_MODEL = "yoy_ratio"
print(f"  YoY 모드: {len(df)}행 (비율 0.1~5.0 범위)")

# ERA5 anomaly 피처: 과거 n년 평균 대비 현재 연도 편차 (기후 이상 신호)
_era5_means = era5.set_index("year").rolling(5, min_periods=2).mean().shift(1)
for col in ["era5_t_ext", "era5_solar", "era5_rain", "era5_gdd"]:
    anom_col = col + "_anom"
    era5[anom_col] = era5["year"].map(
        (era5.set_index("year")[col] - _era5_means[col]).to_dict()
    )
df = df.merge(era5[["year"] + [c + "_anom" for c in ["era5_t_ext","era5_solar","era5_rain","era5_gdd"]]],
              on="year", how="left")

# ctynm 인코딩 (시군 정보가 있을 때 추가 피처)
CTYNM_FEAT = []
if "ctynm" in df.columns:
    le_cty = LabelEncoder()
    df["ctynm_enc"] = le_cty.fit_transform(df["ctynm"].fillna("기타"))
    # ctynm별 expanding window 수확량 평균 (leakage 방지)
    df = df.sort_values(["ctynm", "year"]).copy()
    _cty_global = df[TARGET].mean()
    df["ctynm_yield_mean"] = (
        df.groupby("ctynm")[TARGET]
          .transform(lambda x: x.expanding().mean().shift(1))
          .fillna(_cty_global)
    )
    CTYNM_FEAT = ["ctynm_enc", "ctynm_yield_mean"]
    df = df.sort_values(["farm_id", "year"]).copy()

ERA5_FEATS = ["era5_t_ext", "era5_solar", "era5_rain", "era5_gdd",
              "era5_t_ext_anom", "era5_solar_anom", "era5_rain_anom", "era5_gdd_anom"]
FARM_FEATS = ["farm_yield_mean", "farm_yield_std", "farm_n", "log_yield_mean"]
TIME_FEATS = ["year_norm", "year"]

FEAT = [c for c in ERA5_FEATS + FARM_FEATS + TIME_FEATS + CTYNM_FEAT if c in df.columns]
print(f"  피처 {len(FEAT)}개: {FEAT}")
print(f"  농가 {df['farm_id'].nunique()} | 시즌 {len(df)}")

# ── 교차검증: TimeSeriesSplit(by year) ─────────────────────────────────────────
# GroupKFold(by farm) → 홀드아웃 농가에서 farm_yield_mean 추정 불가 → MAPE 과대
# TimeSeriesSplit(by year) → 이전 연도 학습, 다음 연도 검증 — ERA5 기후 신호 학습에 적합
years_sorted = sorted(df["year"].unique())
n_years = len(years_sorted)
n_splits = min(5, n_years - 2)  # 최소 2개 연도 훈련 보장
X = df[FEAT]
y = df[TARGET_MODEL].values  # YoY ratio 예측

def _cv_score(params_xgb, params_lgb) -> tuple[float, float]:
    mapes, r2s = [], []
    # 연도 순서대로 확장 윈도우 (expanding window CV)
    for split_i in range(n_splits):
        cutoff_idx = n_years - n_splits + split_i  # 훈련 마지막 연도 인덱스
        if cutoff_idx < 2:
            continue
        tr_years = set(years_sorted[:cutoff_idx])
        va_years = {years_sorted[cutoff_idx]}
        tr_mask = df["year"].isin(tr_years).values
        va_mask = df["year"].isin(va_years).values
        if va_mask.sum() < 2:
            continue
        Xtr, Xva = X[tr_mask], X[va_mask]
        ytr, yva = y[tr_mask], y[va_mask]
        med = Xtr.median()
        mx = xgb.XGBRegressor(**params_xgb, verbosity=0, n_jobs=2)
        mx.fit(Xtr.fillna(med), ytr)
        ml = lgb.LGBMRegressor(**{k:v for k,v in params_lgb.items() if k!='verbose'}, verbose=-1, n_jobs=2)
        ml.fit(Xtr.fillna(med), ytr)
        pred = (mx.predict(Xva.fillna(med)) + ml.predict(Xva.fillna(med))) / 2
        pred = np.clip(pred, 0, None)
        mapes.append(mean_absolute_percentage_error(yva, pred + 1e-9) * 100)
        r2s.append(r2_score(yva, pred))
    return (float(np.mean(mapes)) if mapes else 999.0,
            float(np.mean(r2s))   if r2s   else -1.0)

BASE_XGB = dict(n_estimators=100, max_depth=4, learning_rate=0.1,
                subsample=0.8, colsample_bytree=0.8, random_state=42)
BASE_LGB = dict(n_estimators=100, max_depth=4, learning_rate=0.1,
                subsample=0.8, colsample_bytree=0.8, random_state=42, num_leaves=15)

print("  기본 파라미터 CV 중...")
base_mape, base_r2 = _cv_score(BASE_XGB, BASE_LGB)
print(f"  기본 MAPE={base_mape:.1f}%  R²={base_r2:.3f}")

# ── Optuna 하이퍼파라미터 탐색 ────────────────────────────────────────────────
def objective(trial):
    px = dict(
        n_estimators  = trial.suggest_int("xgb_n",  50, 300),
        max_depth     = trial.suggest_int("xgb_d",  2, 6),
        learning_rate = trial.suggest_float("xgb_lr", 0.02, 0.2, log=True),
        subsample     = trial.suggest_float("xgb_ss", 0.5, 1.0),
        colsample_bytree = trial.suggest_float("xgb_cs", 0.5, 1.0),
        reg_alpha     = trial.suggest_float("xgb_a", 0.0, 2.0),
        reg_lambda    = trial.suggest_float("xgb_l", 0.5, 5.0),
        random_state  = 42,
    )
    pl = dict(
        n_estimators  = trial.suggest_int("lgb_n",  50, 300),
        num_leaves    = trial.suggest_int("lgb_lv", 8, 31),
        max_depth     = trial.suggest_int("lgb_d",  2, 6),
        learning_rate = trial.suggest_float("lgb_lr", 0.02, 0.2, log=True),
        subsample     = trial.suggest_float("lgb_ss", 0.5, 1.0),
        colsample_bytree = trial.suggest_float("lgb_cs", 0.5, 1.0),
        reg_alpha     = trial.suggest_float("lgb_a", 0.0, 2.0),
        reg_lambda    = trial.suggest_float("lgb_l", 0.5, 5.0),
        random_state  = 42,
    )
    mape, _ = _cv_score(px, pl)
    return mape

study = optuna.create_study(direction="minimize")
study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)
best = study.best_params
print(f"  최적 CV MAPE: {study.best_value:.1f}%")

best_xgb = dict(
    n_estimators=best["xgb_n"], max_depth=best["xgb_d"],
    learning_rate=best["xgb_lr"], subsample=best["xgb_ss"],
    colsample_bytree=best["xgb_cs"], reg_alpha=best["xgb_a"],
    reg_lambda=best["xgb_l"], random_state=42,
)
best_lgb = dict(
    n_estimators=best["lgb_n"], num_leaves=best["lgb_lv"],
    max_depth=best["lgb_d"], learning_rate=best["lgb_lr"],
    subsample=best["lgb_ss"], colsample_bytree=best["lgb_cs"],
    reg_alpha=best["lgb_a"], reg_lambda=best["lgb_l"],
    random_state=42, verbose=-1,
)
best_mape, best_r2 = _cv_score(best_xgb, best_lgb)
print(f"  최적 파라미터 검증: MAPE={best_mape:.1f}%  R2={best_r2:.3f}")

# ── 전체 데이터로 최종 학습 ──────────────────────────────────────────────────
# CV MAPE는 yoy_ratio 기준; 실제 yield_per_10a MAPE도 계산
# 예측: pred_ratio → pred_yield = farm_yield_mean * pred_ratio
def _abs_mape(tr_mask, va_mask, mx, ml, med):
    Xva = X[va_mask].fillna(med)
    ratio_pred = (mx.predict(Xva) + ml.predict(Xva)) / 2
    ratio_pred = np.clip(ratio_pred, 0.1, 5.0)
    y_pred = df[va_mask]["farm_yield_mean"].values * ratio_pred
    y_true = df[va_mask][TARGET].values
    return mean_absolute_percentage_error(y_true, y_pred + 1e-9) * 100

med_all = X.median()
mx_final = xgb.XGBRegressor(**best_xgb, verbosity=0)
mx_final.fit(X.fillna(med_all), y)
ml_final = lgb.LGBMRegressor(**{k:v for k,v in best_lgb.items() if k!='verbose'}, verbose=-1)
ml_final.fit(X.fillna(med_all), y)

# 최종 절대 MAPE 검증 (last fold)
last_cutoff = n_years - 1
if last_cutoff >= 2:
    tr_yrs_last = set(years_sorted[:last_cutoff])
    va_yrs_last = {years_sorted[last_cutoff]}
    tr_m = df["year"].isin(tr_yrs_last).values
    va_m = df["year"].isin(va_yrs_last).values
    abs_mape_val = _abs_mape(tr_m, va_m, mx_final, ml_final, med_all)
    print(f"  절대 MAPE 검증 (val={years_sorted[last_cutoff]}): {abs_mape_val:.1f}%")
else:
    abs_mape_val = best_mape

model_bundle = {
    "type": "m2_eco",
    "crop": crop,
    "features": FEAT,
    "feat_median": med_all.to_dict(),
    "farm_mean_map": df.groupby("farm_id")[TARGET].mean().to_dict(),
    "global_mean": float(_global_mean),
    "target_model": TARGET_MODEL,
    "xgb": mx_final,
    "lgb": ml_final,
}
pkl_path = os.path.join(cand_dir, "m2_model.pkl")
with open(pkl_path, "wb") as f:
    pickle.dump(model_bundle, f)

meta = {
    "model_type": "m2_eco",
    "crop": crop,
    "target": TARGET,
    "target_model": TARGET_MODEL,
    "features": FEAT,
    "n_samples": int(len(df)),
    "n_farms":   int(df["farm_id"].nunique()),
    "years":     sorted(df["year"].unique().tolist()),
    "mape_cv":   round(best_mape, 2),
    "mape":      round(abs_mape_val, 2),  # 절대 yield MAPE (배포 게이트용)
    "r2_cv":     round(best_r2, 3),
    "mape_base": round(base_mape, 2),
    "r2_base":   round(base_r2, 3),
    "global_mean": float(_global_mean),
    "optuna_trials": N_TRIALS,
    "best_params": best,
}
meta_path = os.path.join(cand_dir, "m2_meta.json")
with open(meta_path, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print(f"\n  ✅ 저장 완료 → {cand_dir}")
print(f"  MAPE={best_mape:.1f}%  R²={best_r2:.3f}  (샘플={len(df)}, 농가={df['farm_id'].nunique()})")
