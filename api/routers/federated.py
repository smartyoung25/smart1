# -*- coding: utf-8 -*-
"""연합학습 전송 계층 — 농장(온프레미스/엣지)이 산출한 보정 파라미터만 수집.

원본 데이터는 농장에 잔류하고, 스칼라 보정계수만 업로드된다(개인정보·영업비밀 보호).
- POST /api/federated/correction : 농장 로컬 산출 파라미터 병합 (인증 필요)
- GET  /api/federated/corrections/{crop_en} : 현재 보정 현황 요약

보안: 인증 미들웨어(/api/* 보호)로 토큰 필수. 공개 데모(PUBLIC_DEMO)에서는
쓰기(POST)가 미들웨어에서 403 차단되어 변형 불가(읽기 GET만 동작).
"""
from __future__ import annotations
import json
import os
from typing import List, Dict, Any
from fastapi import APIRouter, Body, Depends, HTTPException

from api.middleware.auth import require_auth
from pipeline.federated.aggregate import merge_corrections, ARTS

router = APIRouter(prefix="/api/federated", tags=["federated"])

_OWNER_BYPASS = ("admin", "manager", "superadmin", "demo")


@router.post("/correction", summary="농장 로컬 보정 파라미터 업로드·병합 (원본 미반출)")
def post_correction(body: dict = Body(...), user: dict = Depends(require_auth)) -> Dict[str, Any]:
    crop_en = str(body.get("crop_en", "")).strip()
    crop_ko = str(body.get("crop_ko", "")).strip()
    payloads: List[Dict[str, Any]] = body.get("corrections") or []
    if not crop_en:
        raise HTTPException(status_code=400, detail="crop_en 필요")
    if not isinstance(payloads, list) or not payloads:
        raise HTTPException(status_code=400, detail="corrections(list) 필요")
    # I3 차단: 업로드 farm_id를 토큰 농장으로 바인딩 — 임의 농장 보정 덮어쓰기 방지.
    #   (관리자/매니저/데모는 다농장 일괄 업로드 허용.)
    role = (user or {}).get("role", "")
    token_farm = (user or {}).get("farm_id", "")
    is_operator = role in _OWNER_BYPASS
    # 파라미터만 허용 — 원본 데이터 필드가 섞여 오면 거부(반출 방지 가드)
    clean = []
    for p in payloads:
        if not isinstance(p, dict) or "farm_id" not in p or "factor" not in p:
            continue
        if not is_operator and p.get("farm_id") != token_farm:
            raise HTTPException(status_code=403, detail="본인 농장의 보정값만 업로드할 수 있습니다.")
        clean.append({k: p.get(k) for k in ("farm_id", "factor", "raw_geo", "n", "shrink")})
    if not clean:
        raise HTTPException(status_code=400, detail="유효한 보정 파라미터 없음(farm_id·factor 필수)")
    res = merge_corrections(crop_en, clean, crop_ko=crop_ko)
    return {"ok": True, **res}


@router.get("/corrections/{crop_en}", summary="작물별 농장 보정 현황 요약")
def get_corrections(crop_en: str) -> Dict[str, Any]:
    path = os.path.join(ARTS, crop_en, "farm_corrections.json")
    if not os.path.exists(path):
        return {"crop_en": crop_en, "n_farms": 0, "source": None}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return {"crop_en": crop_en, "crop_ko": d.get("crop"),
            "n_farms": d.get("n_farms", len(d.get("corrections", {}))),
            "source": d.get("_source", "central_batch"),
            "global_median": d.get("global_median")}
