"""딸기 Stage1 Optuna 튜닝 스크립트

기존 train_stage1_growth.py의 데이터/피처 파이프라인을 재사용하고
XGB + LGB 하이퍼파라미터를 Optuna로 탐색해 R² > 0.45 달성 시도.

실행:
    python scripts/tune_stage1_strawberry.py [--trials 50]
"""
from __future__ import annotations
import argparse, json, logging, pickle, sys, warnings
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.metrics import r2_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.multioutput import MultiOutputRegressor

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tune_stage1")

CROP = "딸기"
ART_DIR = ROOT / "models" / "artifacts" / "strawberry"


# ── 데이터 로드 (train_stage1_growth.py의 캐시 재사용) ──────────────────────────

def load_stage1_data() -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """stage1 학습 행렬 로드. train_stage1_growth.py 캐시 활용."""
    from scripts.train_stage1_growth import (
        load_env_monthly, load_growth_monthly, build_stage1_matrix,
    )
    from models.crop_config import CROP_CONFIGS

    cfg = CROP_CONFIGS[CROP]
    log.info("환경 데이터 로드...")
    env = load_env_monthly(CROP, use_cache=True)
    log.info("생육 데이터 로드...")
    gr  = load_growth_monthly(CROP, cfg.growth_cols, use_cache=True)
    log.info("Stage1 행렬 구성...")
    df  = build_stage1_matrix(env, gr, cfg)

    target_cols  = [f"growth_{c}" for c in cfg.growth_cols if f"growth_{c}" in df.columns]
    feature_cols = [c for c in df.columns
                    if c not in ["farm_id", "year", "month"] + target_cols
                    and df[c].dtype in [np.float64, np.int64, "Int64", float, int]]

    df_sorted = df.sort_values(["farm_id", "year", "month"]).copy()
    X_raw = df_sorted[feature_cols]
    Y_raw = df_sorted[target_cols]

    valid_mask = Y_raw.notna().any(axis=1)
    X_raw = X_raw[valid_mask]
    Y_raw = Y_raw[valid_mask]

    imputer = SimpleImputer(strategy="median")
    X = imputer.fit_transform(X_raw)
    Y = Y_raw.copy()
    for col in Y.columns:
        med = Y[col].median()
        Y[col] = Y[col].fillna(med if not np.isnan(med) else 0.0)

    log.info("데이터 준비 완료: X=%s, 피처=%d, 타겟=%d",
             X.shape, len(feature_cols), len(target_cols))
    return X, Y.values.astype(float), feature_cols, target_cols


# ── Optuna objective ──────────────────────────────────────────────────────────

def _cv_r2(model_fn, X: np.ndarray, Y: np.ndarray, n_splits: int = 4) -> float:
    tscv = TimeSeriesSplit(n_splits=n_splits)
    scores = []
    for tr_idx, val_idx in tscv.split(X):
        m = model_fn()
        m.fit(X[tr_idx], Y[tr_idx])
        scores.append(float(r2_score(
            Y[val_idx], m.predict(X[val_idx]),
            multioutput="uniform_average",
        )))
    return float(np.mean(scores))


def make_xgb_objective(X, Y):
    import xgboost as xgb

    def objective(trial):
        params = dict(
            n_estimators     = trial.suggest_int("n_estimators", 50, 400),
            max_depth        = trial.suggest_int("max_depth", 2, 6),
            learning_rate    = trial.suggest_float("lr", 0.01, 0.20, log=True),
            subsample        = trial.suggest_float("subsample", 0.5, 1.0),
            colsample_bytree = trial.suggest_float("colsample_bytree", 0.4, 1.0),
            min_child_weight = trial.suggest_int("min_child_weight", 3, 20),
            reg_alpha        = trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            reg_lambda       = trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
            random_state=42, verbosity=0, n_jobs=2,
        )
        fn = lambda: MultiOutputRegressor(xgb.XGBRegressor(**params))
        return _cv_r2(fn, X, Y)

    return objective


def make_lgb_objective(X, Y):
    import lightgbm as lgb

    def objective(trial):
        params = dict(
            n_estimators      = trial.suggest_int("n_estimators", 50, 500),
            max_depth         = trial.suggest_int("max_depth", 2, 6),
            num_leaves        = trial.suggest_int("num_leaves", 7, 63),
            learning_rate     = trial.suggest_float("lr", 0.01, 0.20, log=True),
            subsample         = trial.suggest_float("subsample", 0.5, 1.0),
            colsample_bytree  = trial.suggest_float("colsample_bytree", 0.4, 1.0),
            min_child_samples = trial.suggest_int("min_child_samples", 5, 30),
            reg_alpha         = trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            reg_lambda        = trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
            random_state=42, verbosity=-1, n_jobs=2,
        )
        fn = lambda: MultiOutputRegressor(lgb.LGBMRegressor(**params))
        return _cv_r2(fn, X, Y)

    return objective


# ── 최종 모델 저장 ─────────────────────────────────────────────────────────────

