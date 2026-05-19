"""Airflow DAG — 스마트팜 Continuous Learning Pipeline

Tasks:
  1. fetch_new_labels   — manual_inputs 테이블에서 미처리 레코드 추출
  2. prepare_dataset    — env + growth_measurements JOIN → /tmp/training_data.parquet
  3. retrain_m1         — XGBoost + LightGBM growth model
  4. retrain_m2         — XGBoost + LightGBM yield model
  5. evaluate_models    — deployment gate (R² ≥ 0.62, MAPE ≤ 25%)
  6. deploy_or_alert    — artifacts/ 배포 또는 Slack 실패 알림
  7. mark_inputs_done   — 처리 완료 행 플래그
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "smartfarm",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def fetch_new_labels(**context):
    """Pull unprocessed manual_inputs rows and push IDs to XCom."""
    from sqlalchemy import create_engine, text
    import os

    db_url = os.environ.get("DATABASE_URL", "postgresql://smartfarm:smartfarm@db/smartfarm")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, farm_id, input_type, recorded_at, payload "
                 "FROM manual_inputs WHERE processed = FALSE")
        ).fetchall()
    ids = [r.id for r in rows]
    context["ti"].xcom_push(key="label_ids",   value=ids)
    context["ti"].xcom_push(key="label_count", value=len(ids))
    print(f"[fetch_new_labels] {len(ids)} new labels found")
    return ids


def prepare_dataset(**context):
    """Join env_measurements + growth_measurements with new labels.

    산출물: /tmp/training_data.parquet
    컬럼 구성:
        - 환경: temp_internal, humidity_int, co2_ppm, solar_rad, gdd_cumsum ...
        - 생육: plant_height, leaf_count, leaf_width, crown_diameter ...
        - yield_kg_m2: manual_inputs payload 에서 추출 (M2 타겟)
        - farm_id, time, crop
    """
    import json as _json
    import os

    import pandas as pd
    from sqlalchemy import create_engine

    label_ids = context["ti"].xcom_pull(key="label_ids", task_ids="fetch_new_labels")
    if not label_ids:
        print("[prepare_dataset] No new labels — skipping")
        return

    db_url = os.environ.get("DATABASE_URL", "postgresql://smartfarm:smartfarm@db/smartfarm")
    engine = create_engine(db_url)
    WINDOW = "90 days"

    # ── 환경 데이터 (일별 평균) ─────────────────────────────────────────────
    env_df = pd.read_sql(
        f"SELECT date_trunc('day', time) AS day, farm_id, canonical_name, "
        f"       AVG(value) AS value "
        f"FROM env_measurements "
        f"WHERE time >= NOW() - INTERVAL '{WINDOW}' "
        f"GROUP BY 1, 2, 3",
        engine,
    )
    env_wide = env_df.pivot_table(
        index=["day", "farm_id"], columns="canonical_name", values="value"
    ).reset_index().rename(columns={"day": "time"})

    # ── 생육 데이터 (일별 평균) ─────────────────────────────────────────────
    growth_df = pd.read_sql(
        f"SELECT date_trunc('day', time) AS day, farm_id, crop, canonical_name, "
        f"       AVG(value) AS value "
        f"FROM growth_measurements "
        f"WHERE time >= NOW() - INTERVAL '{WINDOW}' "
        f"GROUP BY 1, 2, 3, 4",
        engine,
    )
    if not growth_df.empty:
        growth_wide = growth_df.pivot_table(
            index=["day", "farm_id", "crop"], columns="canonical_name", values="value"
        ).reset_index().rename(columns={"day": "time"})
        combined = env_wide.merge(growth_wide, on=["time", "farm_id"], how="left")
    else:
        combined = env_wide.copy()
        combined["crop"] = None
        print("[prepare_dataset] growth_measurements 없음 — 환경 데이터만 사용")

    # ── manual_inputs 레이블 병합 ────────────────────────────────────────────
    ids_str = ",".join(str(i) for i in label_ids)
    labels_df = pd.read_sql(
        f"SELECT farm_id, recorded_at, payload FROM manual_inputs WHERE id IN ({ids_str})",
        engine,
    )

    def _extract_yield(payload):
        try:
            d = _json.loads(payload) if isinstance(payload, str) else payload
            return float(d.get("yield_kg_m2", float("nan")))
        except Exception:
            return float("nan")

    labels_df["yield_kg_m2"] = labels_df["payload"].apply(_extract_yield)
    labels_df["day"] = pd.to_datetime(labels_df["recorded_at"]).dt.normalize()

    dataset = combined.merge(
        labels_df[["farm_id", "day", "yield_kg_m2"]],
        left_on=["time", "farm_id"],
        right_on=["day", "farm_id"],
        how="left",
    ).drop(columns=["day"], errors="ignore")

    dataset.to_parquet("/tmp/training_data.parquet", index=False)
    growth_cols = [c for c in dataset.columns
                   if c in ("plant_height", "leaf_count", "leaf_width", "crown_diameter")]
    yield_valid = int(dataset["yield_kg_m2"].notna().sum()) if "yield_kg_m2" in dataset.columns else 0
    print(f"[prepare_dataset] shape={dataset.shape}, 생육컬럼={growth_cols}, yield 유효행={yield_valid}")


def retrain_m1(**context):
    """Retrain M1 growth model (XGBoost + LightGBM ensemble).

    피처: temp_internal, humidity_int, co2_ppm, solar_rad, gdd_cumsum + lag 피처
    타겟: plant_height, leaf_count, leaf_width (가용 컬럼 기준, 다중 타겟)
    배포 게이트: 평균 CV R² ≥ 0.62

    저장 포맷 (m1_growth.py 호환):
        {"models": {tgt: {"xgb": ..., "lgb": ...}},
         "meta":   {"feat_cols": [...], "targets": {tgt: {"r2_ensemble": float}},
                    "crop_ko": str, "n_samples": int}}
    """
    import os
    import pickle

    import numpy as np
    import pandas as pd

    if not os.path.exists("/tmp/training_data.parquet"):
        print("[retrain_m1] No dataset — skipping")
        return

    df = pd.read_parquet("/tmp/training_data.parquet")

    M1_FEATURES = [
        "temp_internal", "humidity_int", "co2_ppm",
        "solar_rad", "gdd_cumsum",
        "plant_height_lag7", "leaf_count_lag7",
    ]
    M1_TARGETS = ["plant_height", "leaf_count", "leaf_width"]

    available_feats = [c for c in M1_FEATURES if c in df.columns]
    available_tgts  = [c for c in M1_TARGETS  if c in df.columns]

    if len(available_feats) < 2 or not available_tgts:
        print(f"[retrain_m1] 피처/타겟 부족 — 스킵 "
              f"(feats={available_feats}, tgts={available_tgts})")
        return

    crop_ko = "딸기"
    if "crop" in df.columns and df["crop"].notna().any():
        crop_ko = str(df["crop"].mode().iloc[0])

    df_clean = df[available_feats + available_tgts].dropna()
    if len(df_clean) < 20:
        print(f"[retrain_m1] 유효 행 수 부족 ({len(df_clean)}) — 스킵")
        return

    X = df_clean[available_feats].values
    n = len(X)

    if n < 200:
        lr, depth, leaves, es = 0.15, 3, 31, 15
    elif n < 400:
        lr, depth, leaves, es = 0.10, 4, 50, 20
    else:
        lr, depth, leaves, es = 0.05, 5, 63, 30

    from sklearn.metrics import r2_score as sk_r2
    from sklearn.model_selection import TimeSeriesSplit

    n_splits = 2 if n < 100 else (3 if n < 300 else 4)
    tscv = TimeSeriesSplit(n_splits=n_splits)

    models_pkg: dict = {}
    r2_all: list = []

    for tgt in available_tgts:
        y = df_clean[tgt].values

        final_lgb, cv_r2_lgb, best_lgb_n = None, 0.0, 100
        try:
            import lightgbm as lgb

            best_iters, r2_folds = [], []
            for tr_idx, val_idx in tscv.split(X):
                fm = lgb.LGBMRegressor(
                    n_estimators=500, learning_rate=lr, max_depth=depth,
                    num_leaves=leaves, reg_alpha=0.5, reg_lambda=3.0,
                    subsample=0.8, colsample_bytree=0.8, min_child_samples=5,
                    random_state=42, verbose=-1,
                )
                fm.fit(
                    X[tr_idx], y[tr_idx],
                    eval_set=[(X[val_idx], y[val_idx])],
                    callbacks=[lgb.early_stopping(es, verbose=False),
                               lgb.log_evaluation(-1)],
                )
                best_iters.append(fm.best_iteration_)
                r2_folds.append(sk_r2(y[val_idx], fm.predict(X[val_idx])))

            best_lgb_n = max(30, int(np.median(best_iters))) if best_iters else 100
            cv_r2_lgb  = float(np.mean(r2_folds)) if r2_folds else 0.0
            final_lgb  = lgb.LGBMRegressor(
                n_estimators=best_lgb_n, learning_rate=lr, max_depth=depth,
                num_leaves=leaves, reg_alpha=0.5, reg_lambda=3.0,
                subsample=0.8, colsample_bytree=0.8, min_child_samples=5,
                random_state=42, verbose=-1,
            )
            final_lgb.fit(X, y)
            print(f"[retrain_m1] {tgt} LGB n={best_lgb_n}, CV R²={cv_r2_lgb:.3f}")
        except ImportError:
            print("[retrain_m1] LightGBM 미설치")

        final_xgb, cv_r2_xgb, best_xgb_n = None, 0.0, 100
        try:
            import xgboost as xgb_lib

            best_iters_x, r2_folds_x = [], []
            for tr_idx, val_idx in tscv.split(X):
                fm = xgb_lib.XGBRegressor(
                    n_estimators=500, early_stopping_rounds=es,
                    learning_rate=lr, max_depth=depth,
                    reg_alpha=0.5, reg_lambda=3.0,
                    subsample=0.8, colsample_bytree=0.8,
                    random_state=42, verbosity=0,
                )
                fm.fit(X[tr_idx], y[tr_idx],
                       eval_set=[(X[val_idx], y[val_idx])], verbose=False)
                best_iters_x.append(fm.best_iteration)
                r2_folds_x.append(sk_r2(y[val_idx], fm.predict(X[val_idx])))

            best_xgb_n = max(30, int(np.median(best_iters_x))) if best_iters_x else 100
            cv_r2_xgb  = float(np.mean(r2_folds_x)) if r2_folds_x else 0.0
            final_xgb  = xgb_lib.XGBRegressor(
                n_estimators=best_xgb_n, learning_rate=lr, max_depth=depth,
                reg_alpha=0.5, reg_lambda=3.0,
                subsample=0.8, colsample_bytree=0.8,
                random_state=42, verbosity=0,
            )
            final_xgb.fit(X, y)
            print(f"[retrain_m1] {tgt} XGB n={best_xgb_n}, CV R²={cv_r2_xgb:.3f}")
        except ImportError:
            print("[retrain_m1] XGBoost 미설치")

        valid_r2 = [r for r in (cv_r2_lgb, cv_r2_xgb) if r > 0.0]
        r2_ens = float(np.mean(valid_r2)) if valid_r2 else 0.0
        models_pkg[tgt] = {"xgb": final_xgb, "lgb": final_lgb, "r2_ensemble": r2_ens}
        r2_all.append(r2_ens)

    mean_r2 = round(float(np.mean(r2_all)), 4) if r2_all else 0.0

    pkg = {
        "models": {
            tgt: {"xgb": d["xgb"], "lgb": d["lgb"]}
            for tgt, d in models_pkg.items()
        },
        "meta": {
            "feat_cols": available_feats,
            "targets":   {tgt: {"r2_ensemble": d["r2_ensemble"]}
                          for tgt, d in models_pkg.items()},
            "crop_ko":   crop_ko,
            "n_samples": n,
        },
    }
    with open("/tmp/m1_candidate.pkl", "wb") as f:
        pickle.dump(pkg, f)

    context["ti"].xcom_push(key="m1_r2",   value=mean_r2)
    context["ti"].xcom_push(key="m1_crop", value=crop_ko)
    print(f"[retrain_m1] 완료 — 평균 R²={mean_r2:.3f} "
          f"(작목={crop_ko}, 타겟={available_tgts}, 피처={len(available_feats)}개)")


def retrain_m2(**context):
    """Retrain M2 yield forecast model (LightGBM + XGBoost ensemble).

    피처: plant_height, leaf_count, leaf_width + temp_internal, solar_rad, ec_dsm
          + lag_7d_yield, lag_14d_yield, gdd_cumsum
    타겟: yield_kg_m2  (log1p 변환)
    배포 게이트: MAPE ≤ 25%
    """
    import os
    import pickle

    import numpy as np
    import pandas as pd

    if not os.path.exists("/tmp/training_data.parquet"):
        print("[retrain_m2] No dataset — skipping")
        return

    df = pd.read_parquet("/tmp/training_data.parquet")
    target_col = "yield_kg_m2"

    if target_col not in df.columns:
        print("[retrain_m2] yield_kg_m2 컬럼 없음 — skipping")
        return

    M2_FEATURES = [
        "plant_height", "leaf_count", "leaf_width",
        "temp_internal", "solar_rad", "ec_dsm",
        "lag_7d_yield", "lag_14d_yield",
        "gdd_cumsum",
    ]
    available = [c for c in M2_FEATURES if c in df.columns]

    if "lag_7d_yield" not in df.columns:
        df = df.sort_values("farm_id") if "farm_id" in df.columns else df
        df["lag_7d_yield"]  = df[target_col].shift(7).fillna(df[target_col].mean())
        df["lag_14d_yield"] = df[target_col].shift(14).fillna(df[target_col].mean())
        for lc in ("lag_7d_yield", "lag_14d_yield"):
            if lc not in available:
                available.append(lc)

    if len(available) < 2:
        print(f"[retrain_m2] 피처 부족 ({available}) — 스킵")
        return

    df_clean = df[available + [target_col]].dropna()
    if len(df_clean) < 20:
        print(f"[retrain_m2] 유효 행 수 부족 ({len(df_clean)}) — 스킵")
        return

    X     = df_clean[available].values
    y     = df_clean[target_col].values
    y_log = np.log1p(y)
    n     = len(X)

    if n < 200:
        lr, depth, leaves, es = 0.15, 4, 31, 15
    elif n < 400:
        lr, depth, leaves, es = 0.10, 5, 50, 20
    else:
        lr, depth, leaves, es = 0.05, 6, 63, 30

    from sklearn.metrics import mean_absolute_percentage_error
    from sklearn.model_selection import TimeSeriesSplit

    n_splits = 2 if n < 100 else (3 if n < 300 else 4)
    tscv = TimeSeriesSplit(n_splits=n_splits)

    final_lgb, cv_mape_lgb, best_lgb_n = None, 999.0, 0
    try:
        import lightgbm as lgb

        best_iters: list = []
        mape_folds: list = []
        for tr_idx, val_idx in tscv.split(X):
            fm = lgb.LGBMRegressor(
                n_estimators=500, learning_rate=lr, max_depth=depth,
                num_leaves=leaves, reg_alpha=1.0, reg_lambda=5.0,
                subsample=0.8, colsample_bytree=0.8, min_child_samples=5,
                random_state=42, verbose=-1,
            )
            fm.fit(
                X[tr_idx], y_log[tr_idx],
                eval_set=[(X[val_idx], y_log[val_idx])],
                callbacks=[lgb.early_stopping(es, verbose=False),
                           lgb.log_evaluation(-1)],
            )
            best_iters.append(fm.best_iteration_)
            pred   = np.expm1(fm.predict(X[val_idx]))
            actual = np.expm1(y_log[val_idx])
            mask   = actual > 0.01
            if mask.sum() > 0:
                mape_folds.append(
                    float(mean_absolute_percentage_error(actual[mask], pred[mask])) * 100
                )

        best_lgb_n  = max(30, int(np.median(best_iters))) if best_iters else 100
        cv_mape_lgb = float(np.mean(mape_folds)) if mape_folds else 999.0
        final_lgb   = lgb.LGBMRegressor(
            n_estimators=best_lgb_n, learning_rate=lr, max_depth=depth,
            num_leaves=leaves, reg_alpha=1.0, reg_lambda=5.0,
            subsample=0.8, colsample_bytree=0.8, min_child_samples=5,
            random_state=42, verbose=-1,
        )
        final_lgb.fit(X, y_log)
        print(f"[retrain_m2] LGB n={best_lgb_n}, CV MAPE={cv_mape_lgb:.1f}%")
    except ImportError:
        print("[retrain_m2] LightGBM 미설치")

    final_xgb, cv_mape_xgb, best_xgb_n = None, 999.0, 0
    try:
        import xgboost as xgb

        best_iters_x: list = []
        mape_folds_x: list = []
        for tr_idx, val_idx in tscv.split(X):
            fm = xgb.XGBRegressor(
                n_estimators=500, early_stopping_rounds=es,
                learning_rate=lr, max_depth=depth,
                reg_alpha=1.0, reg_lambda=5.0,
                subsample=0.8, colsample_bytree=0.8,
                random_state=42, verbosity=0,
            )
            fm.fit(X[tr_idx], y_log[tr_idx],
                   eval_set=[(X[val_idx], y_log[val_idx])], verbose=False)
            best_iters_x.append(fm.best_iteration)
            pred   = np.expm1(fm.predict(X[val_idx]))
            actual = np.expm1(y_log[val_idx])
            mask   = actual > 0.01
            if mask.sum() > 0:
                mape_folds_x.append(
                    float(mean_absolute_percentage_error(actual[mask], pred[mask])) * 100
                )

        best_xgb_n  = max(30, int(np.median(best_iters_x))) if best_iters_x else 100
        cv_mape_xgb = float(np.mean(mape_folds_x)) if mape_folds_x else 999.0
        final_xgb   = xgb.XGBRegressor(
            n_estimators=best_xgb_n, learning_rate=lr, max_depth=depth,
            reg_alpha=1.0, reg_lambda=5.0,
            subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbosity=0,
        )
        final_xgb.fit(X, y_log)
        print(f"[retrain_m2] XGB n={best_xgb_n}, CV MAPE={cv_mape_xgb:.1f}%")
    except ImportError:
        print("[retrain_m2] XGBoost 미설치")

    valid = [m for m in (cv_mape_lgb, cv_mape_xgb) if m < 999.0]
    if not valid:
        print("[retrain_m2] 모든 모델 학습 실패 — 스킵")
        return
    ensemble_mape = round(float(np.mean(valid)), 2)

    with open("/tmp/m2_candidate.pkl", "wb") as f:
        pickle.dump({
            "lgb": final_lgb, "xgb": final_xgb,
            "features": available, "log_transform": True,
            "lgb_n": best_lgb_n, "xgb_n": best_xgb_n,
            "cv_mape": ensemble_mape, "n_samples": n,
        }, f)

    context["ti"].xcom_push(key="m2_mape", value=ensemble_mape)
    print(f"[retrain_m2] 완료 — LGB {cv_mape_lgb:.1f}% / XGB {cv_mape_xgb:.1f}% "
          f"→ 앙상블 MAPE={ensemble_mape:.1f}% (n={n}, 피처={len(available)}개)")


def evaluate_models(**context):
    """Check deployment gates. Push pass/fail result to XCom."""
    m1_r2   = context["ti"].xcom_pull(key="m1_r2",   task_ids="retrain_m1") or 0.0
    m2_mape = context["ti"].xcom_pull(key="m2_mape", task_ids="retrain_m2") or 999.0

    m1_pass  = m1_r2   >= 0.62
    m2_pass  = m2_mape <= 25.0
    all_pass = m1_pass and m2_pass

    context["ti"].xcom_push(key="gate_passed", value=all_pass)
    context["ti"].xcom_push(key="gate_details", value={
        "M1": {"r2":   m1_r2,   "threshold": 0.62,  "passed": m1_pass},
        "M2": {"mape": m2_mape, "threshold": 25.0,  "passed": m2_pass},
    })
    print(f"[evaluate_models] M1 R²={m1_r2:.3f} pass={m1_pass}, "
          f"M2 MAPE={m2_mape:.1f}% pass={m2_pass}")


def deploy_or_alert(**context):
    """Gate PASSED → candidate pkl을 artifacts/ 배포 (prev/ 백업).
    Gate FAILED → Slack 또는 콘솔 알림.
    """
    import json
    import os
    import pickle
    import shutil

    gate_passed  = context["ti"].xcom_pull(key="gate_passed",  task_ids="evaluate_models")
    gate_details = context["ti"].xcom_pull(key="gate_details", task_ids="evaluate_models") or {}

    if not gate_passed:
        print(f"[deploy_or_alert] 게이트 실패 — 알림. 세부: {gate_details}")
        slack_url = os.environ.get("SLACK_WEBHOOK_URL", "")
        if slack_url:
            try:
                import urllib.request
                msg = {"text": (
                    "⚠️ *SmartFarm ML 배포 게이트 실패*\n"
                    f"```{json.dumps(gate_details, ensure_ascii=False, indent=2)}```"
                )}
                req = urllib.request.Request(
                    slack_url,
                    data=json.dumps(msg).encode(),
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=5)
                print("[deploy_or_alert] Slack 알림 전송 완료")
            except Exception as e:
                print(f"[deploy_or_alert] Slack 알림 실패: {e}")
        return

    ARTS = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "models", "artifacts")
    )
    CROP_MAP = {
        "딸기": "strawberry", "방울토마토": "cherry_tomato",
        "완숙토마토": "tomato",  "참외": "melon",
        "오이": "cucumber",    "파프리카": "paprika",
    }

    def _backup_and_copy(src: str, dst: str) -> None:
        if os.path.exists(dst):
            prev_dir = os.path.join(os.path.dirname(dst), "prev")
            os.makedirs(prev_dir, exist_ok=True)
            v = 1
            while os.path.exists(os.path.join(prev_dir, str(v))):
                v += 1
            bak = os.path.join(prev_dir, str(v))
            os.makedirs(bak, exist_ok=True)
            shutil.copy2(dst, os.path.join(bak, os.path.basename(dst)))
            print(f"[deploy_or_alert] 백업: {os.path.basename(dst)} → prev/{v}/")
        shutil.copy2(src, dst)

    # M1 배포
    if os.path.exists("/tmp/m1_candidate.pkl"):
        with open("/tmp/m1_candidate.pkl", "rb") as f:
            m1_pkg = pickle.load(f)
        crop_ko = m1_pkg.get("meta", {}).get("crop_ko", "딸기")
        crop_en = CROP_MAP.get(crop_ko, "strawberry")
        art_dir = os.path.join(ARTS, crop_en)
        os.makedirs(art_dir, exist_ok=True)

        dst_pkl  = os.path.join(art_dir, "m1_growth_model.pkl")
        dst_meta = os.path.join(art_dir, "m1_meta.json")
        _backup_and_copy("/tmp/m1_candidate.pkl", dst_pkl)
        meta = dict(m1_pkg.get("meta", {}))
        meta["deployed_by"] = "continuous_learning_dag"
        with open(dst_meta, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"[deploy_or_alert] M1 배포 완료 → {dst_pkl}")
    else:
        print("[deploy_or_alert] m1_candidate 없음 — M1 스킵")

    # M2 배포
    if os.path.exists("/tmp/m2_candidate.pkl"):
        m1_crop = context["ti"].xcom_pull(key="m1_crop", task_ids="retrain_m1") or "딸기"
        crop_en = CROP_MAP.get(m1_crop, "strawberry")
        art_dir = os.path.join(ARTS, crop_en)
        os.makedirs(art_dir, exist_ok=True)

        dst_m2 = os.path.join(art_dir, "m2_yield_model.pkl")
        _backup_and_copy("/tmp/m2_candidate.pkl", dst_m2)

        with open("/tmp/m2_candidate.pkl", "rb") as f:
            m2_pkg = pickle.load(f)
        m2_meta = {
            "crop_ko":       m1_crop,
            "features":      m2_pkg.get("features", []),
            "cv_mape":       m2_pkg.get("cv_mape"),
            "n_samples":     m2_pkg.get("n_samples"),
            "lgb_n":         m2_pkg.get("lgb_n"),
            "xgb_n":         m2_pkg.get("xgb_n"),
            "log_transform": m2_pkg.get("log_transform", True),
            "deployed_by":   "continuous_learning_dag",
        }
        with open(os.path.join(art_dir, "m2_meta.json"), "w", encoding="utf-8") as f:
            json.dump(m2_meta, f, ensure_ascii=False, indent=2)
        print(f"[deploy_or_alert] M2 배포 완료 → {dst_m2}")
    else:
        print("[deploy_or_alert] m2_candidate 없음 — M2 스킵")

    print(f"[deploy_or_alert] 완료. 결과: {gate_details}")


def mark_inputs_done(**context):
    """Mark processed manual_inputs rows so they are not re-used next run."""
    from sqlalchemy import create_engine, text
    import os

    label_ids = context["ti"].xcom_pull(key="label_ids", task_ids="fetch_new_labels") or []
    if not label_ids:
        return

    engine = create_engine(
        os.environ.get("DATABASE_URL", "postgresql://smartfarm:smartfarm@db/smartfarm")
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE manual_inputs SET processed = TRUE "
                f"WHERE id IN ({','.join(str(i) for i in label_ids)})"
            )
        )
    print(f"[mark_inputs_done] {len(label_ids)}행 처리 완료 표시")


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

with DAG(
    dag_id="smartfarm_continuous_learning",
    default_args=default_args,
    description="Daily retraining loop for M1/M2 models",
    schedule_interval="0 17 * * *",   # 02:00 KST = 17:00 UTC
    start_date=datetime(2026, 5, 1),
    catchup=False,
    tags=["smartfarm", "ml"],
) as dag:

    t_fetch  = PythonOperator(task_id="fetch_new_labels",  python_callable=fetch_new_labels)
    t_prep   = PythonOperator(task_id="prepare_dataset",   python_callable=prepare_dataset)
    t_m1     = PythonOperator(task_id="retrain_m1",        python_callable=retrain_m1)
    t_m2     = PythonOperator(task_id="retrain_m2",        python_callable=retrain_m2)
    t_eval   = PythonOperator(task_id="evaluate_models",   python_callable=evaluate_models)
    t_deploy = PythonOperator(task_id="deploy_or_alert",   python_callable=deploy_or_alert)
    t_mark   = PythonOperator(task_id="mark_inputs_done",  python_callable=mark_inputs_done)

    t_fetch >> t_prep >> [t_m1, t_m2] >> t_eval >> t_deploy >> t_mark
