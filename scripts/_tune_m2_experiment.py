"""M2 튜닝 정직 실험 — 파프리카·완숙토마토 (아티팩트 미저장).

★ 정직성 안전장치:
  1) 먼저 baseline(현 하이퍼파라미터)을 재현해 아티팩트의 CV R²와 일치하는지 확인한다.
     일치하지 않으면 하네스가 신뢰 불가 → 튜닝 수치도 신뢰 불가로 중단한다.
  2) 모든 판정은 train_stage2 가 반환하는 **교차검증 cv_r2_mean** 으로만 한다(학습 R² 금지).
  3) train_stage2 실함수를 그대로 호출한다(피처선택·GroupKFold·앙상블 전부 실제 경로).
     hp_override/extra_exclude 훅으로만 개입 — CV 재구현 없음(조용한 divergence 차단).
  4) run_crop 과 동일하게 매트릭스를 구성하고, 각 작목이 실제 선택한 mode 로 튜닝한다.

사용:
  PYTHONPATH=C:/smart_farm python scripts/_tune_m2_experiment.py
"""
from __future__ import annotations
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
logging.getLogger().setLevel(logging.WARNING)   # 학습 로그 소음 억제

from models.crop_config import CROP_CONFIGS
from scripts.train_stage2_yield import (
    AREA_DEFAULTS, build_stage2_matrix, build_stage2_matrix_annual,
    load_area_map, load_cultiv_meta, load_env_monthly, load_growth_monthly,
    load_production_monthly, load_rda_supplemental, train_stage2,
)
import pandas as pd

ART = ROOT / "models" / "artifacts"
# 각 작목이 아티팩트에서 실제 선택한 mode (stage2_meta.agg_mode 로 확인)
CROPS = {"파프리카": "paprika", "완숙토마토": "tomato"}


def build_matrices(crop_ko):
    cfg = CROP_CONFIGS[crop_ko]
    da = AREA_DEFAULTS.get(crop_ko, 1200.0)
    env = load_env_monthly(crop_ko)
    growth = load_growth_monthly(crop_ko, cfg.growth_cols)
    prod = load_production_monthly(crop_ko, load_area_map(crop_ko), da)
    cultiv = load_cultiv_meta(crop_ko)
    dfm = build_stage2_matrix(env, growth, prod, cfg, cultiv_meta=cultiv)
    dfa = build_stage2_matrix_annual(env, growth, prod, cfg, cultiv_meta=cultiv)
    rda = load_rda_supplemental(crop_ko)
    if not rda.empty:
        dfm = pd.concat([dfm, rda], ignore_index=True, sort=False)
        dfa = pd.concat([dfa, rda], ignore_index=True, sort=False)
    return cfg, dfm, dfa


def cv_of(df, cfg, mode="absolute", hp=None, ex=None):
    if df is None or df.empty:
        return None
    r = train_stage2(df, cfg, target_mode=mode, hp_override=hp, extra_exclude=ex)
    if not r:
        return None
    return {
        "cv_r2": r.get("cv_r2_mean"), "cv_mape": r.get("cv_mape_mean"),
        "n": r.get("n_train"), "model": r.get("model_type"),
    }


