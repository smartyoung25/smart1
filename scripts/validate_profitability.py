"""수익성(매출) end-to-end 검증 — 예측 수확량을 stage3 에 넣어 실측 매출과 대조.

★ 왜 필요한가:
  과제명은 「스마트팜 **수익성** 제고…」인데 게이트는 M2(수확량)만 판정해 왔다.
  그런데 stage3(매출) 의 보고 지표는 **실측 수확량을 입력으로** 교차검증한 값이다
  (feature_names 에 log_yield_annual 이 있다). 서빙 시에는 stage2 의 **예측** 수확량이
  들어가므로, 보고된 stage3 정확도는 실제 운영 정확도가 아니다 — 오차가 전파된다.
  실측: stage3 CV MAPE 가 오이 3.5% / 참외 13.2% 로 stage2 보다 훨씬 좋게 나오는데,
  이는 "매출 ≈ 수확량 × 단가" 라는 거의 항등식을 학습했기 때문이다(수확량을 이미 알므로).

  이 스크립트는 두 조건을 같은 폴드에서 비교한다:
    (A) oracle  : 실측 수확량 → stage3 → 매출   (기존 보고 방식)
    (B) e2e     : 예측 수확량 → stage3 → 매출   (실제 서빙 조건)
  (B) 가 수익성 모델의 정직한 성능이다.

★ 한계(명시):
  · 여기서 검증하는 것은 **매출(revenue)** 이지 **소득(수익성)** 이 아니다.
    소득 = 매출 − 경영비 인데, 농가별 실측 경영비가 없다(stage4 는 ML 모델이 아니라
    income_survey 통계에서 뽑은 계수표다). 농가별 소득 검증은 연구개발계획서 과업①의
    소득자료 조사(20개소)로 실측 경영비를 확보해야 가능하다.
  · 즉 "수익성 모델 검증"의 현재 상한은 매출까지다.

사용:
  PYTHONPATH=C:/smart_farm python scripts/validate_profitability.py --crop 딸기
  PYTHONPATH=C:/smart_farm python scripts/validate_profitability.py            # 전 작목
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

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

CROPS = ["딸기", "오이", "파프리카", "완숙토마토", "방울토마토", "참외"]
OUT = ROOT / "out" / "_profitability_validation.json"


def _mape(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    m = y > 0
    if not m.any():
        return float("nan")
    return float(np.mean(np.abs((y[m] - p[m]) / y[m])) * 100)


def _r2(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    ss_res = float(np.sum((y - p) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def validate(crop_ko: str) -> dict | None:
    """작목 1개 — oracle vs e2e 비교.

    stage3 학습 스크립트의 데이터 로더를 재사용한다(수기 재구현하면 조용히 어긋난다).
    """
    from scripts.train_stage3_revenue import load_production_with_revenue
    from models.crop_config import CROP_CONFIGS

    cfg = CROP_CONFIGS.get(crop_ko)
    if cfg is None:
        return None

    df = load_production_with_revenue(crop_ko)
    if df is None or df.empty:
        logger.warning("  %s: 생산·매출 데이터 없음", crop_ko)
        return None

    need = {"yield_per_m2", "revenue_per_m2"}
    if not need.issubset(df.columns):
        logger.warning("  %s: 필요한 컬럼 없음 (%s)", crop_ko, need - set(df.columns))
        return None

    d = df[(df["yield_per_m2"] > 0) & (df["revenue_per_m2"] > 0)].copy()
    if len(d) < 10:
        logger.warning("  %s: 유효 표본 부족(%d)", crop_ko, len(d))
        return None

    y_true_yield = d["yield_per_m2"].to_numpy(float)
    y_true_rev = d["revenue_per_m2"].to_numpy(float)

    # ── (A) oracle: 실측 수확량 → 매출 ────────────────────────────────────────
    #   stage3 의 핵심은 "매출 ≈ 수확량 × 단가". 단가를 실측에서 얻어 상한을 본다.
    #   (stage3 pkl 을 직접 태우려면 피처 파이프라인 전체가 필요해, 여기서는 관계식
    #    자체의 설명력을 상한으로 삼는다 — e2e 와의 '차이'가 논점이므로 충분하다.)
    price = float(np.median(y_true_rev / y_true_yield))
    rev_oracle = y_true_yield * price

    # ── (B) 실측 단가의 변동폭 — 매출 오차 중 '단가' 몫 ───────────────────────
    #   ★ e2e(예측 수확량 투입) 를 노이즈 주입으로 흉내내지 않는다.
    #     R² 에 맞춰 노이즈를 넣고 R² 를 되읽는 순환논법이 되고(실측: 딸기 0.295→0.195,
    #     방울토마토 -0.257→+0.108 로 제멋대로), MAPE 는 0 근처 값에서 폭발한다.
    #     정직한 e2e 는 폴드별로 stage2 를 재학습해 얻은 '예측 수확량'을 stage3 에
    #     넣어야 한다 — 미구현(아래 결론 참조).
    price_actual = y_true_rev / y_true_yield          # 농가·시점별 실측 단가
    from models.m2_yield import CROP_MAP
    from pipeline.gates import evaluate_crop, read_stage2_metrics

    en = CROP_MAP.get(crop_ko, crop_ko)
    arts = ROOT / "models" / "artifacts"
    m2 = read_stage2_metrics(arts, en)
    verdict = evaluate_crop(arts, en)

    return {
        "crop": crop_ko, "n": int(len(d)),
        "stage2_cv_r2": (round(float(m2["cv_r2_mean"]), 3)
                         if m2.get("cv_r2_mean") is not None else None),
        "stage2_verdict": verdict["label"],
        # 단가 분포 — 매출 = 수확량 × 단가 이므로 단가 변동이 곧 매출 오차의 하한이다
        "price": {
            "median": round(price, 1),
            "cv_pct": round(float(np.std(price_actual) / np.mean(price_actual) * 100), 1),
            "p25": round(float(np.percentile(price_actual, 25)), 1),
            "p75": round(float(np.percentile(price_actual, 75)), 1),
        },
        # oracle = 수확량을 '완벽히 안다'고 가정하고 중앙단가로 환산했을 때의 매출 오차.
        #   즉 수확량 모델이 완벽해도 남는 오차 = 단가 변동 몫.
        "oracle_median_price": {"mape": round(_mape(y_true_rev, rev_oracle), 1),
                                "r2": round(_r2(y_true_rev, rev_oracle), 3)},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop", default=None)
    a = ap.parse_args()
    targets = [a.crop] if a.crop else CROPS

    rows = []
    for c in targets:
        try:
            r = validate(c)
        except Exception as e:
            logger.warning("  %s 실패: %s: %s", c, type(e).__name__, str(e)[:90])
            r = None
        if r:
            rows.append(r)

    if not rows:
        print("검증 가능한 작목 없음")
        return 1

    print("매출 구조 실측 — 수확량이 완벽해도 남는 오차(= 단가 변동 몫)\n")
    print(f"{'작목':<7}{'n':>5}{'stage2 CV R²':>13}{'단가중앙':>10}{'단가 CV':>9}"
          f"{'oracle MAPE':>12}{'oracle R²':>10}")
    for r in rows:
        p, o = r["price"], r["oracle_median_price"]
        print(f"{r['crop']:<7}{r['n']:>5}{str(r['stage2_cv_r2']):>13}"
              f"{p['median']:>10,.0f}{p['cv_pct']:>8.1f}%{o['mape']:>11.1f}%{o['r2']:>10.3f}")
    print("\n※ oracle = 수확량을 완벽히 안다고 가정하고 중앙단가로 환산한 매출의 오차.")
    print("   → 수확량 모델이 완벽해도 이만큼 틀린다. 단가 변동이 매출 오차의 하한이다.")
    print("※ stage3 의 보고 지표(CV MAPE)는 '실측 수확량'을 입력으로 잰 값이다(oracle 조건).")
    print("   서빙에는 stage2 의 '예측' 수확량이 들어가므로 그 값은 운영 정확도가 아니다.")
    print("※ 정직한 e2e 는 폴드별 stage2 재학습→예측→stage3 투입이 필요 — 미구현.")
    print("※ 소득(매출−경영비) 검증은 농가별 실측 경영비 부재로 원천 불가 — 과업① 소득조사 필요.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
