"""POST /api/v2/recommend — 범용 수익 최적화 추천 엔드포인트

farm_id 불필요. 환경값을 직접 전달하면 즉시 추천 + 이상 감지 결과를 반환.

Request:
    POST /api/v2/recommend
    {
        "farm_id": "farm_001",      // optional, 로깅용
        "crop":    "딸기",
        "tier":    "semi_auto",     // "manual" | "semi_auto" | "auto"
        "area_m2": 1000.0,
        "horizon_days": 30,
        "env": {
            "temp_internal": 20.0,
            "humidity_int":  75.0,
            "co2_ppm":       800.0,
            "solar_rad":     150.0,
            "ec_dsm":        2.5
        }
    }

Response:
    {
        "farm_id": "farm_001",
        "crop": "딸기",
        "model_source": "M2",
        "updated_at": "2026-05-15T14:00:00Z",
        "alerts": [...],
        "recommendations": [...]
    }
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from engine.farm_tier import FarmTier
from engine.profit_optimizer import optimize
from engine.what_if_simulator import EnvState
from api.services.anomaly_detector import detect_anomalies

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2", tags=["recommend-v2"])


# ── 요청/응답 스키마 ──────────────────────────────────────────────────────────

class EnvInput(BaseModel):
    temp_internal: Optional[float] = Field(None, description="내부 온도 (도C)")
    humidity_int:  Optional[float] = Field(None, description="내부 습도 (%)")
    co2_ppm:       Optional[float] = Field(None, description="CO2 농도 (ppm)")
    solar_rad:     Optional[float] = Field(None, description="일사량 (W/m2)")
    ec_dsm:        Optional[float] = Field(None, description="EC (dS/m)")
    soil_temp:     Optional[float] = Field(None, description="지온 (도C)")
    temp_external: Optional[float] = Field(None, description="외부 온도 (도C)")


class RecommendRequest(BaseModel):
    crop:         str   = Field(..., description="작물명 (한국어, 예: 딸기)")
    env:          EnvInput
    farm_id:      str   = Field("unknown", description="농가 ID (로깅용)")
    tier:         Literal["manual", "semi_auto", "auto"] = Field("semi_auto")
    area_m2:      float = Field(1000.0, gt=0, description="재배 면적 (m²)")
    horizon_days: int   = Field(30, ge=1, le=365, description="계획 기간 (일)")


class AlertOut(BaseModel):
    variable:    str
    variable_ko: str
    current_value: float
    normal_min:  float
    normal_max:  float
    unit:        str
    severity:    str
    message_ko:  str


class RecommendationOut(BaseModel):
    rank:          int
    action_ko:     str
    profit_delta:  float
    revenue_delta: float
    cost_delta:    float
    confidence:    float
    tier_action:   str
    canonical_changes: dict[str, float]


class RecommendResponse(BaseModel):
    farm_id:      str
    crop:         str
    model_source: str
    updated_at:   str
    alerts:       list[AlertOut]
    recommendations: list[RecommendationOut]


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

_TIER_MAP = {
    "manual":    FarmTier.MANUAL,
    "semi_auto": FarmTier.SEMI_AUTO,
    "auto":      FarmTier.AUTO,
}

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.post("/recommend", response_model=RecommendResponse, summary="수익 최적화 추천")
def recommend(body: RecommendRequest):
    """현재 환경값 → 수익 최적화 추천 + 이상 감지.

    - M2 실측 모델(conf 72%) 우선 사용
    - M2 비활성 시 FourStagePipeline 폴백
    - 환경값이 정상 범위 이탈 시 alerts 포함
    """
    env_dict = {k: v for k, v in body.env.model_dump().items() if v is not None}
    if not env_dict:
        return RecommendResponse(
            farm_id=body.farm_id, crop=body.crop,
            model_source="none", updated_at=_now_iso(),
            alerts=[], recommendations=[],
        )

    tier       = _TIER_MAP.get(body.tier, FarmTier.SEMI_AUTO)
    current_env = EnvState(farm_id=body.farm_id, values=env_dict)

    # 이상 감지
    raw_alerts = detect_anomalies(body.crop, env_dict)
    alerts = [
        AlertOut(
            variable=a.variable, variable_ko=a.variable_ko,
            current_value=a.current_value, normal_min=a.normal_min,
            normal_max=a.normal_max, unit=a.unit,
            severity=a.severity, message_ko=a.message_ko,
        )
        for a in raw_alerts
    ]

    # 수익 최적화
    recs = optimize(
        farm_id=body.farm_id,
        tier=tier,
        current_env=current_env,
        horizon_days=body.horizon_days,
        area_m2=body.area_m2,
        crop_ko=body.crop,
    )

    model_source = "M2" if (recs and abs(recs[0].confidence - 0.72) < 0.01) else "pipeline"

    items = [
        RecommendationOut(
            rank=r.rank, action_ko=r.action_ko,
            profit_delta=round(r.profit_delta, 0),
            revenue_delta=round(r.revenue_delta, 0),
            cost_delta=round(r.cost_delta, 0),
            confidence=round(r.confidence, 3),
            tier_action=r.tier_action,
            canonical_changes=r.canonical_changes,
        )
        for r in recs
    ]

    logger.info(
        "[v2/recommend] farm=%s crop=%s model=%s alerts=%d recs=%d",
        body.farm_id, body.crop, model_source, len(alerts), len(items),
    )

    return RecommendResponse(
        farm_id=body.farm_id, crop=body.crop,
        model_source=model_source, updated_at=_now_iso(),
        alerts=alerts, recommendations=items,
    )
