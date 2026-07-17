"""환경 반응 모델 — 환경 설정 → 수확량. 최적화(의사결정)용.

★ 이름에 대하여 — **인과 모델이 아니다**:
  lag 변수를 빼도 인과 식별이 되지 않는다. 관측 데이터라 교란이 남는다 —
  잘하는 농가가 온도도 잘 맞추고 수확도 많다면, 모델은 그 '농가 실력'을 온도 효과로
  돌린다. 무작위 배정 실험이 없으면 ∂수확량/∂온도 를 인과로 주장할 수 없다.
  그래서 '환경 반응(response) 모델'이라 부른다. 최적화에 쓰되 근거를 과장하지 않는다.

★ 왜 별도 모델인가 (기존 stage2 를 못 쓰는 이유):
  stage2 는 예측 정확도가 목적이라 yield_lag1·yield_ewm3·farm_yield_hist_mean 이
  지배한다(중요도 0.3/0.1/0.1 vs temp_internal 0.1 · humidity_int **0.0**).
  실측: 20℃와 28℃ 예측이 소수점 7자리까지 동일 — ∂수확량/∂온도 ≈ 0 이라
  환경 최적화가 성립하지 않는다. CO₂ 는 아예 변수에 없다(데이터엔 '잔존CO2' 로 존재).
  → "작년에 잘한 농가가 올해도 잘한다"를 학습한 모델이다. 예측엔 유용하나
    "온도를 올리면 어떻게 되나"에는 답하지 못한다.

★ 설계 원칙:
  1) lag·농가이력 제외 — 이들이 환경 효과를 흡수한다.
  2) **생육(growth) 도 제외** — 생육은 환경의 *매개(mediator)* 다. 모델에 넣으면
     온도의 효과가 생육을 통해 흘러 '직접효과'만 남고 총효과가 차단된다.
     의사결정에 필요한 건 환경→수확량의 **총효과**다.
  3) 농가 고정효과는 빼되(farm_id 미사용), 교란은 남는다는 걸 문서화한다.
  4) 정확도(R²)는 stage2 보다 낮게 나온다 — 당연하다. 목적이 다르다.
     쓸 수 있는지는 R² 가 아니라 **환경 반응이 유의한가**로 판단한다.

사용:
  PYTHONPATH=C:/smart_farm python scripts/train_env_response.py --crop 딸기
  PYTHONPATH=C:/smart_farm python scripts/train_env_response.py            # 전 작목
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

CROPS = ["딸기", "오이", "파프리카", "완숙토마토", "방울토마토", "참외"]
OUT_DIR = ROOT / "models" / "artifacts"
REPORT = ROOT / "out" / "_env_response.json"

# 의사결정 변수 — 농가가 실제로 조절할 수 있는 것
_CONTROL = ["temp_internal", "humidity_int", "co2_ppm"]
# 통제 불가하지만 수확량에 영향 → 함께 넣어야 편향이 준다
_EXOG = ["temp_external", "solar_rad"]
# 환경의 생리학적 변환 — 월평균보다 신호가 강하다. 온도·습도의 '함수'이므로
# 제어변수를 바꾸면 이들도 함께 움직여야 정합하나, 여기서는 데이터에 기록된 값을 쓴다.
#   ★ 그래서 PDP 로 온도만 흔들면 gdd_monthly 가 고정돼 온도 효과가 과소평가된다.
#     (한계로 명시 — 제대로 하려면 온도→GDD 재계산을 PDP 안에서 해야 한다.)
_DERIVED = ["gdd_monthly", "m2_vpd_stress", "m2_phenology"]
# ★ 제외: yield_lag*·*_hist_*·growth_* (위 설계 원칙 1·2 참조)


def _feature_cols(df) -> list[str]:
    """환경 + 생리 파생 + 계절. lag·이력·생육은 뺀다."""
    cols = []
    for c in _CONTROL + _EXOG + _DERIVED:
        if c in df.columns and df[c].notna().sum() >= 20:
            cols.append(c)
    for c in ("month_sin", "month_cos"):
        if c in df.columns:
            cols.append(c)
    return cols


def _load_matrix(crop_ko: str):
    """stage2 의 로더를 재사용한다 — 수기 재구현하면 조용히 어긋난다."""
    from scripts.train_stage2_yield import (
        AREA_DEFAULTS, build_stage2_matrix, load_area_map, load_cultiv_meta,
        load_env_monthly, load_growth_monthly, load_production_monthly,
    )
    from models.crop_config import CROP_CONFIGS

    cfg = CROP_CONFIGS[crop_ko]
    env = load_env_monthly(crop_ko)
    growth = load_growth_monthly(crop_ko, cfg.growth_cols)
    area_map = load_area_map(crop_ko)
    # default_area 는 학습 스크립트와 동일한 출처를 쓴다(2213행) — 값이 갈리면 yield 가 어긋난다
    prod = load_production_monthly(crop_ko, area_map, AREA_DEFAULTS.get(crop_ko, 1200.0))
    try:
        cultiv = load_cultiv_meta(crop_ko)
    except Exception:
        cultiv = None
    return build_stage2_matrix(env, growth, prod, cfg, cultiv), cfg


def _cv_eval(X, y, groups):
    """연도 단위 교차검증(LOYO) — 같은 해 데이터로 자기 자신을 맞히지 않게."""
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.metrics import r2_score

    years = np.unique(groups)
    if len(years) < 3:
        return None, None, None
    r2s, models = [], []
    for ty in years:
        tr, va = groups != ty, groups == ty
        if tr.sum() < 20 or va.sum() < 3:
            continue
        m = GradientBoostingRegressor(n_estimators=200, max_depth=3,
                                      learning_rate=0.05, subsample=0.8,
                                      random_state=42)
        m.fit(X[tr], y[tr])
        r2s.append(float(r2_score(y[va], m.predict(X[va]))))
        models.append(m)
    if not r2s:
        return None, None, None
    final = GradientBoostingRegressor(n_estimators=200, max_depth=3,
                                      learning_rate=0.05, subsample=0.8,
                                      random_state=42).fit(X, y)
    return float(np.mean(r2s)), float(np.std(r2s)), final


def _response(model, X, cols, col, lo, hi, n=9) -> list[dict]:
    """부분의존(PDP) — 해당 변수만 바꿨을 때 예측 수확량의 변화.

    ★ 이 곡선이 평평하면 그 변수로는 최적화를 할 수 없다(stage2 가 그랬다).
    """
    if col not in cols:
        return []
    i = cols.index(col)
    grid = np.linspace(lo, hi, n)
    out = []
    for g in grid:
        Xi = X.copy()
        Xi[:, i] = g
        out.append({"x": round(float(g), 1),
                    "yield": round(float(np.mean(model.predict(Xi))), 4)})
    return out


def train(crop_ko: str) -> dict | None:
    df, cfg = _load_matrix(crop_ko)
    if df is None or df.empty or "yield_per_m2" not in df.columns:
        logger.warning("  %s: 행렬 없음", crop_ko)
        return None

    d = df[df["yield_per_m2"] > 0].copy()
    cols = _feature_cols(d)
    ctrl = [c for c in _CONTROL if c in cols]
    if not ctrl or len(d) < 40:
        logger.warning("  %s: 표본(%d) 또는 제어변수(%s) 부족", crop_ko, len(d), ctrl)
        return None

    d = d.dropna(subset=cols + ["yield_per_m2", "year"])
    if len(d) < 40:
        logger.warning("  %s: 결측 제거 후 표본 부족(%d)", crop_ko, len(d))
        return None

    X = d[cols].to_numpy(float)
    y = d["yield_per_m2"].to_numpy(float)
    groups = d["year"].to_numpy()

    cv_r2, cv_std, model = _cv_eval(X, y, groups)
    if model is None:
        logger.warning("  %s: CV 폴드 구성 실패(연도 부족)", crop_ko)
        return None

    imp = dict(zip(cols, (round(float(v), 3) for v in model.feature_importances_)))
    resp = {
        "temp_internal": _response(model, X, cols, "temp_internal",
                                   *cfg.opt_temp_range),
        "humidity_int": _response(model, X, cols, "humidity_int",
                                  *cfg.opt_humid_range),
        "co2_ppm": _response(model, X, cols, "co2_ppm", *cfg.opt_co2_range),
    }
    # 반응 폭 — 평평하면 최적화 불가. 판단 근거로 남긴다.
    span = {}
    for k, v in resp.items():
        if v:
            ys = [p["yield"] for p in v]
            base = np.mean(y)
            span[k] = round((max(ys) - min(ys)) / base * 100, 1) if base else None

    return {
        "crop": crop_ko, "n": int(len(d)), "features": cols,
        "cv_r2": (round(cv_r2, 3) if cv_r2 is not None else None),
        "cv_r2_std": (round(cv_std, 3) if cv_std is not None else None),
        "importance": imp,
        "response": resp,
        "response_span_pct": span,
        "model": model,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop", default=None)
    ap.add_argument("--write", action="store_true", help="아티팩트 저장")
    a = ap.parse_args()

    rows = []
    for c in ([a.crop] if a.crop else CROPS):
        try:
            r = train(c)
        except Exception as e:
            logger.warning("  %s 실패: %s: %s", c, type(e).__name__, str(e)[:100])
            r = None
        if r:
            rows.append(r)

    if not rows:
        print("학습 가능한 작목 없음")
        return 1

    print("\n환경 반응 모델 — 환경만으로 수확량 설명 (lag·생육 제외)\n")
    print(f"{'작목':<7}{'n':>6}{'CV R²':>9}{'±':>7}   반응폭(%: 환경만 바꿨을 때 수확량 변동)")
    for r in rows:
        s = r["response_span_pct"]
        print(f"{r['crop']:<7}{r['n']:>6}{str(r['cv_r2']):>9}{str(r['cv_r2_std']):>7}   "
              f"온도 {s.get('temp_internal','—')!s:>6} · 습도 {s.get('humidity_int','—')!s:>6} · "
              f"CO₂ {s.get('co2_ppm','—')!s:>6}")
    print("\n※ CV R² 는 stage2 보다 낮은 게 정상이다 — 목적이 예측이 아니라 '환경 반응'이다.")
    print("※ 반응폭이 0 에 가까우면 그 변수로는 최적화할 수 없다.")
    print("★ 인과가 아니다 — 관측 데이터라 교란(농가 실력 등)이 남는다.")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(
        [{k: v for k, v in r.items() if k != "model"} for r in rows],
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {REPORT}")

    if a.write:
        import pickle
        for r in rows:
            from models.m2_yield import CROP_MAP
            en = CROP_MAP.get(r["crop"], r["crop"])
            p = OUT_DIR / en / "env_response.pkl"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(pickle.dumps({
                "model": r["model"], "feature_cols": r["features"],
                "cv_r2": r["cv_r2"], "n_train": r["n"],
                "note": "환경 반응 모델(최적화용) — 인과 아님. 예측은 stage2 를 쓸 것.",
            }))
            print(f"  저장: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
