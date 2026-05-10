"""Platform admin API routes."""
from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter

from api.schemas.admin import (
    AdminOverview,
    ModelStatus,
    ModelOverview,
    DataSourceStatus,
    DataSourcesResponse,
    VariableMapping,
    VariableRegistryResponse,
    PipelineRun,
    PipelineRunsResponse,
    TriggerRequest,
    TriggerResponse,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


@router.get("/overview", response_model=AdminOverview)
def get_overview():
    return AdminOverview(
        connected_farms=5,
        avg_model_r2=0.71,
        data_completeness_pct=88.5,
        income_improvement_pct=14.2,
        updated_at=_now(),
    )


@router.get("/models", response_model=ModelOverview)
def get_models():
    models = [
        ModelStatus(module_id="M1", metric_name="R²",   metric_value=0.73, threshold=0.62, passed=True),
        ModelStatus(module_id="M2", metric_name="MAPE", metric_value=18.4, threshold=25.0, passed=True),
        ModelStatus(module_id="M3", metric_name="days", metric_value=3.2,  threshold=5.0,  passed=True),
        ModelStatus(module_id="M4", metric_name="error%", metric_value=16.1, threshold=20.0, passed=True),
        ModelStatus(module_id="M5", metric_name="F1",   metric_value=0.85, threshold=0.88, passed=False),
    ]
    return ModelOverview(models=models, updated_at=_now())


@router.get("/data-sources", response_model=DataSourcesResponse)
def get_data_sources():
    sources = [
        DataSourceStatus(source_id="iot_sensor",  label_ko="IoT 센서",      connected=True,  last_sync=_now(), completeness_pct=94.0),
        DataSourceStatus(source_id="rda_api",     label_ko="농진청 API",    connected=True,  last_sync=_now(), completeness_pct=80.0),
        DataSourceStatus(source_id="kamis",       label_ko="KAMIS 가격",    connected=True,  last_sync=_now(), completeness_pct=100.0),
        DataSourceStatus(source_id="wur_dataset", label_ko="WUR 데이터셋",  connected=False, last_sync=None,   completeness_pct=0.0),
        DataSourceStatus(source_id="manual",      label_ko="농가 수동입력", connected=True,  last_sync=_now(), completeness_pct=60.0),
    ]
    return DataSourcesResponse(sources=sources, updated_at=_now())


@router.get("/variable-registry", response_model=VariableRegistryResponse)
def get_variable_registry():
    variables = [
        VariableMapping(
            canonical_name="temp_internal",
            display_name_ko="내부 온도",
            unit="°C",
            impute_strategy="locf",
            sources=[
                {"source_id": "iot_sensor",  "source_field": "온도_내부",  "transform_expr": None},
                {"source_id": "rda_api",     "source_field": "내부온도",   "transform_expr": None},
                {"source_id": "wur_dataset", "source_field": "T_air",     "transform_expr": None},
            ],
        ),
        VariableMapping(
            canonical_name="ec_dsm",
            display_name_ko="EC",
            unit="dS/m",
            impute_strategy="knn",
            sources=[
                {"source_id": "iot_sensor",  "source_field": "EC",          "transform_expr": "value * 0.1"},
                {"source_id": "wur_dataset", "source_field": "EC_solution", "transform_expr": None},
            ],
        ),
        VariableMapping(
            canonical_name="co2_ppm",
            display_name_ko="CO₂ 농도",
            unit="ppm",
            impute_strategy="knn",
            sources=[
                {"source_id": "iot_sensor",  "source_field": "잔존CO2",    "transform_expr": None},
                {"source_id": "wur_dataset", "source_field": "CO2_conc",   "transform_expr": None},
            ],
        ),
    ]
    return VariableRegistryResponse(variables=variables)


@router.get("/pipeline/runs", response_model=PipelineRunsResponse)
def get_pipeline_runs():
    runs = [
        PipelineRun(
            run_id="run_001",
            trigger="scheduled",
            started_at=_now(),
            duration_seconds=312,
            status="success",
            metrics_before={"M1_r2": 0.70},
            metrics_after={"M1_r2": 0.73},
            deployed=True,
        ),
        PipelineRun(
            run_id="run_002",
            trigger="manual",
            started_at=_now(),
            duration_seconds=None,
            status="running",
            deployed=None,
        ),
    ]
    return PipelineRunsResponse(runs=runs)


@router.post("/pipeline/trigger", response_model=TriggerResponse)
def trigger_pipeline(body: TriggerRequest):
    run_id = f"run_{uuid4().hex[:8]}"
    return TriggerResponse(
        run_id=run_id,
        status="queued",
        message=f"Pipeline queued (run_id={run_id}). Reason: {body.reason or 'manual trigger'}",
    )
