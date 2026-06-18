"""기자재·시공업체 공식 참조 데이터 API (읽기 전용)

스마트팜코리아 공식 DB를 빌드한 api/data/reference/*.json 을 서빙한다.
모두 GET(읽기) — PUBLIC_DEMO 쓰기 게이트와 무관.

엔드포인트:
    GET /api/reference/taxonomy            공식 분류체계(5대분류)
    GET /api/reference/devices?q=&cat=     자사제품 검색(제조사·모델·표준장치명)
    GET /api/reference/vendors?q=&sector=  기업 디렉터리 검색
    GET /api/reference/construction?q=&region=&rank=  온실 시공업체 도급순위
    GET /api/reference/meta                출처·버전·집계
"""
from __future__ import annotations
import json
import os
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/reference", tags=["reference"])

_REF_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "reference")


@lru_cache(maxsize=8)
def _load(name: str):
    path = os.path.join(_REF_DIR, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _match(text: str, q: str) -> bool:
    return q.lower() in (text or "").lower()


@router.get("/taxonomy")
def taxonomy():
    """공식 분류체계(대분류 → 표준 장치명)."""
    return {"categories": _load("equipment_taxonomy.json")}


@router.get("/taxonomy2")
def taxonomy2():
    """공종별 분류체계 v2 (건축/기자재 3계층)."""
    return {"groups": _load("equipment_taxonomy_v2.json")}


@router.get("/criteria")
def criteria():
    """12항목 5등급 평가기준."""
    return {"criteria": _load("evaluation_criteria.json")}


@router.get("/catalog")
def catalog(
    q: str = Query("", description="업체/형식명/기종명 부분일치"),
    gubun: str = Query("", description="대분류(구동기/측정기/제어기/농작업기/기타)"),
    model_type: str = Query("", description="기종명"),
    grade: str = Query("", description="종합등급(A~E)"),
    limit: int = Query(30, ge=1, le=200),
):
    """평가완료 제품 카탈로그 검색 — C16 자동완성·등급조회용."""
    items = _load("equipment_catalog.json")
    out = []
    for it in items:
        if gubun and it.get("gubun") != gubun:
            continue
        if model_type and model_type not in (it.get("model_type") or ""):
            continue
        if grade and it.get("grade") != grade:
            continue
        if q and not (_match(it.get("maker", ""), q)
                      or _match(it.get("form_name", ""), q)
                      or _match(it.get("model_type", ""), q)):
            continue
        out.append(it)
        if len(out) >= limit:
            break
    return {"count": len(out), "items": out}


@router.get("/meta")
def meta():
    return {"v1": _load("_meta.json"), "v2": _load("_catalog_meta.json")}


@router.get("/devices")
def devices(
    q: str = Query("", description="제조사/모델/표준장치명 부분일치"),
    cat: str = Query("", description="공식 대분류 필터"),
    field: str = Query("", description="활용분야 필터(시설원예/축산)"),
    limit: int = Query(30, ge=1, le=200),
):
    """자사제품 검색 — C16 장비추가 자동완성용."""
    items = _load("vendor_products.json")
    out = []
    for it in items:
        if cat and it.get("category") != cat:
            continue
        if field and field not in (it.get("field") or ""):
            continue
        if q and not (_match(it.get("maker", ""), q)
                      or _match(it.get("model", ""), q)
                      or _match(it.get("std_device", ""), q)
                      or _match(it.get("company", ""), q)):
            continue
        out.append(it)
        if len(out) >= limit:
            break
    return {"count": len(out), "items": out}


@router.get("/vendors")
def vendors(
    q: str = Query("", description="기업명/ICT제품 부분일치"),
    sector: str = Query("", description="사업분야 필터(시설원예/축산 등)"),
    region: str = Query("", description="주소 시·도 부분일치"),
    limit: int = Query(30, ge=1, le=200),
):
    """기업(제조/유통/시공) 디렉터리 검색."""
    items = _load("vendors.json")
    out = []
    for it in items:
        if sector and sector not in (it.get("sectors") or []):
            continue
        if region and not _match(it.get("address", ""), region):
            continue
        if q and not (_match(it.get("name", ""), q)
                      or _match(it.get("ict_products", ""), q)):
            continue
        out.append(it)
        if len(out) >= limit:
            break
    return {"count": len(out), "items": out}


@router.get("/construction")
def construction(
    q: str = Query("", description="상호 부분일치"),
    region: str = Query("", description="지역(시·도) 부분일치"),
    rank: str = Query("", description="도급순위 군별(1군/2군)"),
    limit: int = Query(50, ge=1, le=200),
):
    """온실 시공업체 도급순위 검색."""
    items = _load("construction_companies.json")
    out = []
    for it in items:
        if rank and it.get("rank_group") != rank:
            continue
        if region and not (_match(it.get("region", ""), region)
                           or _match(it.get("address", ""), region)):
            continue
        if q and not _match(it.get("name", ""), q):
            continue
        out.append(it)
        if len(out) >= limit:
            break
    return {"count": len(out), "items": out}
