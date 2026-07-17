"""일일·주간 작업추천 라우트.

연구개발계획서 과업④ "주간/일일작업추천시스템".
farmer_state 의 공유 router 에 사이드 이펙트로 등록한다(farmer_env 와 동일 패턴).

판단 로직은 전부 api/services/task_recommend.py 에 있다 — 여기서는 농장 컨텍스트
(작목·실측 환경·일출일몰)를 모아 넘기고 결과를 그대로 반환한다.
"""
from __future__ import annotations

import logging

from api.routers.farmer_state import router, _FARM_META, _require_farm

logger = logging.getLogger(__name__)


def _ctx(farm_id: str):
    """작목·실측환경·일출일몰. 헬퍼는 이미 있는 것을 재사용한다(중복 판정 방지)."""
    _require_farm(farm_id)
    meta = _FARM_META.get(farm_id, {}) or {}
    crop = meta.get("crop") or "딸기"

    # 실측 환경 — farmer.py 의 단일 구현을 쓴다(순환 import 를 피해 함수 안에서 import).
    try:
        from api.routers.farmer import _get_env
        env = _get_env(farm_id) or {}
    except Exception as e:
        logger.warning("[tasks] 환경 조회 실패(빈 값으로 진행): %s", e)
        env = {}

    try:
        from api.routers.farmer_env import _farm_sun_times
        sr, ss = _farm_sun_times(farm_id)
    except Exception:
        sr = ss = None
    sun = (sr, ss) if sr is not None else None
    return crop, env, sun


@router.get("/tasks/daily", summary="오늘의 작업추천 (관수 Period·환경 전략표 편차·기록)")
def get_daily_tasks(farm_id: str):
    """규칙 기반 일일 작업추천 — LLM 불필요.

    근거 없는 지시를 만들지 않는다: 실측이 없으면 추천 대신 '기록하기'를 낸다.
    각 작업은 why(근거)를 포함한다.
    """
    from api.services.task_recommend import daily_tasks
    crop, env, sun = _ctx(farm_id)
    return daily_tasks(farm_id, crop=crop, env=env, sun=sun)


@router.get("/tasks/weekly", summary="이번 주 작업추천 (요일별 점검·주간 리뷰)")
def get_weekly_tasks(farm_id: str):
    from api.services.task_recommend import weekly_tasks
    crop, _env, _sun = _ctx(farm_id)
    return weekly_tasks(farm_id, crop=crop)