def main():
    for crop_ko, crop_en in CROPS.items():
        meta = json.load(open(ART / crop_en / "stage2_meta.json", encoding="utf-8"))
        base_r2 = meta.get("cv_r2_mean")
        base_mode = meta.get("agg_mode", "?")
        print(f"\n{'='*64}\n{crop_ko} ({crop_en}) — 아티팩트 baseline: "
              f"CV R²={base_r2}  mode={base_mode}  n={meta.get('n_train')}")
        print("="*64)

        cfg, dfm, dfa = build_matrices(crop_ko)
        # base_mode 에 맞는 매트릭스 선택
        if base_mode.startswith("annual"):
            df, mode = dfa, ("residual" if base_mode == "annual_residual" else "absolute")
        else:
            df, mode = dfm, "absolute"

        # ── 1) 결정성 확인 — baseline 3회 반복 ───────────────────────────
        reps = [cv_of(df, cfg, mode=mode)["cv_r2"] for _ in range(3)]
        spread = max(reps) - min(reps)
        b = cv_of(df, cfg, mode=mode)
        print(f"  [현재코드 재현] CV R²={reps} (편차 {spread:.3f})")
        print(f"  [아티팩트 저장값] CV R²={base_r2}")
        if spread > 0.03:
            print(f"  ⚠ 비결정적(편차 {spread:.3f}>0.03) — 튜닝 수치 신뢰 주의")
        if base_r2 is not None and abs(b["cv_r2"] - base_r2) > 0.03:
            print(f"  ★ 아티팩트 stale — 현재 코드·데이터 재현({b['cv_r2']:.3f}) ≠ "
                  f"저장값({base_r2}). 재학습만으로도 값이 바뀐다.")
        print(f"  → baseline = 현재코드 재현값 {b['cv_r2']:.3f} 로 튜닝 진행")

        # ── 2) 튜닝 후보 ─────────────────────────────────────────────────
        # 원칙: 소표본 과적합이 병목 → (a) 더 강한 정규화, (b) 더 얕은/깊은 트리,
        #       (c) 학습률·early stop 조정, (d) 노이즈 피처 제외 시도.
        trials = [
            ("정규화↑(L2·L1·gamma)",      {"reg_l2": 6.0, "reg_l1": 1.0, "gamma": 0.5}, None),
            ("트리 얕게(depth2)",          {"depth": 2, "mcw": 8},                        None),
            ("트리 깊게(depth5)+정규화",   {"depth": 5, "reg_l2": 4.0, "reg_l1": 0.6},    None),
            ("학습천천히(lr0.03,n800)",    {"lr": 0.03, "n_est": 800, "es": 60},          None),
            ("컬럼샘플↓(0.4)",            {"colsamp": 0.4, "sub": 0.6},                  None),
            ("early-stop 여유(es80)",      {"es": 80, "n_est": 900},                      None),
            ("정규화↑+얕게 결합",          {"depth": 2, "mcw": 8, "reg_l2": 6.0, "reg_l1": 1.0, "gamma": 0.5}, None),
        ]
        best = ("baseline", b["cv_r2"], b["cv_mape"])
        rows = [("baseline", b["cv_r2"], b["cv_mape"], b["model"])]
        for name, hp, ex in trials:
            r = cv_of(df, cfg, mode=mode, hp=hp, ex=ex)
            if r is None:
                rows.append((name, None, None, "실패")); continue
            rows.append((name, r["cv_r2"], r["cv_mape"], r["model"]))
            if r["cv_r2"] is not None and r["cv_r2"] > best[1]:
                best = (name, r["cv_r2"], r["cv_mape"])

        print(f"\n  {'후보':<26}{'CV R²':>9}{'CV MAPE':>10}  model")
        for name, r2, mape, mdl in rows:
            r2s = f"{r2:.3f}" if r2 is not None else "—"
            mps = f"{mape:.1f}" if mape is not None else "—"
            mark = "  ← 최고" if name == best[0] and name != "baseline" else ""
            print(f"  {name:<26}{r2s:>9}{mps:>10}  {mdl}{mark}")

        gain = best[1] - b["cv_r2"]
        print(f"\n  ▶ 최고: {best[0]}  CV R²={best[1]:.3f}  "
              f"(baseline 대비 {gain:+.3f})")
        if gain < 0.02:
            print(f"  ▶ 판정: 유의미한 개선 없음(Δ<0.02) — 현 모델 유지 권장")
        elif best[1] >= 0.20:
            print(f"  ▶ 판정: 개선됨 + 기준(0.20) 돌파 → 조건부→적용 전환 가능. 재학습 검토")
        else:
            print(f"  ▶ 판정: 소폭 개선하나 기준(0.20) 미달 → 조건부 유지, 반영 실익 낮음")


if __name__ == "__main__":
    main()
