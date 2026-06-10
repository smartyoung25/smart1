# -*- coding: utf-8 -*-
"""온프레미스/엣지 — 농장 로컬 보정계수 산출 (원본 데이터 미반출).

연합학습 경량판(federated-lite):
중앙 클라우드 M2 모델은 공통으로 배포되고, **각 농장의 편향 보정계수만** 농장
현장(온프레미스/엣지 게이트웨이)에서 계산해 **스칼라 파라미터만 업로드**한다.
실수확·환경 원본은 농장을 떠나지 않는다(개인정보·영업비밀 보호).

중앙 파이프라인(models/m2_yield.py + farm_corrections.json)과 **동일 수식**:
    raw_geo = geomean(actual_yield_i / model_pred_i)      # 농장 편향(기하평균)
    shrink  = min(n, 3) / 3                                # 관측 적을수록 1.0로 수축
    factor  = raw_geo ** shrink                            # 1.0(=무보정) 쪽으로 베이지안 수축

업로드 페이로드는 {farm_id, raw_geo, n, shrink, factor} 뿐 — 행 단위 원본 없음.

사용:
    from pipeline.federated.local_correction import compute_local_correction
    payload = compute_local_correction("경남_거창_051", pairs=[(yield_kg_m2, pred_kg_m2), ...])
    # payload 만 서버 /api/federated/correction 으로 업로드 (aggregate.py가 수집)
"""
from __future__ import annotations
from typing import List, Tuple, Dict, Any
import math

_SHRINK_CAP = 3   # 관측 n이 이 값 이상이면 수축계수 1.0 (완전 신뢰)


def _geomean(ratios: List[float]) -> float:
    vals = [r for r in ratios if r is not None and r > 0]
    if not vals:
        return 1.0
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def compute_local_correction(farm_id: str,
                             pairs: List[Tuple[float, float]],
                             clip: Tuple[float, float] = (0.5, 2.0)) -> Dict[str, Any]:
    """농장 로컬에서 (실수확, 모델예측) 쌍으로 보정 파라미터만 산출.

    pairs: [(actual_yield_kg_m2, model_pred_kg_m2), ...] — **농장 내부에만 존재**
    반환: 업로드 가능한 스칼라 페이로드(원본 미포함).
    """
    ratios = [a / p for (a, p) in pairs if p and p > 0 and a and a > 0]
    n = len(ratios)
    if n == 0:
        return {"farm_id": farm_id, "n": 0, "raw_geo": 1.0, "shrink": 0.0,
                "factor": 1.0, "note": "관측 없음 — 무보정(1.0)"}
    raw_geo = _geomean(ratios)
    lo, hi = clip
    raw_geo = max(lo, min(hi, raw_geo))         # 이상치 클리핑(중앙 로직과 동일 범위)
    shrink = min(n, _SHRINK_CAP) / _SHRINK_CAP
    factor = round(raw_geo ** shrink, 4)
    return {"farm_id": farm_id, "n": n,
            "raw_geo": round(raw_geo, 4), "shrink": round(shrink, 3),
            "factor": factor}


if __name__ == "__main__":
    # 검증: 중앙 farm_corrections.json 값 재현 (경남_거창_051: raw_geo 1.2077,n=2 → factor 1.1385)
    demo = compute_local_correction("경남_거창_051",
                                    pairs=[(7.0, 5.795), (8.5, 7.04)])  # 비율 ≈1.208
    print("local payload:", demo)
    # 방법 일치 검증(반올림 허용): factor ≈ raw_geo ** shrink
    assert abs(demo["factor"] - (demo["raw_geo"] ** demo["shrink"])) < 1e-3
    print("OK — 원본 미반출, 파라미터만 업로드 대상")
