"""출하 시점 최적화 라우트.

연구개발계획서 과업②(다) "출하타이밍 최적화".
farmer_state 의 공유 router 에 사이드 이펙트로 등록(farmer_env·farmer_tasks 와 동일 패턴).

판단 로직은 api/services/shipping_timing.py 에 있다 — 여기서는 농장 작목만 넘긴다.
"""
from __future__ import annotations

import logging

from api.routers.farmer_state import router, _FARM_META, _require_farm

logger = logging.getLogger(__name__)


@router.get("/shipping/timing", summary="출하 시점 최적화 (월별 실측 단가 기반)")
def get_shipping_timing(farm_id: str, horizon_months: int = 6):
    """지금부터 horizon 개월 내 단가가 가장 높은 출하월을 제시한다.

    ★ 단가만 본다 — 저장성·품질 저하·수확 시기는 반영하지 않는다.
      응답의 caveat 를 화면이 반드시 함께 노출해야 한다.
    """
    _require_farm(farm_id)
    from api.services.shipping_timing import recommend
    crop = (_FARM_META.get(farm_id, {}) or {}).get("crop") or "딸기"
    return recommend(crop, horizon_months=max(1, min(12, horizon_months)))
