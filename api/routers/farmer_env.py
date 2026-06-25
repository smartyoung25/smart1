"""환경관리 전략표(climate-plan) 라우터 — farmer.py에서 분리.

생육시기×하루구간 목표 설정값·광연동승온·온도적산·전략표 대비 편차 처방.
farmer_state의 공유 router에 사이드 이펙트 등록.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

from api.routers.farmer_state import router, _FARM_META, _require_farm

logger = logging.getLogger(__name__)


@router.get("/environment/climate-plan", summary="환경관리 전략표(생육시기×하루구간 설정값) 조회")
def get_climate_plan(farm_id: str, mode: str = "", crop: str = ""):
    from api.services import climate_plan as _cp
    _require_farm(farm_id)
    _crop = crop or (_FARM_META.get(farm_id, {}) or {}).get("crop") or "딸기"
    if mode:   # 모드 지정 시 해당 모드 기본 템플릿(미저장이어도 즉시 표 제공)
        fp = _cp._plan_path(farm_id)
        if fp.exists():
            try:
                import json as _j
                saved = _j.loads(fp.read_text(encoding="utf-8"))
                if saved.get("mode") == mode:
                    saved["periods_def"] = _cp.PERIODS
                    return saved
            except Exception:
                pass
        return _cp.build_template(_crop, mode,
                                  (_cp.load_plan(farm_id, _crop) or {}).get("transplant_date", ""))
    return _cp.load_plan(farm_id, _crop)


@router.post("/environment/climate-plan", summary="환경관리 전략표 저장")
def post_climate_plan(farm_id: str, body: dict):
    from api.services import climate_plan as _cp
    _require_farm(farm_id)
    return _cp.save_plan(farm_id, body)


def _farm_sun_times(farm_id: str):
    """농장 좌표 → 오늘 일출·일몰(시). 실패 시 (None,None)."""
    try:
        from api.services import climate_plan as _cp
        from api.services.extended_weather import _coords
        m = _FARM_META.get(farm_id, {}) or {}
        lat, lon = _coords(m.get("sido") or "", m.get("sigungu") or "")
        return _cp.sun_times(lat, lon)
    except Exception:
        return None, None


@router.get("/environment/climate-plan/active", summary="정식일+현재시각 기준 지금 적용 목표값(광연동·일출경계·온도적산)")
def get_climate_active(farm_id: str, crop: str = "", hour: int = -1, solar: float = -1, sun: int = 1):
    from api.services import climate_plan as _cp
    _require_farm(farm_id)
    _crop = crop or (_FARM_META.get(farm_id, {}) or {}).get("crop") or "딸기"
    sr, ss = _farm_sun_times(farm_id) if sun else (None, None)
    return _cp.active_setpoint(farm_id, _crop, hour if hour >= 0 else None,
                               solar if solar >= 0 else None, sr, ss)


@router.post("/environment/climate-plan/daily-temp", summary="실측 기온 샘플 기록(온도적산 입력)")
def post_daily_temp(farm_id: str, body: dict):
    from api.services import climate_plan as _cp
    _require_farm(farm_id)
    t = body.get("temp")
    if t is None:
        raise HTTPException(status_code=400, detail="temp 필요")
    # 현재 목표 24h 평균을 함께 기록(부족분 계산 기준)
    act = _cp.active_setpoint(farm_id, (_FARM_META.get(farm_id, {}) or {}).get("crop") or "딸기")
    tgt_avg = (act.get("metrics") or {}).get("avg24")
    return _cp.record_daily_temp(farm_id, float(t), tgt_avg, body.get("date"))


@router.get("/environment/climate-plan/evaluate",
            summary="전략표 목표 대비 실측 편차 → 제어 처방(AI 제어·이상감지 기준선)")
def get_climate_evaluate(farm_id: str, crop: str = "", temp: float = -999,
                         rh: float = -1, co2: float = -1, solar: float = -1, hour: int = -1):
    from api.services import climate_plan as _cp
    _require_farm(farm_id)
    _crop = crop or (_FARM_META.get(farm_id, {}) or {}).get("crop") or "딸기"
    measured = {}
    if temp > -900: measured["temp"] = temp
    if rh >= 0:     measured["rh"] = rh
    if co2 >= 0:    measured["co2"] = co2
    sr, ss = _farm_sun_times(farm_id)
    if sr is not None: measured["sunrise"], measured["sunset"] = sr, ss
    return _cp.evaluate(farm_id, _crop, measured,
                        hour if hour >= 0 else None, solar if solar >= 0 else None)
