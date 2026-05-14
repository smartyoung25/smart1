"""Platform admin API routes — 실데이터 연결."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter

from api.schemas.admin import (
    AdminOverview,
    CropModelInfo,
    CropModelsResponse,
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

ARTIFACTS_DIR = Path(__file__).parent.parent.parent / "models" / "artifacts"

# 작목별 파이프라인 메타 JSON 경로
_CROP_META_FILES = {
    "딸기":       "strawberry_pipeline_meta.json",
    "방울토마토": "cherry_tomato_pipeline_meta.json",
    "완숙토마토": "tomato_pipeline_meta.json",
    "참외":       "melon_pipeline_meta.json",
    "파프리카":   "paprika_pipeline_meta.json",
}
_CROP_EN = {
    "딸기":       "strawberry",
    "방울토마토": "cherry_tomato",
    "완숙토마토": "tomato",
    "참외":       "melon",
    "파프리카":   "paprika",
    "오이":       "cucumber",
}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _load_all_meta() -> dict[str, dict]:
    """artifacts/*.json 파일을 작목명 키로 로드."""
    result: dict[str, dict] = {}
    for crop_ko, fname in _CROP_META_FILES.items():
        p = ARTIFACTS_DIR / fname
        if p.exists():
            try:
                result[crop_ko] = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("[admin] %s 로드 실패: %s", fname, e)
    return result


# ---------------------------------------------------------------------------
# GET /overview
# ---------------------------------------------------------------------------

@router.get("/overview", response_model=AdminOverview)
def get_overview():
    from api.routers.farmer import _FARM_META
    from api.services.model_loader import get_model_meta, CROP_EN

    n_farms   = len(_FARM_META)
    iot_farms = sum(1 for m in _FARM_META.values() if m["iot_available"])

    # 작목별 모델 R² 수집
    r2_list: list[float] = []
    loaded  = 0
    for crop_ko in CROP_EN:
        meta = get_model_meta(crop_ko)
        if meta.get("status") == "loaded":
            loaded += 1
            if meta.get("train_r2") is not None:
                r2_list.append(meta["train_r2"])

    avg_r2 = round(sum(r2_list) / len(r2_list), 3) if r2_list else 0.0

    # 소득 마진율: (최적 월수익 - 월비용) / 최적 월수익 × 100 (딸기 기준)
    all_meta = _load_all_meta()
    income_pct = 0.0
    straw = all_meta.get("딸기", {})
    if straw:
        opt  = straw.get("optimization_sample", {})
        rev  = opt.get("monthly_revenue", 0)
        inc  = opt.get("monthly_income", 0)
        if rev and rev > 0:
            income_pct = round(inc / rev * 100, 1)

    return AdminOverview(
        connected_farms=n_farms,
        iot_farms=iot_farms,
        avg_model_r2=avg_r2,
        models_loaded=loaded,
        data_completeness_pct=round(iot_farms / n_farms * 100, 1),
        income_improvement_pct=max(0.0, income_pct),
        updated_at=_now(),
    )


# ---------------------------------------------------------------------------
# GET /models  (기존 ModelStatus 형식 — 하위 호환)
# ---------------------------------------------------------------------------

@router.get("/models", response_model=ModelOverview)
def get_models():
    """R²·MAPE 기준 통과 여부 — 전체 작목 앙상블 요약."""
    all_meta  = _load_all_meta()
    r2_vals   = [m["train_metrics"]["r2"]  for m in all_meta.values() if "train_metrics" in m]
    mape_vals = [m["train_metrics"]["mape"] for m in all_meta.values() if "train_metrics" in m]

    avg_r2   = sum(r2_vals)   / len(r2_vals)   if r2_vals   else 0.0
    avg_mape = sum(mape_vals) / len(mape_vals) if mape_vals else 0.0

    models = [
        ModelStatus(module_id="Ensemble-R²",   metric_name="훈련 R²",
                    metric_value=round(avg_r2, 3),   threshold=0.90, passed=avg_r2 >= 0.90),
        ModelStatus(module_id="Ensemble-MAPE",  metric_name="훈련 MAPE %",
                    metric_value=round(avg_mape, 1), threshold=100.0, passed=avg_mape <= 100.0),
    ]
    # 작목별 행 추가
    for crop_ko, meta in all_meta.items():
        tr = meta.get("train_metrics", {})
        r2 = tr.get("r2", 0)
        models.append(ModelStatus(
            module_id=crop_ko,
            metric_name="R²",
            metric_value=round(r2, 3),
            threshold=0.90,
            passed=r2 >= 0.90,
            last_trained=_now(),
        ))
    return ModelOverview(models=models, updated_at=_now())


# ---------------------------------------------------------------------------
# GET /models/crops  (신규 — 작목별 상세)
# ---------------------------------------------------------------------------

@router.get("/models/crops", response_model=CropModelsResponse)
def get_crop_models():
    """작목별 ML 모델 상세 지표 (실 JSON 메타 기반)."""
    all_meta = _load_all_meta()
    crops: list[CropModelInfo] = []

    for crop_ko, crop_en in _CROP_EN.items():
        meta = all_meta.get(crop_ko)
        if meta is None:
            crops.append(CropModelInfo(crop_ko=crop_ko, crop_en=crop_en, status="no_model"))
            continue

        tr  = meta.get("train_metrics", {})
        te  = meta.get("test_metrics",  {})
        opt = meta.get("optimization_sample", {})
        top = meta.get("top5_env_combinations", [])
        best = top[0] if top else {}

        crops.append(CropModelInfo(
            crop_ko=crop_ko,
            crop_en=crop_en,
            status="loaded",
            model_type=meta.get("model_type"),
            train_r2=round(tr.get("r2", 0), 3),
            train_mape=round(tr.get("mape", 0), 1),
            test_r2=round(te.get("r2", 0), 3) if te.get("r2") is not None else None,
            test_mape=round(te.get("mape_pct", 0), 1) if te.get("mape_pct") is not None else None,
            feature_count=meta.get("feature_count"),
            n_train=meta.get("n_train"),
            n_test=te.get("n_test"),
            opt_temp=best.get("temp"),
            opt_humid=best.get("humid"),
            opt_co2=best.get("co2"),
            income_6m_krw=opt.get("total_income_6m"),
        ))

    return CropModelsResponse(crops=crops, updated_at=_now())


# ---------------------------------------------------------------------------
# GET /data-sources
# ---------------------------------------------------------------------------

@router.get("/data-sources", response_model=DataSourcesResponse)
def get_data_sources():
    from api.routers.farmer import _FARM_META
    from api.services import persistence
    from api.data.stats_loader import get_price_krw_kg

    # IoT 센서: IoT 구축 농가 비율
    iot_farms = sum(1 for m in _FARM_META.values() if m["iot_available"])
    iot_pct   = round(iot_farms / len(_FARM_META) * 100)

    # KAMIS: 실제 단가 조회 성공 여부
    try:
        get_price_krw_kg("딸기")
        kamis_ok = True
    except Exception:
        kamis_ok = False

    # 수동 입력: 입력값 있는 농가 수
    manual_count = sum(
        1 for fid in _FARM_META
        if persistence.get_manual_env(fid) or persistence.get_manual_cost(fid)
    )
    manual_pct = round(manual_count / len(_FARM_META) * 100)

    # 학습 데이터: 로드된 JSON 메타 수
    meta_count = sum(1 for f in ARTIFACTS_DIR.glob("*_pipeline_meta.json"))
    rda_pct    = round(meta_count / len(_CROP_META_FILES) * 100)

    sources = [
        DataSourceStatus(source_id="iot_sensor",  label_ko="IoT 센서",
                         connected=iot_farms > 0, last_sync=_now(), completeness_pct=float(iot_pct)),
        DataSourceStatus(source_id="rda_api",     label_ko="농진청 패널 데이터 (2018~2022)",
                         connected=meta_count > 0, last_sync=_now(), completeness_pct=float(rda_pct)),
        DataSourceStatus(source_id="kamis",       label_ko="KAMIS 가격 (stats_loader)",
                         connected=kamis_ok, last_sync=_now(), completeness_pct=100.0 if kamis_ok else 0.0),
        DataSourceStatus(source_id="kma_asos",    label_ko="기상청 ASOS",
                         connected=False, last_sync=None, completeness_pct=0.0),
        DataSourceStatus(source_id="manual",      label_ko="농가 수동 입력",
                         connected=True, last_sync=_now(), completeness_pct=float(manual_pct)),
    ]
    return DataSourcesResponse(sources=sources, updated_at=_now())


# ---------------------------------------------------------------------------
# GET /variable-registry
# ---------------------------------------------------------------------------

@router.get("/variable-registry", response_model=VariableRegistryResponse)
def get_variable_registry():
    variables = [
        VariableMapping(canonical_name="temp_internal",  display_name_ko="내부 온도",   unit="°C",    impute_strategy="locf",
                        sources=[{"source_id": "iot_sensor", "source_field": "온도_내부"}, {"source_id": "rda_api", "source_field": "내부온도"}]),
        VariableMapping(canonical_name="humidity_int",   display_name_ko="내부 습도",   unit="%",     impute_strategy="locf",
                        sources=[{"source_id": "iot_sensor", "source_field": "습도_내부"}, {"source_id": "rda_api", "source_field": "내부습도"}]),
        VariableMapping(canonical_name="co2_ppm",        display_name_ko="CO₂ 농도",   unit="ppm",   impute_strategy="knn",
                        sources=[{"source_id": "iot_sensor", "source_field": "잔존CO2"}]),
        VariableMapping(canonical_name="solar_rad",      display_name_ko="일사량",      unit="W/m²",  impute_strategy="knn",
                        sources=[{"source_id": "iot_sensor", "source_field": "누적일사"}, {"source_id": "kma_asos", "source_field": "hr1MaxIcsr"}]),
        VariableMapping(canonical_name="ec_dsm",         display_name_ko="EC (양액)",   unit="dS/m",  impute_strategy="knn",
                        sources=[{"source_id": "iot_sensor", "source_field": "EC", "transform_expr": "value×0.1"}]),
        VariableMapping(canonical_name="soil_temp",      display_name_ko="지온",        unit="°C",    impute_strategy="locf",
                        sources=[{"source_id": "iot_sensor", "source_field": "지온"}, {"source_id": "kma_asos", "source_field": "ts"}]),
        VariableMapping(canonical_name="revenue_per_m2", display_name_ko="매출/m²",    unit="원/m²", impute_strategy="none",
                        sources=[{"source_id": "rda_api", "source_field": "소득_m2"}]),
        VariableMapping(canonical_name="kamis_price",    display_name_ko="KAMIS 단가",  unit="원/kg", impute_strategy="locf",
                        sources=[{"source_id": "kamis", "source_field": "평균가격"}]),
    ]
    return VariableRegistryResponse(variables=variables)


# ---------------------------------------------------------------------------
# GET /pipeline/runs  (실 JSON 메타 기반)
# ---------------------------------------------------------------------------

@router.get("/pipeline/runs", response_model=PipelineRunsResponse)
def get_pipeline_runs():
    all_meta = _load_all_meta()
    runs: list[PipelineRun] = []

    for crop_ko, meta in all_meta.items():
        tr = meta.get("train_metrics", {})
        te = meta.get("test_metrics",  {})
        runs.append(PipelineRun(
            run_id=f"{_CROP_EN.get(crop_ko, crop_ko)}_v{meta.get('pipeline_version', '1.0')}",
            trigger="scripted",
            started_at=_now(),
            duration_seconds=None,
            status="success",
            metrics_before=None,
            metrics_after={
                "train_r2":   round(tr.get("r2", 0), 3),
                "train_mape": round(tr.get("mape", 0), 1),
                "test_r2":    round(te.get("r2", 0), 3) if te else None,
                "n_train":    meta.get("n_train"),
                "n_test":     te.get("n_test") if te else None,
            },
            deployed=True,
        ))

    return PipelineRunsResponse(runs=runs)


# ---------------------------------------------------------------------------
# POST /pipeline/trigger
# ---------------------------------------------------------------------------

@router.post("/pipeline/trigger", response_model=TriggerResponse)
def trigger_pipeline(body: TriggerRequest):
    run_id = f"run_{uuid4().hex[:8]}"
    return TriggerResponse(
        run_id=run_id,
        status="queued",
        message=f"재학습 대기 중 (run_id={run_id}). 사유: {body.reason or '수동 트리거'}",
    )
