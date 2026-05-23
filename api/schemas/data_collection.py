"""데이터 수집 API 스키마.

농가·스마트팜에서 실측한 생육 측정값(주간)과 수확량(시즌 말)을 수신하는 엔드포인트용.
수집된 데이터는 ML 모델 재학습 파이프라인의 학습 원료로 사용됩니다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── 주간 생육 측정값 ─────────────────────────────────────────────────────────

class GrowthRecord(BaseModel):
    """POST /api/data/growth — 주간 생육 측정값 수신."""
    farm_id: str = Field(..., min_length=1, max_length=50, description="농장 ID")
    crop_ko: str = Field(..., min_length=1, max_length=50, description="작목 (예: 딸기, 방울토마토)")
    recorded_date: date = Field(..., description="측정 날짜 (YYYY-MM-DD)")

    # ── 환경값 (IoT 또는 수동 입력) ───────────────────────────────────────────
    temp_internal:  Optional[float] = Field(None, ge=0,   le=50,   description="내부 온도 (°C)")
    humidity_int:   Optional[float] = Field(None, ge=20,  le=100,  description="내부 습도 (%)")
    co2_ppm:        Optional[float] = Field(None, ge=300, le=2000, description="CO₂ 농도 (ppm)")
    solar_rad:      Optional[float] = Field(None, ge=0,   le=1200, description="일사량 (W/m²)")
    ec_dsm:         Optional[float] = Field(None, ge=0.5, le=5.0,  description="EC (dS/m)")
    soil_temp:      Optional[float] = Field(None, ge=5,   le=35,   description="지온 (°C)")
    vpd_kpa:        Optional[float] = Field(None, ge=0,   le=5,    description="VPD (kPa) — 미입력 시 온습도에서 자동 계산")

    # ── 생육 측정값 (선택) ─────────────────────────────────────────────────────
    plant_height_cm:  Optional[float] = Field(None, ge=0, le=500,  description="초장 (cm)")
    leaf_count:       Optional[int]   = Field(None, ge=0, le=200,  description="엽수")
    fruit_count:      Optional[int]   = Field(None, ge=0, le=500,  description="착과수")
    stem_diameter_mm: Optional[float] = Field(None, ge=0, le=100,  description="줄기직경 (mm)")
    chlorophyll_spad: Optional[float] = Field(None, ge=0, le=100,  description="엽록소 SPAD")

    source: str = Field("api", description="데이터 출처 ('api' | 'iot_auto' | 'manual')")
    notes: Optional[str] = Field(None, max_length=500, description="비고")


class GrowthRecordResponse(BaseModel):
    """POST /api/data/growth 응답."""
    status: str                    # "stored" | "stored_db" | "error"
    message_ko: str
    record_id: Optional[str] = None
    total_count: int = 0           # 해당 농장·작목 누적 수신 건수
    retrain_triggered: bool = False


# ── 수확량 실측값 ─────────────────────────────────────────────────────────────

class HarvestRecord(BaseModel):
    """POST /api/data/harvest — 시즌 수확량 실측값 수신."""
    farm_id: str = Field(..., min_length=1, max_length=50)
    crop_ko: str = Field(..., min_length=1, max_length=50)
    harvest_date: date = Field(..., description="수확 날짜 (YYYY-MM-DD)")

    yield_kg_m2:  float = Field(..., ge=0, le=100,       description="수확량 (kg/m²) — 필수")
    area_m2:      Optional[float] = Field(None, ge=1, le=100_000, description="재배 면적 (m²)")
    total_yield_kg: Optional[float] = Field(None, ge=0,          description="총 수확량 (kg) — 미입력 시 yield_kg_m2 × area_m2 자동 계산")

    # ── 재배 이력 (선택) ───────────────────────────────────────────────────────
    planting_date:  Optional[date]  = Field(None, description="정식일")
    growing_days:   Optional[int]   = Field(None, ge=1, le=400, description="재배 일수")
    season_avg_temp: Optional[float] = Field(None, ge=0, le=40, description="시즌 평균 온도 (°C)")
    season_avg_humidity: Optional[float] = Field(None, ge=0, le=100, description="시즌 평균 습도 (%)")

    source: str = Field("api", description="데이터 출처")
    notes: Optional[str] = Field(None, max_length=500)


class HarvestRecordResponse(BaseModel):
    """POST /api/data/harvest 응답."""
    status: str
    message_ko: str
    record_id: Optional[str] = None
    total_count: int = 0
    retrain_triggered: bool = False
    retrain_message_ko: str = ""


# ── 수집 현황 조회 ─────────────────────────────────────────────────────────────

class DataCountItem(BaseModel):
    crop_ko: str
    growth_count: int
    harvest_count: int
    last_growth_at: Optional[str] = None
    last_harvest_at: Optional[str] = None
    retrain_status: str = "대기"    # "대기" | "재학습 중" | "완료"


class DataStatusResponse(BaseModel):
    """GET /api/data/status — 수집 현황."""
    farm_id: Optional[str] = None   # None = 전체 집계
    items: list[DataCountItem]
    total_growth: int
    total_harvest: int
    retrain_threshold_growth: int = 30
    retrain_threshold_harvest: int = 10
