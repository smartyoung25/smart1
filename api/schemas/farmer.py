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
    # UI 편의용 flat 필드 (loadCurrentEnv JS에서 d.temp_internal 등으로 직접 접근)
    temp_internal:  Optional[float] = None
    humidity_int:   Optional[float] = None
    co2_ppm:        Optional[float] = None
    solar_rad:      Optional[float] = None
    ec_dsm:         Optional[float] = None
    soil_temp:      Optional[float] = None
    ph:             Optional[float] = None
    timestamp:      Optional[str]   = None
    # 이상 감지 결과 (loadEnvAnomalies JS에서 d.alerts 접근)
    alerts: list[dict] = []
    # 제어 모드 및 Fail-safe (env-mode-active, env-failsafe-pill pill 업데이트용)
    control_mode:    Optional[str]  = None  # manual|advisory|approval|full_auto
    failsafe_status: Optional[str]  = None  # "ok" | "error" | None


class HarvestForecast(BaseResponse):
    """GET /api/farms/{farm_id}/harvest"""
    predicted_date: Optional[str] = None    # ISO date string
    predicted_yield_kg_m2: Optional[float] = None
    confidence: float = 0.0
    # UI 편의 필드 (대시보드 JS가 직접 접근)
    yield_kg_forecast: Optional[float] = None   # = predicted_yield_kg_m2 × area_m2
    yield_q10: Optional[float] = None            # 80% 신뢰구간 하한 (−20%)
    yield_q90: Optional[float] = None            # 80% 신뢰구간 상한 (+20%)
    days_to_harvest: Optional[int] = None
    crop_ko: Optional[str] = None
    area_m2: Optional[float] = None
    growth_stage_ko: Optional[str] = None       # 한국어 생육단계 (초기|생육중|착과기|수확기)
    days_since_planting: Optional[int] = None   # 정식 후 경과일
    # Phase 42: 모델 신뢰도 등급 (농가 화면 표시용)
    confidence_grade: str = "낮음 (참고용)"     # "높음" | "보통" | "낮음 (참고용)"
    model_mape_pct: Optional[float] = None      # 학습 MAPE (%)
    mape_note: str = ""                          # 오차 설명 메시지
    # Phase 45+: M2 게이트 통과 여부 + 신뢰도 (수확 카드 표시용)
    model_gate_pass: Optional[bool] = None       # M2 gate_passed (True/False)
    model_confidence: Optional[float] = None     # 1 - MAPE/100 (0~0.95)


class RevenueResponse(BaseResponse):
    """GET /api/farms/{farm_id}/revenue"""
    kamis_price_krw_kg: float
    predicted_revenue_krw: float
    predicted_cost_krw: float
    predicted_profit_krw: float
    # UI 편의 별칭 (대시보드 JS가 price_krw_kg, revenue_krw, cost_krw 등으로 접근)
    price_krw_kg: float = 0.0
    revenue_krw: float = 0.0
    cost_krw: float = 0.0
    price_source: str = "stats_avg"    # "kamis_live" | "stats_avg"
    crop_ko: Optional[str] = None
    # 소득 예측 상세 (대시보드 소득 카드용)
    yield_kg_forecast: Optional[float] = None   # M2 수확량 예측 (전체 kg)
    yield_kg_m2: Optional[float] = None          # M2 수확량 예측 (kg/m²)
    model_confidence: float = 0.5                # M2 신뢰도 (0~1, MAPE 기반)
    model_gate_pass: Optional[bool] = None       # M2 게이트 통과 여부
    revenue_source: str = "stats_fallback"       # "ml_model" | "stats_fallback"
    area_m2: Optional[float] = None              # 재배 면적
    profit_margin_pct: Optional[float] = None    # 이익률 (%)


class CostItem(BaseModel):
    """단일 비용 항목"""
    category: str          # electricity | water | heating | labor | nutrients | pesticides
    label_ko: str
    label: str = ""        # UI 별칭 (label_ko 와 동일값 — JS가 it.label 로 접근)
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
    # UI 별칭 (대시보드 JS가 d.total_krw 로 접근)
    total_krw: float = 0.0


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
    ph:            Optional[float] = Field(None, ge=4.0, le=8.5,  description="pH")


class ManualEnvResponse(BaseModel):
    """POST /environment/manual 응답"""
    status: str
    message_ko: str
    stored_fields: list[str]


# ---------------------------------------------------------------------------
# AI 상담 (Chat)
# ---------------------------------------------------------------------------

