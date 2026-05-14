from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class AdminOverview(BaseModel):
    """GET /api/admin/overview"""
    connected_farms: int
    iot_farms: int                   # IoT 구축 농가 수
    avg_model_r2: float
    models_loaded: int               # pkl 로드 성공 모델 수
    data_completeness_pct: float
    income_improvement_pct: float
    updated_at: datetime


class CropModelInfo(BaseModel):
    """작목별 ML 모델 상세 정보 (4-Stage 파이프라인 기반)"""
    crop_ko: str
    crop_en: str
    status: str                      # "loaded" | "no_model"
    model_type: Optional[str] = None # "4stage" | "xgb_lgb_ensemble" | "ridge_fallback"
    # 레거시 단일 모델 메트릭 (하위 호환)
    train_r2: Optional[float] = None
    train_mape: Optional[float] = None
    test_r2: Optional[float] = None
    test_mape: Optional[float] = None
    feature_count: Optional[int] = None
    n_train: Optional[int] = None
    n_test: Optional[int] = None
    # 4-Stage 파이프라인 메트릭
    stage1_cv_r2: Optional[float] = None      # 환경→생육 CV R²
    stage1_gate: Optional[bool] = None        # Stage1 게이트 통과 여부
    stage2_mape: Optional[float] = None       # 생육→수확량 MAPE %
    stage2_cv_r2: Optional[float] = None      # Stage2 CV R²
    stage2_gate: Optional[bool] = None        # Stage2 게이트 통과 여부
    stage2_n_train: Optional[int] = None      # Stage2 학습 샘플 수
    stage2_area_from_registry: Optional[int] = None  # 실측 면적 적용 농가 수
    stage3_mape: Optional[float] = None       # 수확량→매출 MAPE %
    stage3_gate: Optional[bool] = None        # Stage3 게이트 통과 여부
    price_median_krw_kg: Optional[float] = None  # Stage3 사용 단가
    # 최적화 파라미터
    opt_temp: Optional[float] = None   # 최적 온도
    opt_humid: Optional[float] = None  # 최적 습도
    opt_co2: Optional[float] = None    # 최적 CO₂
    income_6m_krw: Optional[float] = None  # 최적 환경 6개월 소득


class CropModelsResponse(BaseModel):
    """GET /api/admin/models/crops"""
    crops: list[CropModelInfo]
    updated_at: datetime


class ModelStatus(BaseModel):
    module_id: str          # M1 ~ M7
    metric_name: str        # R² | MAPE | F1
    metric_value: float
    threshold: float
    passed: bool
    last_trained: Optional[datetime] = None


class ModelOverview(BaseModel):
    """GET /api/admin/models"""
    models: list[ModelStatus]
    updated_at: datetime


class DataSourceStatus(BaseModel):
    source_id: str
    label_ko: str
    connected: bool
    last_sync: Optional[datetime] = None
    completeness_pct: float


class DataSourcesResponse(BaseModel):
    """GET /api/admin/data-sources"""
    sources: list[DataSourceStatus]
    updated_at: datetime


class VariableMapping(BaseModel):
    canonical_name: str
    display_name_ko: str
    unit: str
    impute_strategy: str
    sources: list[dict]     # [{source_id, source_field, transform_expr}]


class VariableRegistryResponse(BaseModel):
    """GET /api/admin/variable-registry"""
    variables: list[VariableMapping]


class PipelineRun(BaseModel):
    run_id: str
    trigger: str            # scheduled | manual | threshold
    started_at: datetime
    duration_seconds: Optional[int] = None
    status: str             # running | success | failed
    metrics_before: Optional[dict] = None
    metrics_after: Optional[dict] = None
    deployed: Optional[bool] = None


class PipelineRunsResponse(BaseModel):
    """GET /api/admin/pipeline/runs"""
    runs: list[PipelineRun]


class TriggerRequest(BaseModel):
    reason: Optional[str] = None


class TriggerResponse(BaseModel):
    run_id: str
    status: str
    message: str
