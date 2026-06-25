"""PDCA 적기적작 경영관리 라우터 — farmer.py에서 분리.

farmer_state의 공유 router에 PDCA 라우트를 등록한다(사이드 이펙트 임포트).
main.py가 farmer_pdca를 import하면 이 라우트도 farmer.router에 포함된다.
"""
from __future__ import annotations

import logging

from api.routers.farmer_state import router, _FARM_META, _require_farm

logger = logging.getLogger(__name__)


@router.get("/pdca/summary", summary="PDCA 3대 지수 요약 (효과성·효율성·성장가능성)")
def get_pdca_summary(farm_id: str):
    """적기적작 3대 KPI + 오늘의 PDCA 4단계 요약."""
    _require_farm(farm_id)
    from api.services import pdca as _pdca
    meta = _FARM_META.get(farm_id, {}) or {}
    crop = meta.get("crop_ko") or meta.get("crop") or "딸기"
    td = meta.get("transplant_date")
    season = _pdca.pdca_season(farm_id)
    return {
        "farm_id": farm_id,
        "crop": crop,
        "transplant_date": td,
        "effectiveness":    season["effectiveness"],
        "efficiency":       season["efficiency"],
        "growth_potential": season["growth_potential"],
        "season":           season,
        "daily":            _pdca.pdca_daily(farm_id),
    }


@router.get("/pdca/weekly", summary="주간 PDCA 체크포인트 (최근 4주)")
def get_pdca_weekly(farm_id: str, week_offset: int = 0):
    """주간 PDCA 상세 — Plan/Do/Check/Act 4단계 결과."""
    _require_farm(farm_id)
    from api.services import pdca as _pdca
    weeks = []
    for offset in range(3, -1, -1):
        try:
            weeks.append(_pdca.pdca_weekly(farm_id, week_offset=offset))
        except Exception:
            pass
    return {"farm_id": farm_id, "weeks": weeks, "season": _pdca.pdca_season(farm_id)}


@router.get("/pdca/thresholds", summary="현재 임계값 초과 항목 목록")
def get_pdca_thresholds(farm_id: str):
    """환경 센서값과 PDCA 임계값 비교 → 경보 항목 반환."""
    _require_farm(farm_id)
    from api.services import pdca as _pdca
    alerts = _pdca.get_threshold_alerts(farm_id)
    return {
        "farm_id": farm_id,
        "alert_count": len(alerts),
        "danger_count": sum(1 for a in alerts if a["severity"] == "danger"),
        "warn_count":   sum(1 for a in alerts if a["severity"] == "warn"),
        "alerts": alerts,
        "thresholds": _pdca.THRESHOLDS,
    }


@router.get("/pdca/consult", summary="컨설턴트 개입 트리거 목록")
def get_pdca_consult(farm_id: str):
    """효과성·착과기·드리프트 3대 트리거 기반 컨설턴트 개입 시점 반환."""
    _require_farm(farm_id)
    from api.services import pdca as _pdca
    return {"farm_id": farm_id, **_pdca.consult_triggers(farm_id)}
