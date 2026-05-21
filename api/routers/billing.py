"""빌링/구독 라우터.

엔드포인트:
    GET  /api/farms/{farm_id}/billing/plan        현재 플랜 + 가용 기능 전체
    GET  /api/farms/{farm_id}/billing/quota       AI 채팅 쿼터 현황
    GET  /api/farms/{farm_id}/billing/features    섹션별 기능 잠금 상태 (UI 게이팅용)
    POST /api/farms/{farm_id}/billing/upgrade     업그레이드 요청 (결제 PG stub)
    GET  /api/admin/billing/overview              전체 농장 티어 현황 (관리자)
    POST /api/admin/billing/set-tier              농장 티어 직접 설정 (관리자)
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.middleware.auth import require_auth
from api.services.billing import (
    check_chat_quota, check_feature, consume_chat_quota,
    get_farm_tier, get_plan_info, set_farm_tier, tier_rank,
)

logger = logging.getLogger(__name__)

# ── 농가 라우터 (prefix: /api/farms/{farm_id}/billing) ───────────────────────
farm_router  = APIRouter(tags=["billing"])
# ── 관리자 라우터 (prefix: /api/admin/billing) ───────────────────────────────
admin_router = APIRouter(tags=["billing_admin"])


# ---------------------------------------------------------------------------
# 스키마
# ---------------------------------------------------------------------------

class UpgradeRequest(BaseModel):
    target_tier: str
    pg_channel:  str = "manual"   # "kakaopay" | "toss" | "manual"


class UpgradeResponse(BaseModel):
    status:       str   # "requested" | "approved" | "redirect_url"
    message_ko:   str
    redirect_url: Optional[str] = None
    request_id:   Optional[str] = None


class SetTierRequest(BaseModel):
    farm_id: str
    tier:    str


# ---------------------------------------------------------------------------
# GET /api/farms/{farm_id}/billing/plan
# ---------------------------------------------------------------------------

@farm_router.get("/billing/plan")
def get_billing_plan(farm_id: str, user: dict = Depends(require_auth)):
    """현재 구독 티어, 가용 기능 전체, 업그레이드 옵션 반환."""
    return get_plan_info(farm_id)


# ---------------------------------------------------------------------------
# GET /api/farms/{farm_id}/billing/quota
# ---------------------------------------------------------------------------

@farm_router.get("/billing/quota")
def get_quota(farm_id: str, user: dict = Depends(require_auth)):
    """AI 채팅 쿼터 현황."""
    return check_chat_quota(farm_id)


# ---------------------------------------------------------------------------
# GET /api/farms/{farm_id}/billing/features
# ---------------------------------------------------------------------------

@farm_router.get("/billing/features")
def get_features(
    farm_id: str,
    section: Optional[str] = Query(None, description="섹션 필터 (environ|irrigation|growth|market|energy|control|ai_chat)"),
    user: dict = Depends(require_auth),
):
    """섹션별 기능 잠금 상태. section 파라미터로 필터 가능.

    UI tierGuard()가 이 엔드포인트를 호출해 잠금 오버레이를 표시합니다.
    """
    plan = get_plan_info(farm_id)
    items = plan["unlocked"] + plan["locked"]
    if section:
        items = [i for i in items if i["section"] == section]

    tier = plan["tier"]
    return {
        "farm_id":  farm_id,
        "tier":     tier,
        "section":  section,
        "features": [
            {**i, "allowed": tier_rank(tier) >= tier_rank(i["min_tier"])}
            for i in items
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/farms/{farm_id}/billing/upgrade
# ---------------------------------------------------------------------------

@farm_router.post("/billing/upgrade", response_model=UpgradeResponse)
def request_upgrade(
    farm_id: str,
    body: UpgradeRequest,
    user: dict = Depends(require_auth),
):
    """업그레이드 요청. 결제 PG 연동 전 stub — 'manual' 채널은 즉시 승인."""
    from uuid import uuid4
    current = get_farm_tier(farm_id)
    if tier_rank(body.target_tier) <= tier_rank(current):
        raise HTTPException(
            status_code=400,
            detail=f"현재 티어({current})보다 높은 티어로만 업그레이드 가능합니다.",
        )

    req_id = f"upg_{uuid4().hex[:10]}"

    # manual 채널: 즉시 승인 (데모/운영자 직접 처리)
    if body.pg_channel == "manual":
        set_farm_tier(farm_id, body.target_tier)
        logger.info("[billing] 업그레이드 승인 (manual) farm=%s %s→%s", farm_id, current, body.target_tier)
        return UpgradeResponse(
            status="approved",
            message_ko=f"업그레이드 완료: {current} → {body.target_tier} (수동 승인)",
            request_id=req_id,
        )

    # KakaoPay / Toss: stub redirect (실 PG 연동 시 결제창 URL 반환)
    redirect_url = f"https://payment-stub.smartfarm.example/checkout?req={req_id}&tier={body.target_tier}"
    _db_log_upgrade_request(farm_id, body.target_tier, body.pg_channel, req_id)
    logger.info("[billing] 업그레이드 요청 farm=%s %s→%s pg=%s req=%s",
                farm_id, current, body.target_tier, body.pg_channel, req_id)
    return UpgradeResponse(
        status="redirect_url",
        message_ko=f"결제 페이지로 이동합니다 ({body.pg_channel})",
        redirect_url=redirect_url,
        request_id=req_id,
    )


def _db_log_upgrade_request(farm_id: str, target_tier: str, pg_channel: str, req_id: str) -> None:
    try:
        from api.services.db import get_connection  # type: ignore
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO upgrade_requests (farm_id, requested_tier, pg_channel, status)
                       VALUES (%s, %s, %s, 'pending')""",
                    (farm_id, target_tier, pg_channel)
                )
            conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# GET /api/admin/billing/overview
# ---------------------------------------------------------------------------

@admin_router.get("/billing/overview")
def admin_billing_overview(user: dict = Depends(require_auth)):
    """전체 농장 티어 현황 (관리자 대시보드용)."""
    from api.routers.farmer import _FARM_META   # type: ignore
    rows = []
    for farm_id in _FARM_META:
        tier = get_farm_tier(farm_id)
        quota = check_chat_quota(farm_id)
        rows.append({
            "farm_id":    farm_id,
            "tier":       tier,
            "chat_used":  quota["used"],
            "chat_max":   quota["max"],
        })
    return {
        "farms":       rows,
        "total":       len(rows),
        "by_tier":     {t: sum(1 for r in rows if r["tier"] == t) for t in ["basic","smart","pro","enterprise"]},
    }


# ---------------------------------------------------------------------------
# POST /api/admin/billing/set-tier
# ---------------------------------------------------------------------------

@admin_router.post("/billing/set-tier")
def admin_set_tier(body: SetTierRequest, user: dict = Depends(require_auth)):
    """관리자용 티어 직접 설정 (개발·데모 전용)."""
    if user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    try:
        set_farm_tier(body.farm_id, body.tier)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    logger.info("[billing] 관리자 티어 설정 farm=%s → %s by=%s", body.farm_id, body.tier, user.get("sub"))
    return {"status": "ok", "farm_id": body.farm_id, "tier": body.tier}
