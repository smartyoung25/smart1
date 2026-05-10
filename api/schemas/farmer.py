from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from api.schemas.common import BaseResponse


class FarmAlert(BaseModel):
    """농가별 알림 항목"""
    id: str
    severity: str        # "danger" | "warning" | "info"
    variable: str        # 정규 변수명
    message_ko: str
    value: float
    threshold: float
    unit: str


class FarmSummary(BaseResponse):
    """GET /api/farms/{farm_id}/summary"""
    alert_count: int = 0
    alerts: list[FarmAlert] = []
    harvest_days_remaining: Optional[int] = None   # D-day from M3
    revenue_mtd_krw: float = 0.0                    # month-to-date ₩


class RecommendationItem(BaseModel):
    rank: int
    action_ko: str
    profit_delta: float          # ₩
    revenue_delta: float
    cost_delta: float
    confidence: float
    tier_action: str             # checklist | approval_required | auto
    canonical_changes: dict[str, float]


class RecommendationsResponse(BaseResponse):
    """GET /api/farms/{farm_id}/recommendations"""
    recommendations: list[RecommendationItem]


class ApplyRequest(BaseModel):
    rank: int
    confirmed: bool = False      # Tier 2 requires confirmed=True


class ApplyResponse(BaseModel):
    status: str                  # queued | sent | checklist_generated
    message_ko: str
    checklist_url: Optional[str] = None


class EnvPoint(BaseModel):
    canonical_name: str
    value: float
    unit: str
    quality_tag: str
    imputed: bool


class EnvironmentSection(BaseModel):
    """실내 또는 실외 환경 섹션"""
    source: str           # "iot" | "manual_input" | "asos" | "none"
    label_ko: str         # 사용자 노출용 레이블
    editable: bool = False  # True = IoT 미설치 → 수동 입력 가능
    has_data: bool = True
    measurements: list[EnvPoint] = []


class EnvironmentResponse(BaseResponse):
    """GET /api/farms/{farm_id}/environment"""
    iot_available: bool = True
    indoor: EnvironmentSection   # 실내 환경 (IoT 센서 or 수동 입력)
    outdoor: EnvironmentSection  # 외부 기상 (기상청 ASOS)
    # 하위 호환용 flat 목록 (기존 코드 영향 최소화)
    measurements: list[EnvPoint] = []


class HarvestForecast(BaseResponse):
    """GET /api/farms/{farm_id}/harvest"""
    predicted_date: Optional[str] = None    # ISO date string
    predicted_yield_kg_m2: Optional[float] = None
    confidence: float = 0.0


class RevenueResponse(BaseResponse):
    """GET /api/farms/{farm_id}/revenue"""
    kamis_price_krw_kg: float
    predicted_revenue_krw: float
    predicted_cost_krw: float
    predicted_profit_krw: float


class CostItem(BaseModel):
    """단일 비용 항목"""
    category: str          # electricity | water | heating | labor | nutrients | pesticides
    label_ko: str
    amount_krw: float      # 월 비용 (원)
    unit_label: str        # "180kWh/일 × 30일 × 105원/kWh"
    pct_of_total: float    # 전체 비용 중 비율 (0.0~1.0)
    is_manual: bool = False  # 실제 입력값 사용 여부


class ManualCostInput(BaseModel):
    """POST /api/farms/{farm_id}/costs/manual — 실제 비용 직접 입력"""
    # 전기: 사용량 + 단가 → 금액 자동 계산
    electricity_kwh_month: Optional[float] = Field(None, ge=0, le=100_000, description="월 전기 사용량 (kWh)")
    electricity_rate:      Optional[float] = Field(None, ge=0, le=1_000,   description="전기 단가 (원/kWh)")
    # 용수
    water_m3_month:        Optional[float] = Field(None, ge=0, le=10_000,  description="월 용수 사용량 (m³)")
    water_rate:            Optional[float] = Field(None, ge=0, le=10_000,  description="용수 단가 (원/m³)")
    # 난방
    heating_kwh_month:     Optional[float] = Field(None, ge=0, le=100_000, description="월 난방 에너지 (kWh)")
    heating_rate:          Optional[float] = Field(None, ge=0, le=1_000,   description="난방 단가 (원/kWh)")
    # 인건비
    labor_hours_month:     Optional[float] = Field(None, ge=0, le=1_000,   description="월 작업 시간 (시간)")
    labor_rate:            Optional[float] = Field(None, ge=0, le=100_000, description="시급 (원/시간)")
    # 직접 비용
    nutrients_krw_month:   Optional[float] = Field(None, ge=0, le=10_000_000, description="월 영양제·비료 비용 (원)")
    pesticides_krw_month:  Optional[float] = Field(None, ge=0, le=10_000_000, description="월 농약·방제 비용 (원)")