class WhatIfInput(BaseModel):
    """POST /api/farms/{farm_id}/whatif — 가상 환경값으로 수익 예측"""
    temp_internal: Optional[float] = Field(None, ge=0,   le=50)
    humidity_int:  Optional[float] = Field(None, ge=20,  le=100)
    co2_ppm:       Optional[float] = Field(None, ge=300, le=2000)
    solar_rad:     Optional[float] = Field(None, ge=0,   le=1200)
    ec_dsm:        Optional[float] = Field(None, ge=0.5, le=5.0)
    soil_temp:     Optional[float] = Field(None, ge=5,   le=35)


class WhatIfResult(BaseModel):
    """POST /whatif 응답"""
    baseline_revenue_krw: float      # 현재 환경 기준 예측 매출
    whatif_revenue_krw: float        # 가상 환경 기준 예측 매출
    delta_krw: float                 # 차이 (양수=증가)
    delta_pct: float                 # 증감률 (%)
    confidence: float                # 모델 신뢰도 0–1
    model_used: str                  # "ml_model" | "stats_fallback"
    # ── 비용·소득 (2026-07-17 추가) ──────────────────────────────────────────
    # ★ 구: profit_gain_krw 에 '매출' 델타를 넣어 UI 가 소득으로 오독했다.
    #   온도를 올리면 매출과 난방비가 함께 오르므로, 비용을 빼지 않으면
    #   "무조건 온도를 올려라"가 된다. 이제 profit_gain_krw 는 진짜 소득 델타다.
    baseline_cost_krw: Optional[float] = None   # 현재 환경 기준 예측 비용
    whatif_cost_krw: Optional[float] = None     # 가상 환경 기준 예측 비용
    cost_delta_krw: Optional[float] = None      # 비용 차이 (양수=증가)
    profit_delta_krw: Optional[float] = None    # 소득 차이 = 매출Δ − 비용Δ. 비용 미산출 시 None
    # UI 편의 별칭 (대시보드 JS가 profit_gain_krw, revenue_krw 등으로 접근)
    profit_gain_krw: float = 0.0     # = profit_delta_krw (비용 미산출 시 0)
    revenue_gain_krw: float = 0.0    # = delta_krw (매출 델타 — legacy)
    revenue_krw: float = 0.0         # = whatif_revenue_krw
    yield_kg_forecast: Optional[float] = None


class WhatIfScenario(BaseModel):
    """다중 What-if 시나리오 중 하나."""
    label: str = Field(..., description="시나리오 이름 (예: '고온 설정', '최적 CO₂')")
    temp_internal: Optional[float] = Field(None, ge=0,   le=50)
    humidity_int:  Optional[float] = Field(None, ge=20,  le=100)
    co2_ppm:       Optional[float] = Field(None, ge=300, le=2000)
    solar_rad:     Optional[float] = Field(None, ge=0,   le=1200)
    ec_dsm:        Optional[float] = Field(None, ge=0.5, le=5.0)
    soil_temp:     Optional[float] = Field(None, ge=5,   le=35)


class WhatIfMultiInput(BaseModel):
    """POST /whatif/multi — 여러 시나리오를 한 번에 비교."""
    scenarios: list[WhatIfScenario] = Field(..., min_length=1, max_length=10)


class WhatIfScenarioResult(BaseModel):
    """WhatIfMultiResult 내 단일 시나리오 결과."""
    label: str
    whatif_revenue_krw: float
    delta_krw: float
    delta_pct: float
    confidence: float
    model_used: str
    rank: int            # 수익 기준 순위 (1=최고)


class WhatIfMultiResult(BaseModel):
    """POST /whatif/multi 응답."""
    farm_id: str
    baseline_revenue_krw: float
    scenarios: list[WhatIfScenarioResult]
    best_label: str           # 가장 수익이 높은 시나리오 이름
    best_delta_krw: float


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
    # 답변에 실제로 사용된 문헌 근거 — [{title, cite, id}]
    #   referenced_data 와 별개 축이다(그쪽=농장 데이터, 이쪽=교재·제품 규칙 출처).
    #   검색 결과가 없으면 빈 리스트 — 화면은 없는 출처를 표기해선 안 된다.
    sources: list[dict] = []
    # 나중에 실제 AI 연결 시 사용할 메타
    model_used: str = "stub-v1"   # e.g. "gpt-4o", "claude-3-5-sonnet"
    confidence: Optional[float] = None


class DiseaseRiskResponse(BaseModel):
    """GET /api/farms/{farm_id}/disease-risk 응답"""
    farm_id: str
    updated_at: str
    crop: str
    disease: str                   # "healthy" | "gray_mold" | "powdery_mildew" | ...
    disease_ko: str
    risk_level: str                # "none" | "low" | "medium" | "high"
    score: float                   # 0.0 ~ 1.0
    reasons: list[str]             # 위험 판단 근거 문구
    action_ko: str                 # 권장 조치
    env_snapshot: dict             # 판단에 사용된 환경값