def save_best_model(model, imputer, feature_cols, target_cols, meta: dict):
    out = {
        "model": model,
        "imputer": imputer,
        "feature_cols": feature_cols,
        "target_cols": target_cols,
        "meta": meta,
    }
    pkl_path = ART_DIR / "stage1_growth.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(out, f)
    log.info("저장: %s", pkl_path)

    meta_path = ART_DIR / "stage1_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({
            "crop_ko": CROP,
            "crop_en": "strawberry",
            "stage": 1,
            "model_type": meta["model_type"],
            "feature_count": len(feature_cols),
            "target_cols": target_cols,
            "n_train": meta["n_train"],
            "cv_r2_mean": round(meta["cv_r2_mean"], 4),
            "cv_r2_std": round(meta.get("cv_r2_std", 0), 4),
            "cv_r2_min": round(meta.get("cv_r2_min", 0), 4),
            "fold_scores": meta.get("fold_scores", []),
            "gate_passed": meta["cv_r2_mean"] >= -0.25,
            "best_params": meta.get("best_params", {}),
            "tuned_by": "optuna",
        }, f, ensure_ascii=False, indent=2)
    log.info("메타: %s", meta_path)


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=60,
                        help="Optuna 탐색 횟수 (기본 60)")
    args = parser.parse_args()

    X, Y, feature_cols, target_cols = load_stage1_data()
    n_samples = len(X)
    log.info("총 샘플: %d", n_samples)

    # ── XGB 튜닝 ──────────────────────────────────────────────────────────────
    log.info("=== XGB Optuna 탐색 (%d trials) ===", args.trials)
    xgb_study = optuna.create_study(direction="maximize",
                                    sampler=optuna.samplers.TPESampler(seed=42))
    xgb_study.optimize(make_xgb_objective(X, Y), n_trials=args.trials,
                       show_progress_bar=False)
    xgb_best_r2 = xgb_study.best_value
    xgb_best_params = xgb_study.best_params
    log.info("XGB best CV R²=%.4f  params=%s", xgb_best_r2, xgb_best_params)

    # ── LGB 튜닝 ──────────────────────────────────────────────────────────────
    log.info("=== LGB Optuna 탐색 (%d trials) ===", args.trials)
    lgb_study = optuna.create_study(direction="maximize",
                                    sampler=optuna.samplers.TPESampler(seed=42))
    lgb_study.optimize(make_lgb_objective(X, Y), n_trials=args.trials,
                       show_progress_bar=False)
    lgb_best_r2 = lgb_study.best_value
    lgb_best_params = lgb_study.best_params
    log.info("LGB best CV R²=%.4f  params=%s", lgb_best_r2, lgb_best_params)

    # ── 최우수 선택 ──────────────────────────────────────────────────────────
    if xgb_best_r2 >= lgb_best_r2:
        import xgboost as xgb
        best_type = "xgb_optuna"
        best_r2   = xgb_best_r2
        best_params = {k: v for k, v in xgb_best_params.items()}
        best_params_clean = {
            "n_estimators": best_params["n_estimators"],
            "max_depth": best_params["max_depth"],
            "learning_rate": best_params["lr"],
            "subsample": best_params["subsample"],
            "colsample_bytree": best_params["colsample_bytree"],
            "min_child_weight": best_params["min_child_weight"],
            "reg_alpha": best_params["reg_alpha"],
            "reg_lambda": best_params["reg_lambda"],
            "random_state": 42, "verbosity": 0, "n_jobs": 2,
        }
        final_model = MultiOutputRegressor(xgb.XGBRegressor(**best_params_clean))
    else:
        import lightgbm as lgb
        best_type = "lgb_optuna"
        best_r2   = lgb_best_r2
        best_params = {k: v for k, v in lgb_best_params.items()}
        best_params_clean = {
            "n_estimators": best_params["n_estimators"],
            "max_depth": best_params["max_depth"],
            "num_leaves": best_params["num_leaves"],
            "learning_rate": best_params["lr"],
            "subsample": best_params["subsample"],
            "colsample_bytree": best_params["colsample_bytree"],
            "min_child_samples": best_params["min_child_samples"],
            "reg_alpha": best_params["reg_alpha"],
            "reg_lambda": best_params["reg_lambda"],
            "random_state": 42, "verbosity": -1, "n_jobs": 2,
        }
        final_model = MultiOutputRegressor(lgb.LGBMRegressor(**best_params_clean))

    log.info("=== 최우수: %s  CV R²=%.4f ===", best_type, best_r2)
    log.info("기존 baseline R²=0.244 대비 개선: %+.4f", best_r2 - 0.244)

    # 전체 데이터로 최종 학습
    imputer = SimpleImputer(strategy="median")
    X_final = imputer.fit_transform(
        pd.DataFrame(X, columns=feature_cols)
    )
    final_model.fit(X_final, Y)

    # CV fold scores 재계산 (저장용) — 최적 파라미터로 새 인스턴스 생성
    tscv = TimeSeriesSplit(n_splits=4)
    fold_scores = []
    for tr_i, val_i in tscv.split(X_final):
        if best_type.startswith("xgb"):
            import xgboost as _xgb2
            m2 = MultiOutputRegressor(_xgb2.XGBRegressor(**best_params_clean))
        else:
            import lightgbm as _lgb2
            m2 = MultiOutputRegressor(_lgb2.LGBMRegressor(**best_params_clean))
        m2.fit(X_final[tr_i], Y[tr_i])
        fold_scores.append(float(r2_score(
            Y[val_i], m2.predict(X_final[val_i]),
            multioutput="uniform_average",
        )))

    # 저장
    imputer2 = SimpleImputer(strategy="median")
    imputer2.fit(pd.DataFrame(X, columns=feature_cols))

    save_best_model(
        model=final_model,
        imputer=imputer2,
        feature_cols=feature_cols,
        target_cols=target_cols,
        meta={
            "model_type": best_type,
            "n_train": n_samples,
            "cv_r2_mean": best_r2,
            "cv_r2_std": float(np.std(fold_scores)),
            "cv_r2_min": float(np.min(fold_scores)),
            "fold_scores": [round(s, 4) for s in fold_scores],
            "best_params": best_params,
        },
    )

    gate = "PASS" if best_r2 >= 0.45 else f"PARTIAL(목표 0.45, 달성 {best_r2:.4f})"
    log.info("=== 완료 ===  CV R²=%.4f  목표 0.45: %s", best_r2, gate)


if __name__ == "__main__":
    main()
