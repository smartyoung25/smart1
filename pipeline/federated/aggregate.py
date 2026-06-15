# -*- coding: utf-8 -*-
"""서버측 — 농장이 업로드한 보정 파라미터만 수집·병합 (원본 데이터 없음).

각 농장(온프레미스/엣지)이 local_correction.py로 산출해 업로드한 스칼라
페이로드를 받아 작물별 farm_corrections.json 에 병합한다. 행 단위 원본은
서버에 도달하지 않는다 — 연합학습의 '파라미터만 공유' 원칙.

이 모듈은 기존 중앙배치(models/artifacts/<crop>/farm_corrections.json) 포맷과
호환되어, 추론측 models/m2_yield._load_corrections()가 그대로 사용한다.

사용:
    from pipeline.federated.aggregate import merge_corrections
    merge_corrections("strawberry", [payload1, payload2, ...])  # 업로드 수집분
"""
from __future__ import annotations
from typing import List, Dict, Any
import json
import os

ARTS = os.path.join(os.path.dirname(__file__), "..", "..", "models", "artifacts")

# I3 차단: 업로드된 보정계수의 허용 범위 — 모델 추론 왜곡(factor 0/거대값) 방지.
_FACTOR_MIN, _FACTOR_MAX = 0.5, 2.0


def _clip(val, lo, hi, default):
    """숫자형으로 강제 + [lo,hi] 클램프. 비정상값은 default."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    if f != f:               # NaN
        return default
    return max(lo, min(hi, f))


def merge_corrections(crop_en: str, payloads: List[Dict[str, Any]],
                      crop_ko: str = "") -> Dict[str, Any]:
    """업로드된 농장 파라미터들을 farm_corrections.json 에 병합.

    payloads: [{farm_id, factor, raw_geo, n, shrink}, ...] (원본 미포함)
    """
    path = os.path.join(ARTS, crop_en, "farm_corrections.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"crop": crop_ko, "crop_en": crop_en, "corrections": {}}

    corr = data.setdefault("corrections", {})
    updated = 0
    for p in payloads:
        fid = p.get("farm_id")
        if not fid or "factor" not in p:
            continue
        # 범위검증: factor[0.5,2.0]·shrink[0,1] 클램프, n은 음수/비정상 제거(추론 오염 차단)
        factor = _clip(p["factor"], _FACTOR_MIN, _FACTOR_MAX, default=1.0)
        shrink = _clip(p.get("shrink"), 0.0, 1.0, default=None)
        try:
            n_val = max(0, int(p.get("n"))) if p.get("n") is not None else None
        except (TypeError, ValueError):
            n_val = None
        corr[fid] = {"factor": factor, "raw_geo": p.get("raw_geo"),
                     "n": n_val, "shrink": shrink}
        updated += 1

    data["n_farms"] = len(corr)
    data["_source"] = "federated_upload"          # 출처 표기(중앙배치와 구분)
    os.makedirs(os.path.dirname(path), exist_ok=True)   # 신규 작물 디렉터리 생성
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return {"crop_en": crop_en, "updated": updated, "n_farms": len(corr), "path": path}


if __name__ == "__main__":
    # dry-run 예시(실제 파일 미수정): 병합 결과 형태만 출력
    demo = [{"farm_id": "demo_farm_X", "factor": 1.05, "raw_geo": 1.08, "n": 2, "shrink": 0.667}]
    print("merge payload 형태:", json.dumps(demo, ensure_ascii=False))
    print("→ farm_corrections.json corrections[farm_id] 로 병합됨 (원본 데이터 없음)")