class ManualCostResponse(BaseModel):
    """POST /costs/manual 응답"""
    status: str
    message_ko: str
    stored_fields: list[str]


class CostBreakdownResponse(BaseResponse):
    """GET /api/farms/{farm_id}/costs"""
    items: list[CostItem]
    total_cost_krw: float
    cost_per_m2: float
    electricity_kwh_month: float
    water_m3_month: float
    has_manual_input: bool = False      # 실제값 입력 여부
    manual_input: Optional[ManualCostInput] = None  # 현재 저장된 실제값


class FarmMeta(BaseModel):
    """GET /api/farms/{farm_id}/meta"""
    farm_id: str
    name: str
    crop: str
    tier: str
    iot_available: bool
    area_m2: float
    # 주소 — ASOS 관측소 자동 매핑에 사용
    sido: Optional[str] = None       # 시도 (예: "전라북도")
    sigungu: Optional[str] = None    # 시군구 (예: "군산시")
    address_detail: Optional[str] = None  # 상세주소 (표시용)
    asos_station_id: Optional[int] = None  # 매핑된 ASOS 관측소 ID


class FarmMetaUpdate(BaseModel):
    """PUT /api/farms/{farm_id}/meta — 농장 기본 정보 수정"""
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    crop: Optional[str] = Field(None, min_length=1, max_length=50)
    area_m2: Optional[float] = Field(None, gt=0, le=100_000)
    sido: Optional[str] = Field(None, max_length=20)
    sigungu: Optional[str] = Field(None, max_length=20)
    address_detail: Optional[str] = Field(None, max_length=100)


class ManualEnvInput(BaseModel):
    """POST /api/farms/{farm_id}/environment/manual — 수동 환경값 입력"""
    temp_internal: Optional[float] = Field(None, ge=0,   le=50,   description="내부 온도 (°C)")
    humidity_int:  Optional[float] = Field(None, ge=20,  le=100,  description="내부 습도 (%)")
    co2_ppm:       Optional[float] = Field(None, ge=300, le=2000, description="CO₂ 농도 (ppm)")
    solar_rad:     Optional[float] = Field(None, ge=0,   le=1200, description="일사량 (W/m²)")
    ec_dsm:        Optional[float] = Field(None, ge=0.5, le=5.0,  description="EC (dS/m)")
    soil_temp:     Optional[float] = Field(None, ge=5,   le=35,   description="지온 (°C)")


class ManualEnvResponse(BaseModel):
    """POST /environment/manual 응답"""
    status: str
    message_ko: str
    stored_fields: list[str]


# ---------------------------------------------------------------------------
# AI 상담 (Chat)
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    """단일 대화 메시지"""
    role: str          # "user" | "assistant"
    content: str
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    """POST /api/farms/{farm_id}/chat"""
    message: str = Field(..., min_length=1, max_length=1000)
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """POST /api/farms/{farm_id}/chat 응답"""
    reply: str
    # 후속 질문 칩 — AI가 다음에 할 만한 질문 제안
    suggestions: list[str] = []
    # 어떤 농장 데이터를 참조했는지 (UI 뱃지용)
    referenced_data: list[str] = []
    # 나중에 실제 AI 연결 시 사용할 메타
    model_used: str = "stub-v1"   # e.g. "gpt-4o", "claude-3-5-sonnet"
    confidence: Optional[float] = None
