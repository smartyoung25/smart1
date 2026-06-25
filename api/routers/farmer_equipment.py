"""시설 기자재·연동·동의 라우터 — farmer.py에서 분리.

기자재 인벤토리(이기종 통합 매핑)·견적서 파싱·연동/서비스 신청·데이터 활용 동의.
farmer_state의 공유 router에 사이드 이펙트 등록.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from api.routers.farmer_state import router, _require_farm, _equipment_path

logger = logging.getLogger(__name__)


@router.post("/equipment/import", summary="견적서/시방서 업로드 → 기자재 초안 파싱(저장 안 함)")
async def import_equipment_doc(farm_id: str, file: UploadFile = File(...)):
    """엑셀/CSV/PDF/이미지 업로드 → 기자재 초안 목록 반환. 사용자가 검토 후 일괄 등록."""
    from api.services import equipment_import as _imp
    _require_farm(farm_id)
    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다(최대 8MB).")
    result = _imp.parse(file.filename or "", content)
    result["farm_id"] = farm_id
    # ★ 자동 재분류: 파싱된 초안 항목을 평가완료 카탈로그와 매칭 → 공종분류·등급 부여
    items = result.get("items") or result.get("draft") or []
    matched = 0
    for it in items:
        cls = _reclassify_from_catalog(
            (it.get("name") or it.get("item") or it.get("device_type") or ""),
            it.get("maker") or "", it.get("model") or it.get("form_name") or "")
        if cls:
            it.update(cls)
            matched += 1
    result["reclassified"] = matched
    result["total_items"] = len(items)
    return result


# ── 평가완료 카탈로그 매칭(자동 재분류) ──────────────────────────────────────
_CATALOG_CACHE = None


def _load_catalog():
    global _CATALOG_CACHE
    if _CATALOG_CACHE is None:
        import json as _json
        from pathlib import Path as _P
        p = _P(__file__).resolve().parents[1] / "data" / "reference" / "equipment_catalog.json"
        try:
            _CATALOG_CACHE = _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            _CATALOG_CACHE = []
    return _CATALOG_CACHE


def _reclassify_from_catalog(name: str, maker: str, model: str):
    """초안 항목명/제조사/모델 → 카탈로그 최적 매칭 → 분류·등급 dict 반환."""
    cat = _load_catalog()
    if not cat:
        return None
    name, maker, model = (name or "").strip(), (maker or "").strip(), (model or "").strip()
    if not (name or maker or model):
        return None

    import re as _re

    def _nk(x):
        x = _re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사|농업회사법인", "", x or "")
        return _re.sub(r"[\s()·.,/\-_]+", "", x).lower()

    nm_model, nm_maker, nm_name = _nk(model), _nk(maker), _nk(name)

    def score(rec):
        s = 0
        rm, rf, rt = _nk(rec.get("maker")), _nk(rec.get("form_name")), _nk(rec.get("model_type"))
        if nm_model and rf and (nm_model == rf):
            s += 6
        elif nm_model and rf and (nm_model in rf or rf in nm_model):
            s += 3
        if nm_maker and rm and (nm_maker == rm):
            s += 4
        elif nm_maker and rm and (nm_maker in rm or rm in nm_maker):
            s += 2
        if nm_name and rt and (nm_name in rt or rt in nm_name):
            s += 2
        return s

    best, best_s = None, 0
    for rec in cat:
        s = score(rec)
        if s > best_s:
            best, best_s = rec, s
    if not best or best_s < 3:   # 약한 매칭은 무시(오분류 방지)
        return None
    return {
        "gubun": best.get("gubun", ""),
        "model_type": best.get("model_type", ""),
        "grade": best.get("grade", ""),
        "gong": best.get("gong", ""),
        "score100": best.get("score100"),
        "match_confidence": best_s,
    }


@router.get("/equipment/schema", summary="기자재 분류·통합 입력 스키마 반환")
def get_equipment_schema(farm_id: str):
    import json as _json
    from pathlib import Path as _P
    _require_farm(farm_id)
    sp = _P(__file__).resolve().parents[1] / "data" / "equipment_schema.json"
    try: return _json.loads(sp.read_text(encoding="utf-8"))
    except Exception: return {"categories": [], "integration_fields": {}, "canonical_names": []}


@router.get("/equipment", summary="농가 시설 기자재 인벤토리 조회")
def get_equipment(farm_id: str):
    import json as _json
    _require_farm(farm_id)
    fp = _equipment_path(farm_id)
    items = []
    if fp.exists():
        try: items = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: items = []
    return {"farm_id": farm_id, "count": len(items), "items": items}


class EquipmentItem(BaseModel):
    """장비 1대 = 이기종 통합 매핑표 1행."""
    device_id:    str = Field(..., max_length=64)
    category:     str = Field("", max_length=32)
    device_type:  str = Field("", max_length=64)
    gubun:        str = Field("", max_length=32)    # 공종 대분류(구동기/측정기/제어기/농작업기/기타)
    model_type:   str = Field("", max_length=64)    # 기종명
    grade:        str = Field("", max_length=4)     # 종합등급 A~E
    gong:         str = Field("", max_length=40)    # 공종별 구분
    score100:     Optional[float] = None            # 환산점수(100)
    location:     str = Field("", max_length=64)
    maker:        str = Field("", max_length=64)
    model:        str = Field("", max_length=64)
    protocol:     str = Field("", max_length=32)
    host:         str = Field("", max_length=128)
    port:         Optional[int] = None
    unit_id:      Optional[int] = None
    datapoints:   list = Field(default_factory=list)  # [{tag,address,data_type,unit,scale,offset,rw,poll_interval,canonical_name}]
    install_date: str = Field("", max_length=20)


@router.post("/equipment", summary="시설 기자재 등록 (이기종 통합 매핑 포함)")
def post_equipment(farm_id: str, body: EquipmentItem):
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    _require_farm(farm_id)
    fp = _equipment_path(farm_id)
    items = []
    if fp.exists():
        try: items = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: items = []
    rec = body.model_dump()
    rec["ts"] = _dt.now(_tz.utc).isoformat()
    # device_id 중복 시 교체(upsert)
    items = [i for i in items if i.get("device_id") != rec["device_id"]]
    items.append(rec)
    try: fp.write_text(_json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass
    # 매핑된 표준변수 집계
    mapped = sorted({dp.get("canonical_name") for i in items for dp in (i.get("datapoints") or []) if dp.get("canonical_name")})
    return {"farm_id": farm_id, "saved": True, "device_id": rec["device_id"],
            "total_devices": len(items), "mapped_variables": mapped,
            "note": "표준변수로 매핑된 포인트는 제조사·프로토콜 무관하게 화면·모델이 사용합니다."}


class IntegrationRequest(BaseModel):
    """연동·서비스 신청 1건 (이기종 장비 연동·외부데이터·전문가 컨설팅 등)."""
    kind:        str = Field(..., max_length=40)   # equipment | external_data | expert | upgrade | other
    title:       str = Field(..., max_length=120)
    maker:       str = Field("", max_length=64)
    protocol:    str = Field("", max_length=40)
    infra_level: str = Field("", max_length=40)    # none | manual_valve | electric_switch (현재 인프라 정도)
    contact:     str = Field("", max_length=64)    # 연락처(전화/이메일)
    note:        str = Field("", max_length=500)


# 신청 가능한 항목 카탈로그 (메뉴·화면에서 노출)
_INTEGRATION_CATALOG = [
    {"kind": "equipment",     "icon": "🔌", "title": "이기종 장비 연동 신청",
     "desc": "제조사·프로토콜(Modbus·BACnet·MQTT 등) 무관 장비를 표준변수로 연동", "target": "c16_equipment.html"},
    {"kind": "external_data", "icon": "🛰️", "title": "외부 데이터 연동 신청",
     "desc": "흙토람 토양검정·팜맵 필지·위성 NDVI·기상/시세 외부 데이터 연계", "target": "c16_equipment.html"},
    {"kind": "expert",        "icon": "👨‍🌾", "title": "전문가 컨설팅 신청",
     "desc": "현장 진단 결과 기반 재배·경영 전문가 매칭 컨설팅", "target": "c4_diagnosis.html"},
    {"kind": "upgrade",       "icon": "⭐", "title": "서비스 등급 업그레이드 신청",
     "desc": "정밀제어·AI 출하예측 등 상위 기능 활성화", "target": "c8_billing.html"},
]


def _integration_path(farm_id: str):
    from pathlib import Path as _P
    d = _P(__file__).resolve().parents[1] / "data" / "integration_requests"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{farm_id}.json"


class ConsentBody(BaseModel):
    mode: str = Field("", max_length=40)            # private|learning|benchmark|network
    items: dict = Field(default_factory=dict)        # {env:true, irr:true, ...}
    note: str = Field("", max_length=200)


def _consent_path(farm_id: str):
    from pathlib import Path as _P
    d = _P(__file__).resolve().parents[1] / "data" / "consent"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{farm_id}.json"


@router.get("/consent", summary="데이터 활용 동의 설정 조회")
def get_consent(farm_id: str):
    import json as _json
    fp = _consent_path(farm_id)
    if fp.exists():
        try: return _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: pass
    return {"farm_id": farm_id, "mode": "", "items": {}, "saved": False}


@router.post("/consent", summary="데이터 활용 동의 설정 저장")
def post_consent(farm_id: str, body: ConsentBody):
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    _require_farm(farm_id)
    rec = body.model_dump()
    rec["farm_id"] = farm_id
    rec["saved"] = True
    rec["updated_at"] = _dt.now(_tz.utc).isoformat()
    on = sum(1 for v in (rec.get("items") or {}).values() if v)
    rec["shared_count"] = on
    try: _consent_path(farm_id).write_text(_json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass
    return {"farm_id": farm_id, "saved": True, "mode": rec["mode"],
            "shared_count": on, "note": "데이터 활용 동의가 저장되었습니다."}


@router.get("/integration-catalog", summary="신청 가능한 연동·서비스 항목 목록")
def get_integration_catalog(farm_id: str):
    return {"farm_id": farm_id, "items": _INTEGRATION_CATALOG}


@router.get("/integration-request", summary="제출한 연동·서비스 신청 내역")
def list_integration_requests(farm_id: str):
    import json as _json
    fp = _integration_path(farm_id)
    items = []
    if fp.exists():
        try: items = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: items = []
    return {"farm_id": farm_id, "requests": items, "total": len(items)}


@router.post("/integration-request", summary="연동·서비스 신청 접수")
def post_integration_request(farm_id: str, body: IntegrationRequest):
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    _require_farm(farm_id)
    fp = _integration_path(farm_id)
    items = []
    if fp.exists():
        try: items = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: items = []
    rec = body.model_dump()
    rec["id"] = f"req_{int(_dt.now(_tz.utc).timestamp())}"
    rec["ts"] = _dt.now(_tz.utc).isoformat()
    rec["status"] = "접수"   # 접수 → 검토 → 연동완료
    items.append(rec)
    try: fp.write_text(_json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass
    return {"farm_id": farm_id, "accepted": True, "request_id": rec["id"],
            "status": rec["status"], "total": len(items),
            "note": "신청이 접수되었습니다. 담당자가 검토 후 연동을 진행합니다."}


@router.delete("/equipment/{device_id}", summary="기자재 삭제")
def delete_equipment(farm_id: str, device_id: str):
    import json as _json
    _require_farm(farm_id)
    fp = _equipment_path(farm_id)
    items = []
    if fp.exists():
        try: items = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: items = []
    n0 = len(items)
    items = [i for i in items if i.get("device_id") != device_id]
    try: fp.write_text(_json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass
    return {"farm_id": farm_id, "deleted": n0 - len(items), "remaining": len(items)}
