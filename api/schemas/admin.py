from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class AdminOverview(BaseModel):
    """GET /api/admin/overview"""
    connected_farms: int
    avg_model_r2: float
    data_completeness_pct: float
    income_improvement_pct: float
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
