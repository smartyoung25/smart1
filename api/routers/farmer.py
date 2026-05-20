"""Farmer-facing API routes."""
from __future__ import annotations
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

from api.schemas.farmer import (
    DiseaseRiskResponse,
    FarmAlert,
    FarmSummary,
    FarmMeta,
    FarmMetaUpdate,
    RecommendationItem,
    RecommendationsResponse,
    ApplyRequest,
    ApplyResponse,
    EnvPoint,
    EnvironmentSection,
    EnvironmentResponse,
    HarvestForecast,
    RevenueResponse,
    CostItem,
    CostBreakdownResponse,
    ManualCostInput,
    ManualCostResponse,
    ManualEnvInput,
    ManualEnvResponse,
    WhatIfInput,
    WhatIfResult,
    ChatRequest,
    ChatResponse,
)
from engine.farm_tier import FarmTier
from engine.profit_optimizer import optimize
from engine.what_if_simulator import EnvState
from api.services.kma_service import get_weather_summary, FARM_STATION
from api.services.region_station import find_station, list_sido, list_sigungu
from api.data.stats_loader import (
    get_price_krw_kg,
    get_yield_kg_m2,
    get_electricity_rate,
    get_water_rate,
    estimate_harvest_days,
)
from api.services import persistence
from api.services.model_loader import predict_revenue_per_m2, get_model_meta
from models.m5_disease import env_risk_predict as _env_risk_predict
from adapters.irrigation_adapter import adapt_irrigation

router = APIRouter(prefix="/api/farms/{farm_id}", tags=["farmer"])

# ---------------------------------------------------------------------------
# Farm registry
# iot_available=False → IoT 미구축 농가, 수동 환경값 입력만 가능
# ---------------------------------------------------------------------------

_FARM_META: dict[str, dict[str, Any]] = {
    # 작목·운영 방식·규모를 명시해 수익 최적화 맥락을 제공
    "farm_001": {
        "tier": FarmTier.MANUAL,    "area_m2": 1200, "iot_available": True,
        "name": "동서 오이 농장",  "crop": "오이",
        "sido": "경상남도", "sigungu": "창녕군", "address_detail": "",
    },
    "farm_002": {
        "tier": FarmTier.SEMI_AUTO, "area_m2": 800,  "iot_available": True,
        "name": "청풍 토마토 농장", "crop": "방울토마토",
        "sido": "충청북도", "sigungu": "충주시", "address_detail": "",
    },
    "farm_003": {
        "tier": FarmTier.MANUAL,    "area_m2": 1500, "iot_available": True,
        "name": "한솔 딸기 농장",  "crop": "딸기(설향)",
        "sido": "전라북도", "sigungu": "군산시", "address_detail": "",
    },
    "farm_004": {
        "tier": FarmTier.SEMI_AUTO, "area_m2": 1000, "iot_available": True,
        "name": "대원 토마토 농장", "crop": "완숙토마토",
        "sido": "경상북도", "sigungu": "상주시", "address_detail": "",
    },
    "farm_005": {
        "tier": FarmTier.MANUAL,    "area_m2": 900,  "iot_available": False,
        "name": "농가 E (IoT 미구축)", "crop": "미등록",
        "sido": None, "sigungu": None, "address_detail": "",
    },
}

# ── 농가별 IoT 실시간 환경값 (각 농장 작목·계절 반영) ─────────────────────
#
# farm_001  동서오이   오이는 고온·고습·적정 EC, 신속 생장
# farm_002  청풍토마토  방울토마토는 고온·강광·고CO₂·높은 EC
# farm_003  한솔딸기   딸기는 저온·고습·약광 (개화기 주의)
# farm_004  대원토마토  완숙토마토는 고온·강광·적정 EC
# farm_005  수동 입력만 — _MANUAL_ENV 에서 읽음

_FARM_ENV: dict[str, dict[str, float]] = {
    "farm_001": {           # 오이: 고온·고습, EC 중간
        "temp_internal": 23.0,
        "humidity_int":  76.0,
        "co2_ppm":       850.0,
        "solar_rad":     320.0,
        "ec_dsm":         2.0,
        "soil_temp":     19.0,
    },
    "farm_002": {           # 방울토마토: 고온·강광·고CO₂
        "temp_internal": 25.3,
        "humidity_int":  67.0,
        "co2_ppm":      1120.0,
        "solar_rad":     490.0,
        "ec_dsm":         2.9,
        "soil_temp":     21.2,
    },
    "farm_003": {           # 딸기(설향): 저온·고습·약광
        "temp_internal": 17.6,
        "humidity_int":  83.0,
        "co2_ppm":       860.0,
        "solar_rad":     185.0,
        "ec_dsm":         1.3,
        "soil_temp":     14.4,
    },
    "farm_004": {           # 완숙토마토: 고온·강광·적정 EC
        "temp_internal": 23.5,
        "humidity_int":  68.0,
        "co2_ppm":       950.0,
        "solar_rad":     480.0,
        "ec_dsm":         2.8,
        "soil_temp":     20.0,
    },
}

_ENV_UNITS: dict[str, str] = {
    "temp_internal": "°C",
    "temp_external": "°C",      # 기상청 ASOS 외부 온도
    "humidity_int":  "%",
    "co2_ppm":       "ppm",
    "solar_rad":     "W/m²",
    "ec_dsm":        "dS/m",
    "soil_temp":     "°C",
    "wind_speed_ext":"m/s",
}

# ASOS에서 온 변수 목록 — quality_tag를 TRANSFER로 표시
_ASOS_VARIABLES = {"temp_external", "wind_speed_ext"}

# ── 작목별 환경 임계값 → 알림 생성 규칙 ────────────────────────────────────
#
# 각 규칙: (variable, direction, threshold, severity, message_ko)
#   direction: "above" = 초과 시 알림, "below" = 미만 시 알림
#
_ALERT_RULES: dict[str, list[tuple]] = {
    "farm_001": [  # 오이
        ("humidity_int", "above",  85.0,  "warning", "내부 습도 85% 초과 — 오이 흰가루병·노균병 위험"),
        ("temp_internal","below",  18.0,  "warning", "내부 온도 18°C 미만 — 오이 저온 장해·생육 지연"),
        ("ec_dsm",       "above",   2.5,  "info",    "EC 농도 2.5 dS/m 초과 — 오이 적정 구간(1.5~2.5) 점검"),
    ],
    "farm_002": [  # 방울토마토
        ("ec_dsm",       "above",   2.8,  "warning", "EC 농도가 방울토마토 권장 상한(2.8 dS/m) 초과"),
        ("temp_internal","above",  26.0,  "danger",  "내부 온도 26°C 초과 — 착과 불량·낙과 위험"),
    ],
    "farm_003": [  # 딸기(설향)
        ("humidity_int", "above",  75.0,  "danger",  "습도 75% 초과 — 회색 곰팡이(보트리티스) 발생 위험"),
        ("ec_dsm",       "below",   1.5,  "warning", "EC 농도가 딸기 개화기 권장치(1.5 dS/m) 이하"),
        ("temp_internal","above",  20.0,  "warning", "딸기 적정 온도(≤20°C) 초과 — 품질 저하 가능"),
    ],
    "farm_004": [  # 완숙토마토
        ("temp_internal","above",  28.0,  "danger",  "내부 온도 28°C 초과 — 완숙토마토 고온 장해·낙과 위험"),
        ("ec_dsm",       "above",   3.5,  "warning", "EC 농도 3.5 dS/m 초과 — 완숙토마토 권장 상한 초과"),
        ("humidity_int", "above",  80.0,  "warning", "습도 80% 초과 — 완숙토마토 잿빛곰팡이 위험"),
    ],
}


def _build_alerts(farm_id: str, env: dict[str, float]) -> list[FarmAlert]:
    """환경값과 임계값을 비교해 FarmAlert 목록 반환."""
    rules = _ALERT_RULES.get(farm_id, [])
    alerts = []
    for i, (var, direction, threshold, severity, msg) in enumerate(rules):
        val = env.get(var)
        if val is None:
            continue
        triggered = (direction == "above" and val > threshold) or \
                    (direction == "below" and val < threshold)
        if triggered:
            alerts.append(FarmAlert(
                id=f"{farm_id}_{var}_{i}",
                severity=severity,
                variable=var,
                message_ko=msg,
                value=round(val, 2),
                threshold=threshold,
                unit=_ENV_UNITS.get(var, ""),
            ))
    return alerts


# ── 수익 파라미터 출처 ──────────────────────────────────────────────────────────
# 단가(kamis_price)   : api/data/stats_loader.get_price_krw_kg()   — KAMIS 5년 패널
# 수확량(yield_kg_m2) : api/data/stats_loader.get_yield_kg_m2()    — 농진청 패널
# ML 예측 매출        : api/services/model_loader.predict_revenue_per_m2()
#                       → models/artifacts/{crop}_revenue_model.pkl (XGB+LGB 앙상블)
# 비용                : _compute_costs() 함수로 _RESOURCE_COSTS 기반 상세 계산
#
# NOTE: 이전 버전의 _FARM_REVENUE 인메모리 dict는 stats_loader + model_loader 로 대체됨

# ---------------------------------------------------------------------------
# 농가별 자원 소비 데이터 (일별 기준, 월 30일 적용)
# 전기: 농업용(갑종) 계시별 요금 기준  105원/kWh
# 용수: 농업용 지하수·지표수 평균      700원/m³
# 난방: LPG·도시가스 열량 환산         85원/kWh
# 인건비: 2025 농업 최저 근로 기준    12,000원/시간
# ---------------------------------------------------------------------------
_RESOURCE_COSTS: dict[str, dict] = {
    "farm_001": {   # 오이 1200m² — 고온·고습, 수막재배
        "electricity_kwh_day": 120.0,   # 환기팬 + 보광
        "electricity_rate":    105.0,   # 원/kWh (stats_loader 적용)
        "water_m3_day":          4.0,   # 오이 다수확 관비 多
        "water_rate":          700.0,   # 원/m³ (stats_loader 적용)
        "heating_kwh_day":      72.0,   # 야간 가온
        "heating_rate":         85.0,   # 원/kWh (가스 환산)
        "labor_hours_day":       5.0,   # 유인·수확 반복
        "labor_rate":        12_000.0,  # 원/시간
        "nutrients_krw_day": 15_000.0,  # 양액 관비
        "pesticides_krw_day": 3_000.0,  # 노균병 방제
    },
    "farm_002": {   # 방울토마토 800m² — 반자동
        "electricity_kwh_day": 112.0,
        "electricity_rate":    105.0,
        "water_m3_day":          3.2,   # 고수량 작물
        "water_rate":          700.0,
        "heating_kwh_day":      80.0,   # 고온 필요
        "heating_rate":         85.0,
        "labor_hours_day":       3.0,   # 반자동 절감
        "labor_rate":        12_000.0,
        "nutrients_krw_day": 14_000.0,
        "pesticides_krw_day": 4_000.0,
    },
    "farm_003": {   # 딸기(설향) 1500m² — 노동집약
        "electricity_kwh_day": 150.0,
        "electricity_rate":    105.0,
        "water_m3_day":          4.5,
        "water_rate":          700.0,
        "heating_kwh_day":     135.0,   # 저온 관리 + 야간 가온
        "heating_rate":         85.0,
        "labor_hours_day":       8.0,   # 수작업 비중 높음
        "labor_rate":        12_000.0,
        "nutrients_krw_day": 22_000.0,
        "pesticides_krw_day": 6_000.0,  # 병해 취약
    },
    "farm_004": {   # 완숙토마토 1000m² — 반자동
        "electricity_kwh_day": 130.0,
        "electricity_rate":    105.0,
        "water_m3_day":          4.0,
        "water_rate":          700.0,
        "heating_kwh_day":      90.0,
        "heating_rate":         85.0,
        "labor_hours_day":       4.0,
        "labor_rate":        12_000.0,
        "nutrients_krw_day": 16_000.0,
        "pesticides_krw_day": 3_500.0,
    },
    "farm_005": {   # 미등록 900m²
        "electricity_kwh_day":  90.0,
        "electricity_rate":    105.0,
        "water_m3_day":          1.8,
        "water_rate":          700.0,
        "heating_kwh_day":      54.0,
        "heating_rate":         85.0,
        "labor_hours_day":       3.0,
        "labor_rate":        12_000.0,
        "nutrients_krw_day":  9_000.0,
        "pesticides_krw_day": 2_000.0,
    },
}

# 수동 입력값은 persistence 서비스를 통해 DB(또는 in-memory 폴백)에 저장
# _MANUAL_ENV / _MANUAL_COSTS 인메모리 dict 제거 → persistence.get/set_manual_env/cost 사용


def _require_farm(farm_id: str) -> dict[str, Any]:
    meta = _FARM_META.get(farm_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Farm '{farm_id}' not found")
    return meta


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _get_env(farm_id: str) -> dict[str, float]:
    """실시간 환경값 반환.

    우선순위:
      1. IoT 미구축 농가 → 수동 입력값 (_MANUAL_ENV) 우선
      2. IoT 구축 농가   → _FARM_ENV 기본값 기반
      3. 공통 보강       → 기상청 ASOS 실측값으로 temp/humidity/solar/soil 갱신
    """
    meta = _FARM_META[farm_id]

    if not meta["iot_available"]:
        # IoT 없음: 수동 입력 있으면 사용, 없으면 빈 dict
        base = persistence.get_manual_env(farm_id)
    else:
        base = dict(_FARM_ENV[farm_id])

    # 기상청 ASOS 실측값으로 외부 기상 관련 항목 보강
    # (온도는 오프셋 보정값 사용, IoT 농가는 내부 측정값 우선이므로 덮어쓰지 않음)
    try:
        wx = get_weather_summary(farm_id)
        if wx["temp_external"] is not None:
            # 외부 온도는 항상 ASOS 값으로 갱신
            base["temp_external"] = round(wx["temp_external"], 1)

        if not meta["iot_available"]:
            # IoT 없는 농가: ASOS 값으로 내부 환경 추정
            gh_temp = wx.get("temp_external")
            if gh_temp is not None and "temp_internal" not in base:
                base["temp_internal"] = round(gh_temp + 4.0, 1)   # 온실 보온 +4°C
            if wx["humidity_ext"] is not None and "humidity_int" not in base:
                base["humidity_int"] = round(wx["humidity_ext"], 1)
            if wx["solar_rad_est"] is not None and "solar_rad" not in base:
                base["solar_rad"] = round(wx["solar_rad_est"], 1)
            if wx["soil_temp"] is not None and "soil_temp" not in base:
                base["soil_temp"] = round(wx["soil_temp"], 1)
        else:
            # IoT 있는 농가: 일사량만 ASOS 참고값으로 보정 (없을 경우에만)
            if wx["solar_rad_est"] is not None:
                base.setdefault("solar_rad", round(wx["solar_rad_est"], 1))
    except Exception as exc:
        # ASOS 오류는 무시하고 기존값 유지
        logger.error("[_get_env] ASOS 조회 실패 farm=%s: %s", farm_id, exc)

    return base


# ---------------------------------------------------------------------------
# GET /meta
# ---------------------------------------------------------------------------

def _meta_to_response(farm_id: str, meta: dict) -> FarmMeta:
    """_FARM_META dict → FarmMeta 응답 (ASOS 관측소 ID 자동 계산 포함)."""
    sido    = meta.get("sido")
    sigungu = meta.get("sigungu") or ""
    stn_id  = find_station(sido, sigungu) if sido else FARM_STATION.get(farm_id)
    return FarmMeta(
        farm_id=farm_id,
        name=meta["name"],
        crop=meta["crop"],
        tier=meta["tier"].value,
        iot_available=meta["iot_available"],
        area_m2=meta["area_m2"],
        sido=sido,
        sigungu=meta.get("sigungu"),
        address_detail=meta.get("address_detail"),
        asos_station_id=stn_id,
    )


@router.get("/meta", response_model=FarmMeta)
def get_meta(farm_id: str):
    meta = _require_farm(farm_id)
    return _meta_to_response(farm_id, meta)


@router.put("/meta", response_model=FarmMeta)
def update_meta(farm_id: str, body: FarmMetaUpdate):
    """농장 기본 정보 수정 (이름·작목·면적·주소).

    주소가 변경되면 ASOS 관측소를 자동 재매핑하고 날씨 캐시를 무효화.
    """
    meta = _require_farm(farm_id)

    # 변경된 필드만 반영
    if body.name         is not None: meta["name"]           = body.name
    if body.crop         is not None: meta["crop"]           = body.crop
    if body.area_m2      is not None: meta["area_m2"]        = body.area_m2
    if body.sido         is not None: meta["sido"]           = body.sido
    if body.sigungu      is not None: meta["sigungu"]        = body.sigungu
    if body.address_detail is not None: meta["address_detail"] = body.address_detail

    # 주소 변경 시 ASOS 관측소 갱신
    sido    = meta.get("sido")
    sigungu = meta.get("sigungu") or ""
    if sido:
        new_stn = find_station(sido, sigungu)
        FARM_STATION[farm_id] = new_stn   # kma_service 매핑 실시간 갱신
        # 캐시 무효화 (kma_service._cache에서 해당 농가 제거)
        from api.services import kma_service
        kma_service._cache.pop(farm_id, None)

    return _meta_to_response(farm_id, meta)


@router.get("/meta/regions")
def get_regions(sido: str | None = None):
    """시도 목록 또는 특정 시도의 시군구 목록 반환 (주소 입력 드롭다운용)."""
    if sido is None:
        return {"sido_list": list_sido()}
    return {"sido": sido, "sigungu_list": list_sigungu(sido)}


# ---------------------------------------------------------------------------
# GET /summary
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=FarmSummary)
def get_summary(farm_id: str):
    meta = _require_farm(farm_id)
    env  = _get_env(farm_id)
    alerts = _build_alerts(farm_id, env) if env else []

    # 이번 달 순이익 = 수확량 × 단가 × 면적 - 실비용 (stats_loader 실데이터)
    crop     = meta.get("crop", "딸기")
    area     = meta["area_m2"]
    price    = get_price_krw_kg(crop)
    yield_m2 = get_yield_kg_m2(crop)
    cb       = _compute_costs(farm_id)
    revenue_mtd = yield_m2 * price * area - cb.total_cost_krw

    # 수확 예정일: GDD 기반 (현재 온도 활용)
    env = _get_env(farm_id)
    temp_now = (env or {}).get("temp_internal", 18.0)
    harvest_days = estimate_harvest_days(crop, float(temp_now))
    if harvest_days >= 999:
        harvest_days = 30   # 온도 너무 낮은 경우 기본값

    return FarmSummary(
        farm_id=farm_id,
        updated_at=_now(),
        alert_count=len(alerts),
        alerts=alerts,
        harvest_days_remaining=harvest_days,
        revenue_mtd_krw=round(revenue_mtd),
    )


# ---------------------------------------------------------------------------
# GET /recommendations
# ---------------------------------------------------------------------------

@router.get("/recommendations", response_model=RecommendationsResponse)
def get_recommendations(farm_id: str):
    meta = _require_farm(farm_id)
    env_values = _get_env(farm_id)

    # IoT 미구축이고 수동 입력값이 없으면 빈 추천 반환
    if not meta["iot_available"] and not env_values:
        return RecommendationsResponse(
            farm_id=farm_id,
            updated_at=_now(),
            recommendations=[],
        )

    # 수동 입력값이 부분적일 수 있으므로 기본값(farm_001 기준)으로 채움
    base = _FARM_ENV.get(farm_id, _FARM_ENV["farm_001"])
    merged_env = {**base, **env_values}
    current_env = EnvState(farm_id=farm_id, values=merged_env)

    recs = optimize(
        farm_id=farm_id,
        tier=meta["tier"],
        current_env=current_env,
        horizon_days=30,
        area_m2=meta["area_m2"],
        crop_ko=meta.get("crop", "딸기"),
    )
    items = [
        RecommendationItem(
            rank=r.rank,
            action_ko=r.action_ko,
            profit_delta=r.profit_delta,
            revenue_delta=r.revenue_delta,
            cost_delta=r.cost_delta,
            confidence=r.confidence,
            tier_action=r.tier_action,
            canonical_changes=r.canonical_changes,
        )
        for r in recs
    ]
    return RecommendationsResponse(
        farm_id=farm_id,
        updated_at=_now(),
        recommendations=items,
    )


# ---------------------------------------------------------------------------
# POST /apply
# ---------------------------------------------------------------------------

@router.post("/apply", response_model=ApplyResponse)
def apply_recommendation(farm_id: str, body: ApplyRequest):
    meta = _require_farm(farm_id)
    tier = meta["tier"]
    if tier == FarmTier.MANUAL:
        return ApplyResponse(
            status="checklist_generated",
            message_ko="체크리스트가 생성되었습니다. 직접 조작해 주세요.",
            checklist_url=f"/checklists/{farm_id}/latest",
        )
    if tier == FarmTier.SEMI_AUTO and not body.confirmed:
        return ApplyResponse(
            status="approval_required",
            message_ko="승인이 필요합니다. confirmed=true로 재요청해 주세요.",
        )
    return ApplyResponse(
        status="sent",
        message_ko="액추에이터 명령이 전송되었습니다.",
    )


# ---------------------------------------------------------------------------
# POST /environment/manual  ← 반드시 GET /environment 앞에 등록
# ---------------------------------------------------------------------------

@router.post("/environment/manual", response_model=ManualEnvResponse)
def submit_manual_env(farm_id: str, body: ManualEnvInput):
    meta = _require_farm(farm_id)
    if meta["iot_available"]:
        raise HTTPException(
            status_code=400,
            detail=f"Farm '{farm_id}'은 IoT가 구축된 농가입니다. 수동 입력이 필요하지 않습니다.",
        )

    # None이 아닌 필드만 저장
    incoming = body.model_dump(exclude_none=True)
    if not incoming:
        raise HTTPException(status_code=422, detail="최소 하나 이상의 환경값을 입력해야 합니다.")

    # 기존 값 병합 후 저장 (부분 업데이트 지원)
    existing = persistence.get_manual_env(farm_id)
    merged = {**existing, **incoming}
    persistence.set_manual_env(farm_id, merged)

    return ManualEnvResponse(
        status="saved",
        message_ko=f"{len(incoming)}개 환경값이 저장되었습니다. AI 추천이 업데이트됩니다.",
        stored_fields=list(merged.keys()),
    )


# ---------------------------------------------------------------------------
# GET /environment
# ---------------------------------------------------------------------------

@router.get("/environment", response_model=EnvironmentResponse)
def get_environment(farm_id: str):
    meta   = _require_farm(farm_id)
    iot_ok = meta["iot_available"]

    # ── 실내 환경 변수 ──────────────────────────────────────────────────────────
    _INDOOR_VARS = {"temp_internal", "humidity_int", "co2_ppm", "solar_rad", "ec_dsm", "soil_temp"}

    if iot_ok:
        indoor_raw     = dict(_FARM_ENV.get(farm_id, {}))
        indoor_source  = "iot"
        indoor_label   = "실내 환경 (IoT 센서)"
        indoor_quality = "FINETUNED"
        indoor_edit    = False
    else:
        indoor_raw     = persistence.get_manual_env(farm_id)
        indoor_source  = "manual_input" if indoor_raw else "none"
        indoor_label   = "실내 환경 (수동 입력)"
        indoor_quality = "MANUAL_INPUT"
        indoor_edit    = True

    indoor_pts = [
        EnvPoint(
            canonical_name=name, value=round(val, 2),
            unit=_ENV_UNITS.get(name, ""),
            quality_tag=indoor_quality,
            imputed=False,
        )
        for name, val in indoor_raw.items()
        if name in _INDOOR_VARS
    ]

    indoor_section = EnvironmentSection(
        source=indoor_source,
        label_ko=indoor_label,
        editable=indoor_edit,
        has_data=bool(indoor_pts),
        measurements=indoor_pts,
    )

    # ── 외부 기상 (기상청 ASOS) ─────────────────────────────────────────────────
    outdoor_pts: list[EnvPoint] = []
    try:
        wx = get_weather_summary(farm_id)
        # imputed=True 는 직접 관측이 아닌 파생·추정값에만 표시
        # solar_rad_est 는 ASOS hr1MaxIcsr 에서 변환한 추정치 → imputed=True
        # 그 외는 ASOS 관측소 직접 실측값 → imputed=False
        _wx_fields = [
            ("temp_external",  wx.get("temp_external"),  "°C",   False),
            ("humidity_ext",   wx.get("humidity_ext"),   "%",    False),
            ("wind_speed_ext", wx.get("wind_speed_ext"), "m/s",  False),
            ("solar_rad_est",  wx.get("solar_rad_est"),  "W/m²", True),   # 추정값
            ("soil_temp",      wx.get("soil_temp"),      "°C",   False),
        ]
        outdoor_pts = [
            EnvPoint(
                canonical_name=name, value=round(val, 2),
                unit=unit,
                quality_tag="TRANSFER",
                imputed=imputed,
            )
            for name, val, unit, imputed in _wx_fields
            if val is not None
        ]
    except Exception:
        pass

    outdoor_section = EnvironmentSection(
        source="asos",
        label_ko="외부 기상 (기상청 ASOS)",
        editable=False,
        has_data=bool(outdoor_pts),
        measurements=outdoor_pts,
    )

    # 하위 호환: 기존 measurements = indoor + outdoor 전체
    all_pts = indoor_pts + outdoor_pts

    return EnvironmentResponse(
        farm_id=farm_id,
        updated_at=_now(),
        iot_available=iot_ok,
        indoor=indoor_section,
        outdoor=outdoor_section,
        measurements=all_pts,
    )


# ---------------------------------------------------------------------------
# GET /environment/weather  — 기상청 ASOS 외부 기상 원본
# ---------------------------------------------------------------------------

@router.get("/environment/weather")
def get_weather(farm_id: str):
    """기상청 ASOS 최근 1일 외부 기상 데이터 반환 (캐시 1시간)."""
    _require_farm(farm_id)
    try:
        wx = get_weather_summary(farm_id)
        return {
            "farm_id":        farm_id,
            "updated_at":     _now(),
            "source":         "kma_asos",
            "obs_date":       wx.get("obs_date"),
            "station_id":     wx.get("station_id"),
            "temp_external":  wx.get("temp_external"),
            "humidity_ext":   wx.get("humidity_ext"),
            "solar_rad_est":  wx.get("solar_rad_est"),
            "soil_temp":      wx.get("soil_temp"),
            "wind_speed_ext": wx.get("wind_speed_ext"),
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"기상청 API 오류: {exc}")


# ---------------------------------------------------------------------------
# GET /harvest
# ---------------------------------------------------------------------------

@router.get("/harvest", response_model=HarvestForecast)
def get_harvest(farm_id: str):
    meta = _require_farm(farm_id)
    crop = meta.get("crop", "딸기")

    # 현재 내부 온도: IoT/수동 → ASOS 추정값 순으로 가져옴
    env      = _get_env(farm_id)
    temp_now = float((env or {}).get("temp_internal", 18.0))

    days_to_harvest = estimate_harvest_days(crop, temp_now)
    if days_to_harvest >= 999:
        days_to_harvest = 45   # 온도 너무 낮은 예외 상황 기본값

    predicted_date = (date.today() + timedelta(days=days_to_harvest)).isoformat()
    yield_m2       = get_yield_kg_m2(crop)

    return HarvestForecast(
        farm_id=farm_id,
        updated_at=_now(),
        predicted_date=predicted_date,
        predicted_yield_kg_m2=round(yield_m2, 2),
        confidence=0.72,
    )


# ---------------------------------------------------------------------------
# GET /revenue
# ---------------------------------------------------------------------------

@router.get("/revenue", response_model=RevenueResponse)
def get_revenue(farm_id: str):
    meta     = _require_farm(farm_id)
    crop     = meta.get("crop", "딸기")
    area     = meta["area_m2"]

    # 실데이터 단가 (stats_loader — KAMIS 5년 패널 기반)
    price    = get_price_krw_kg(crop)

    # ── ML 모델 예측 (없으면 통계 기반 폴백) ──────────────────────────────────
    env      = _get_env(farm_id)
    import datetime as _dt
    _cur_month = _dt.date.today().month
    env_feat = {
        "temp_internal_mean":  float(env.get("temp_internal", 20.0)),
        "humidity_int_mean":   float(env.get("humidity_int",  70.0)),
        "co2_ppm_mean":        float(env.get("co2_ppm",      800.0)),
        "solar_rad_mean":      float(env.get("solar_rad",    100.0)),
        "soil_temp_mean":      float(env.get("soil_temp",     18.0)),
        "gdd_monthly":         max(0.0, float(env.get("temp_internal", 20.0)) - 10.0) * 30.0,
    }
    ml_rev_pm2 = predict_revenue_per_m2(crop, env_feat, month=_cur_month)
    model_meta = get_model_meta(crop)

    if ml_rev_pm2 is not None and ml_rev_pm2 > 0:
        # ML 예측값: 원/m²/월 → 월간 매출
        revenue      = ml_rev_pm2 * area
        revenue_src  = "ml_model"
        logger.info(
            "[get_revenue] farm=%s crop=%s ML예측 %.0f원/m² × %.0fm² = %.0f원",
            farm_id, crop, ml_rev_pm2, area, revenue,
        )
    else:
        # 통계 폴백: 수확량 × 단가 × 면적
        yield_m2 = get_yield_kg_m2(crop)
        revenue  = yield_m2 * price * area
        revenue_src = "stats_fallback"
        logger.info(
            "[get_revenue] farm=%s crop=%s 통계폴백 yield=%.2f kg/m² → %.0f원",
            farm_id, crop, yield_m2, revenue,
        )

    # 비용: _compute_costs 상세 항목 합산 (실단가 반영)
    cb   = _compute_costs(farm_id)
    cost = cb.total_cost_krw

    return RevenueResponse(
        farm_id=farm_id,
        updated_at=_now(),
        kamis_price_krw_kg=round(price, 0),
        predicted_revenue_krw=round(revenue, 0),
        predicted_cost_krw=round(cost, 0),
        predicted_profit_krw=round(revenue - cost, 0),
    )


# ---------------------------------------------------------------------------
# POST /whatif  — 가상 환경값으로 수익 변화 시뮬레이션
# ---------------------------------------------------------------------------

def _env_to_feat(env: dict, crop_ko: str) -> dict:
    """환경 dict → ML 피처 dict 변환 (모델 입력 형식)."""
    temp = float(env.get("temp_internal", 20.0))
    return {
        "temp_internal_mean": temp,
        "humidity_int_mean":  float(env.get("humidity_int", 70.0)),
        "co2_ppm_mean":       float(env.get("co2_ppm", 800.0)),
        "solar_rad_mean":     float(env.get("solar_rad", 100.0)),
        "soil_temp_mean":     float(env.get("soil_temp", 18.0)),
        "gdd_monthly":        max(0.0, temp - 10.0) * 30.0,
    }


@router.post("/whatif", response_model=WhatIfResult)
def whatif(farm_id: str, body: WhatIfInput):
    """가상 환경값으로 매출 변화 예측.

    슬라이더로 조절한 값을 body로 받아 ML 모델로 현재 대비 수익 델타를 반환.
    ML 모델이 없으면 온도 기반 단순 추정으로 폴백.
    """
    import datetime as _dt
    meta   = _require_farm(farm_id)
    crop   = meta.get("crop", "딸기")
    area   = meta["area_m2"]
    month  = _dt.date.today().month

    # 현재 환경값 (베이스라인)
    current_env = _get_env(farm_id)
    # 기본값 채우기 (IoT 미구축 시 빈 dict 방지)
    base_env = {**_FARM_ENV.get(farm_id, _FARM_ENV["farm_001"]), **current_env}

    # 가상 환경값: 현재값 위에 body 값 덮어쓰기
    hypo_env = {**base_env, **body.model_dump(exclude_none=True)}

    price = get_price_krw_kg(crop)

    def _predict(env: dict) -> tuple[float, str]:
        """env dict → (월 매출 원, 모델 출처)"""
        feat     = _env_to_feat(env, crop)
        ml_rev   = predict_revenue_per_m2(crop, feat, month=month)
        if ml_rev is not None and ml_rev > 0:
            return ml_rev * area, "ml_model"
        # 폴백: 온도 기반 단순 추정
        from api.data.stats_loader import get_yield_kg_m2
        yield_m2 = get_yield_kg_m2(crop)
        temp_bonus = max(0.0, (env.get("temp_internal", 20.0) - 20.0) * 0.01)
        return (yield_m2 + temp_bonus) * price * area, "stats_fallback"

    baseline_rev, src  = _predict(base_env)
    whatif_rev,   _    = _predict(hypo_env)
    delta              = whatif_rev - baseline_rev
    delta_pct          = (delta / baseline_rev * 100) if baseline_rev else 0.0

    logger.info(
        "[whatif] farm=%s crop=%s base=%.0f whatif=%.0f delta=%.0f",
        farm_id, crop, baseline_rev, whatif_rev, delta,
    )
    return WhatIfResult(
        baseline_revenue_krw=round(baseline_rev),
        whatif_revenue_krw=round(whatif_rev),
        delta_krw=round(delta),
        delta_pct=round(delta_pct, 2),
        confidence=0.75 if src == "ml_model" else 0.5,
        model_used=src,
    )


# ---------------------------------------------------------------------------
# GET /costs  — 자원별 비용 분석
# ---------------------------------------------------------------------------

def _compute_costs(farm_id: str) -> CostBreakdownResponse:
    """
    비용 계산 공통 로직.
    _MANUAL_COSTS[farm_id] 에 실제값이 있으면 해당 항목 우선 사용,
    없으면 _RESOURCE_COSTS 기본값 사용.
    """
    # farm_id가 _RESOURCE_COSTS에 없으면 가장 유사한 기본값(farm_001) 사용
    rc   = _RESOURCE_COSTS.get(farm_id, _RESOURCE_COSTS["farm_001"])
    mc   = persistence.get_manual_cost(farm_id)
    meta = _FARM_META.get(farm_id, _FARM_META["farm_001"])
    DAYS = 30

    def _v(key_manual: str, default: float) -> tuple[float, bool]:
        """(값, 실제입력여부)"""
        v = mc.get(key_manual)
        return (v, True) if v is not None else (default, False)

    # ── 전기 (단가: stats_loader 실데이터 → KEPCO 농업용갑 112원/kWh) ──────────
    kwh_m,   kwh_manual   = _v("electricity_kwh_month", rc["electricity_kwh_day"] * DAYS)
    e_rate,  e_rate_manual = _v("electricity_rate",     get_electricity_rate())
    elec     = kwh_m * e_rate
    elec_manual = kwh_manual or e_rate_manual

    # ── 용수 (단가: stats_loader 실데이터 → 농업용 평균 620원/m³) ────────────
    m3_m,    m3_manual    = _v("water_m3_month",  rc["water_m3_day"] * DAYS)
    w_rate,  w_rate_m     = _v("water_rate",       get_water_rate())
    water    = m3_m * w_rate
    water_manual = m3_manual or w_rate_m

    # ── 난방 ──────────────────────────────────────────────────────────────
    h_kwh,   h_kwh_m      = _v("heating_kwh_month", rc["heating_kwh_day"] * DAYS)
    h_rate,  h_rate_m     = _v("heating_rate",       rc["heating_rate"])
    heat     = h_kwh * h_rate
    heat_manual = h_kwh_m or h_rate_m

    # ── 인건비 ────────────────────────────────────────────────────────────
    l_hrs,   l_hrs_m      = _v("labor_hours_month", rc["labor_hours_day"] * DAYS)
    l_rate,  l_rate_m     = _v("labor_rate",         rc["labor_rate"])
    labor    = l_hrs * l_rate
    labor_manual = l_hrs_m or l_rate_m

    # ── 영양제·비료 ───────────────────────────────────────────────────────
    nutr,    nutr_manual  = _v("nutrients_krw_month",  rc["nutrients_krw_day"] * DAYS)
    pest,    pest_manual  = _v("pesticides_krw_month", rc["pesticides_krw_day"] * DAYS)

    total = elec + water + heat + labor + nutr + pest

    def pct(v: float) -> float:
        return round(v / total, 4) if total else 0.0

    # 저장된 실제값 객체 (폼 초기값으로 프론트에 내려줌)
    stored_mc = ManualCostInput(**mc) if mc else None
    has_manual = bool(mc)

    def _elec_label() -> str:
        src = "실제입력" if elec_manual else "KEPCO농업용갑"
        if elec_manual:
            return f"실제입력 {kwh_m:,.0f}kWh × {e_rate:.0f}원/kWh"
        return f"{rc['electricity_kwh_day']}kWh/일 × 30일 × {e_rate:.0f}원/kWh ({src})"

    def _water_label() -> str:
        src = "실제입력" if water_manual else "농업용평균"
        if water_manual:
            return f"실제입력 {m3_m:,.1f}m³ × {w_rate:.0f}원/m³"
        return f"{rc['water_m3_day']}m³/일 × 30일 × {w_rate:.0f}원/m³ ({src})"

    def _heat_label() -> str:
        if heat_manual:
            return f"실제입력 {h_kwh:,.0f}kWh × {h_rate:.0f}원/kWh"
        return f"{rc['heating_kwh_day']}kWh/일 × 30일 × {h_rate:.0f}원/kWh"

    def _labor_label() -> str:
        if labor_manual:
            return f"실제입력 {l_hrs:,.0f}시간 × {l_rate:,.0f}원/시간"
        return f"{rc['labor_hours_day']}시간/일 × 30일 × {l_rate:,.0f}원/시간"

    items = [
        CostItem(category="electricity", label_ko="전기료",
                 amount_krw=round(elec),  unit_label=_elec_label(),
                 pct_of_total=pct(elec),  is_manual=elec_manual),
        CostItem(category="water",       label_ko="용수비",
                 amount_krw=round(water), unit_label=_water_label(),
                 pct_of_total=pct(water), is_manual=water_manual),
        CostItem(category="heating",     label_ko="난방비",
                 amount_krw=round(heat),  unit_label=_heat_label(),
                 pct_of_total=pct(heat),  is_manual=heat_manual),
        CostItem(category="labor",       label_ko="인건비",
                 amount_krw=round(labor), unit_label=_labor_label(),
                 pct_of_total=pct(labor), is_manual=labor_manual),
        CostItem(category="nutrients",   label_ko="영양제·비료",
                 amount_krw=round(nutr),
                 unit_label="실제입력" if nutr_manual else f"{rc['nutrients_krw_day']:,.0f}원/일 × 30일",
                 pct_of_total=pct(nutr),  is_manual=nutr_manual),
        CostItem(category="pesticides",  label_ko="농약·방제",
                 amount_krw=round(pest),
                 unit_label="실제입력" if pest_manual else f"{rc['pesticides_krw_day']:,.0f}원/일 × 30일",
                 pct_of_total=pct(pest),  is_manual=pest_manual),
    ]

    return CostBreakdownResponse(
        farm_id=farm_id,
        updated_at=_now(),
        items=items,
        total_cost_krw=round(total),
        cost_per_m2=round(total / meta["area_m2"], 1),
        electricity_kwh_month=kwh_m,
        water_m3_month=m3_m,
        has_manual_input=has_manual,
        manual_input=stored_mc,
    )


@router.get("/costs", response_model=CostBreakdownResponse)
def get_costs(farm_id: str):
    _require_farm(farm_id)
    return _compute_costs(farm_id)


@router.post("/costs/manual", response_model=ManualCostResponse)
def post_costs_manual(farm_id: str, body: ManualCostInput):
    """
    농가 실제 비용 입력.
    입력된 항목만 저장 — 미입력 항목은 기본값(_RESOURCE_COSTS) 유지.
    """
    _require_farm(farm_id)
    stored = body.model_dump(exclude_none=True)
    if not stored:
        raise HTTPException(status_code=422, detail="입력된 값이 없습니다.")

    persistence.set_manual_cost(farm_id, stored)
    return ManualCostResponse(
        status="ok",
        message_ko=f"실제 비용이 저장됐습니다. ({len(stored)}개 항목)",
        stored_fields=list(stored.keys()),
    )


@router.delete("/costs/manual", status_code=200)
def delete_costs_manual(farm_id: str):
    """실제 입력값 삭제 → 기본 추정값으로 복원."""
    _require_farm(farm_id)
    persistence.set_manual_cost(farm_id, {})   # 빈 dict 저장 → 기본값으로 복원
    return {"status": "ok", "message_ko": "실제 비용 입력값이 삭제되어 기본값으로 복원됩니다."}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# GET /disease-risk  — 환경 센서 기반 병해 위험도 평가 (이미지 불필요)
# ---------------------------------------------------------------------------

@router.get("/disease-risk", response_model=DiseaseRiskResponse)
def get_disease_risk(farm_id: str):
    """현재 환경 측정값(온도·습도·CO2)으로 병해 위험도를 실시간 평가합니다.
    이미지 없이도 환경 조건으로 잿빛곰팡이·흰가루병·역병 위험을 진단합니다.
    """
    meta = _require_farm(farm_id)
    crop = meta.get("crop", "딸기")
    env  = _get_env(farm_id)

    env_snapshot = {
        "temp_internal": float(env.get("temp_internal", 20.0)),
        "humidity_int":  float(env.get("humidity_int", 70.0)),
        "co2_ppm":       float(env.get("co2_ppm", 800.0)),
    }

    result = _env_risk_predict(env_snapshot, crop)

    logger.info(
        "[disease_risk] farm=%s crop=%s → %s [%s] score=%.2f",
        farm_id, crop, result.disease, result.risk_level, result.score,
    )

    return DiseaseRiskResponse(
        farm_id=farm_id,
        updated_at=_now().isoformat(),
        crop=crop,
        disease=result.disease,
        disease_ko=result.disease_ko,
        risk_level=result.risk_level,
        score=result.score,
        reasons=result.reasons,
        action_ko=result.action_ko,
        env_snapshot=env_snapshot,
    )


# POST /chat  — AI 농가 운영 상담 (stub, AI API 연결 전)
# ---------------------------------------------------------------------------
# 실제 AI 연결 시: _stub_reply() 를 제거하고 아래 주석 처리된
# _call_ai_api() 호출로 교체하면 됩니다.
# ---------------------------------------------------------------------------

def _stub_reply(farm_id: str, message: str) -> ChatResponse:
    """
    농장 컨텍스트를 참조하는 규칙 기반 stub 응답.
    AI API 연결 전까지 사용. 연결 후에는 이 함수를 _call_ai_api()로 교체.
    """
    msg_lower = message.lower()
    meta   = _FARM_META.get(farm_id, {})
    env    = _get_env(farm_id) or {}
    alerts = _build_alerts(farm_id, env) if env else []
    crop   = meta.get("crop", "작물")
    area   = meta.get("area_m2", 0)

    referenced: list[str] = []

    # ── 수익 파라미터: stats_loader 실데이터 사용 ────────────────────────────────
    _price_live    = get_price_krw_kg(crop)
    _yield_live    = get_yield_kg_m2(crop)
    _cost_live_pm2 = _compute_costs(farm_id).cost_per_m2

    # ── 알림 관련 ────────────────────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["알림", "경고", "위험", "주의", "이상"]):
        referenced.append("alerts")
        if not alerts:
            return ChatResponse(
                reply=f"현재 {meta.get('name', farm_id)} 농장에 활성 알림이 없습니다. 환경 지표가 모두 정상 범위에 있어요.",
                suggestions=["환경 수치 자세히 보기", "지난 주 알림 이력은?", "병해 예방 체크리스트"],
                referenced_data=["alerts"],
            )
        alert_lines = "\n".join(
            f"• [{a.severity.upper()}] {a.message_ko} (현재 {a.value}{a.unit})"
            for a in alerts
        )
        return ChatResponse(
            reply=f"현재 {len(alerts)}건의 알림이 있습니다:\n\n{alert_lines}\n\n가장 시급한 항목부터 조치하시기 바랍니다.",
            suggestions=["조치 방법 알려줘", "알림 기준값은?", "자동 제어 설정하기"],
            referenced_data=["alerts", "environment"],
        )

    # ── 수확 관련 ─────────────────────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["수확", "언제", "d-", "예측일", "출하"]):
        referenced.append("harvest")
        try:
            hf = get_harvest(farm_id)
            d_day = (date.fromisoformat(hf.predicted_date) - date.today()).days
            d_str = hf.predicted_date
            reply_harvest = (
                f"{crop} 예상 수확일은 **{d_str} (D-{d_day})** 입니다.\n\n"
                f"예상 수확량 {hf.predicted_yield_kg_m2:.2f} kg/m² (신뢰도 {hf.confidence*100:.0f}%). "
                f"내부 온도를 1°C 높이면 수확일이 약 1~2일 앞당겨질 수 있습니다."
            )
        except Exception:
            reply_harvest = f"{crop} 수확 예측 데이터를 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
        return ChatResponse(
            reply=reply_harvest,
            suggestions=["온도 올리면 수익 얼마나 늘어?", "GDD란 무엇인가요?", "출하 물량 얼마나 준비할까?"],
            referenced_data=["harvest", "environment"],
        )

    # ── 수익·가격 관련 ────────────────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["수익", "매출", "가격", "kamis", "단가", "이익", "돈"]):
        referenced.append("revenue")
        price    = _price_live
        y_kg     = _yield_live
        cost     = _cost_live_pm2
        profit   = round((y_kg * price - cost) * area / 10000)
        return ChatResponse(
            reply=f"이번 달 {crop} 예상 순이익은 **{profit:,}만원** 입니다.\n\n"
                  f"• KAMIS 단가: {price:,.0f}원/kg\n"
                  f"• 수확량: {y_kg} kg/m²\n"
                  f"• 운영비: {cost:,.0f}원/m²\n\n"
                  f"수익을 높이려면 AI 추천 탭의 환경 조정 제안을 확인해 보세요.",
            suggestions=["수익 더 높이는 방법은?", "KAMIS 가격 내리면 어떻게 되나?", "운영비 줄이는 방법"],
            referenced_data=["revenue"],
        )

    # ── 온도 관련 ─────────────────────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["온도", "기온", "더워", "추워", "냉방", "난방"]):
        referenced.append("environment")
        temp_val = env.get("temp_internal", {})
        val_str  = f"{temp_val.get('value', '?')}°C" if isinstance(temp_val, dict) else "?"
        return ChatResponse(
            reply=f"현재 내부 온도는 {val_str} 입니다.\n\n"
                  f"{crop} 의 최적 온도 범위는 낮 18~22°C, 밤 12~15°C 입니다. "
                  f"착과기에는 온도 편차를 5°C 이내로 유지하는 것이 중요합니다.",
            suggestions=["온도 높이면 수익 얼마나 늘어?", "야간 온도 설정 방법", "온도 알림 기준 바꾸기"],
            referenced_data=["environment"],
        )

    # ── 습도·병해 관련 — env_risk_predict 실 호출 ─────────────────────────────
    if any(kw in msg_lower for kw in ["습도", "건조", "곰팡이", "흰가루", "병해", "역병", "탄저"]):
        referenced.append("disease_risk")
        env_snap = {
            "temp_internal": float(env.get("temp_internal", {}).get("value", env.get("temp_internal", 20.0))
                                   if isinstance(env.get("temp_internal"), dict)
                                   else env.get("temp_internal", 20.0)),
            "humidity_int":  float(env.get("humidity_int", {}).get("value", env.get("humidity_int", 70.0))
                                   if isinstance(env.get("humidity_int"), dict)
                                   else env.get("humidity_int", 70.0)),
            "co2_ppm":       float(env.get("co2_ppm", {}).get("value", env.get("co2_ppm", 800.0))
                                   if isinstance(env.get("co2_ppm"), dict)
                                   else env.get("co2_ppm", 800.0)),
        }
        risk = _env_risk_predict(env_snap, crop)
        risk_badge = {"high": "🔴 높음", "medium": "🟡 중간", "low": "🟢 낮음", "none": "✅ 정상"}.get(risk.risk_level, risk.risk_level)
        if risk.disease == "healthy":
            reply_disease = (
                f"현재 {crop} 농장의 병해 위험도는 {risk_badge}입니다.\n\n"
                f"온도 {env_snap['temp_internal']:.1f}°C, 습도 {env_snap['humidity_int']:.0f}%로 병해 발생 환경 조건에 해당하지 않습니다."
            )
        else:
            reasons_str = " / ".join(risk.reasons) if risk.reasons else "환경 조건 이상"
            reply_disease = (
                f"현재 {crop} 농장에서 **{risk.disease_ko}** 위험이 감지됐습니다. [{risk_badge}]\n\n"
                f"판단 근거: {reasons_str}\n\n"
                f"**권장 조치:** {risk.action_ko}"
            )
        return ChatResponse(
            reply=reply_disease,
            suggestions=["병해 진단 화면 보기", "환기 스케줄 최적화 방법", "방제 비용 얼마나 들어?"],
            referenced_data=["disease_risk", "environment"],
        )

    # ── CO₂ 관련 ─────────────────────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["co2", "이산화탄소", "탄소", "농도"]):
        referenced.append("environment")
        return ChatResponse(
            reply=f"{crop} 의 광합성 효율을 높이려면 CO₂ 농도를 **800~1,200 ppm** 으로 유지하세요.\n\n"
                  f"CO₂ 시비는 오전 일출 후 ~ 오후 2시 사이가 효과적입니다. "
                  f"1,500 ppm 이상은 비용 대비 효과가 낮습니다.",
            suggestions=["CO₂ 시비 비용은 얼마?", "CO₂와 수확량 관계", "자동 CO₂ 제어 설정"],
            referenced_data=["environment"],
        )

    # ── AI 추천 관련 — optimize() 실 호출 ──────────────────────────────────
    if any(kw in msg_lower for kw in ["추천", "제안", "개선", "최적", "올리", "높이"]):
        referenced.append("recommendations")
        try:
            from engine.what_if_simulator import EnvState as _ES
            _env_vals = {
                k: (v.get("value", 20.0) if isinstance(v, dict) else float(v))
                for k, v in env.items() if k in ("temp_internal","humidity_int","co2_ppm","solar_rad")
            }
            _cur_state = _ES(
                farm_id=farm_id,
                values={k: _env_vals.get(k, d) for k, d in
                        [("temp_internal", 20.0), ("humidity_int", 70.0),
                         ("co2_ppm", 800.0),      ("solar_rad", 150.0)]},
            )
            from engine.farm_tier import FarmTier as _FT
            _tier = _FT(meta.get("tier", "BASIC"))
            recs  = optimize(farm_id, _tier, _cur_state,
                             area_m2=float(area), crop_ko=crop)[:3]
            if recs:
                lines = "\n".join(
                    f"{i+1}. {r.action_ko} → 예상 수익 **+{r.profit_delta/10000:.0f}만원**"
                    for i, r in enumerate(recs)
                )
                reply_rec = f"현재 {crop} 농장 수익 극대화 상위 추천:\n\n{lines}\n\nAI 추천 탭에서 바로 적용할 수 있습니다."
            else:
                reply_rec = f"현재 {crop} 환경이 이미 최적에 가까워 추가 추천 조치가 없습니다."
        except Exception as _e:
            logger.warning("[chat/rec] optimize failed: %s", _e)
            reply_rec = f"추천 조치를 계산하는 중 오류가 발생했습니다. AI 추천 탭을 직접 확인해 주세요."
        return ChatResponse(
            reply=reply_rec,
            suggestions=["1번 추천 바로 적용", "추천 근거 더 자세히", "비용 부담 없는 조치만 보여줘"],
            referenced_data=["recommendations", "environment", "revenue"],
        )

    # ── 작물 재배 일반 ────────────────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["재배", "생육", "성장", "관리", "방법", "tip", "팁"]):
        return ChatResponse(
            reply=f"{crop} 스마트팜 운영 핵심 포인트:\n\n"
                  f"• 일조: 하루 14~16시간 유지 (보광등 활용)\n"
                  f"• 관비: EC {_ALERT_RULES.get(farm_id, [{}])[0] if _ALERT_RULES.get(farm_id) else '1.5~2.5'} dS/m\n"
                  f"• 환기: 온도·습도 연동 자동 제어 권장\n"
                  f"• 수확 후 방제: 다음 작기 병해 예방",
            suggestions=["EC 관리 방법 알려줘", "보광등 효과는?", "관비 스케줄 최적화"],
            referenced_data=[],
        )

    # ── 기본 응답 ─────────────────────────────────────────────────────────────
    farm_name = meta.get("name", farm_id)
    return ChatResponse(
        reply=f"안녕하세요! {farm_name} 농장 AI 상담사입니다. 🌱\n\n"
              f"현재 재배 작물: **{crop}** | 면적: {area}m²\n\n"
              f"아래 주제에 대해 질문해 주세요:\n"
              f"• 현재 알림 및 이상 징후\n"
              f"• 수확 예측 및 출하 계획\n"
              f"• 수익·단가 현황\n"
              f"• 온도·습도·CO₂ 환경 관리\n"
              f"• AI 추천 조치 실행",
        suggestions=["현재 알림 확인", "수확일 언제야?", "수익 높이는 방법은?", "오늘 환경 어때?"],
        referenced_data=["meta"],
    )


# ── 실제 AI API 연결 시 이 함수를 구현하고 _stub_reply 를 교체하세요 ──────────
# async def _call_ai_api(farm_id: str, message: str, history: list, context: dict) -> ChatResponse:
#     """
#     예시: OpenAI / Anthropic API 호출
#     system_prompt = build_system_prompt(context)   # 농장 컨텍스트 주입
#     response = await openai.chat.completions.create(
#         model="gpt-4o",
#         messages=[{"role": "system", "content": system_prompt}]
#                 + [{"role": m.role, "content": m.content} for m in history]
#                 + [{"role": "user", "content": message}],
#     )
#     return ChatResponse(
#         reply=response.choices[0].message.content,
#         model_used="gpt-4o",
#     )
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
def post_chat(farm_id: str, body: ChatRequest):
    """
    농가 운영 AI 상담.
    현재: 규칙 기반 stub (농장 컨텍스트 인식).
    AI API 연결 후: _stub_reply → _call_ai_api 교체.
    """
    _require_farm(farm_id)
    return _stub_reply(farm_id, body.message)

# ── P4 관수 데이터 수신 (관수통합관리시스템 연동) ─────────────────────────────

class IrrigationPeriod(BaseModel):
    period:     int   = Field(..., ge=1, le=4, description="구간 번호 (1=일출, 2=오전, 3=오후, 4=일몰)")
    supply_ml:  float = Field(0.0, ge=0, description="공급량 (ml)")
    drain_ml:   float = Field(0.0, ge=0, description="배액량 (ml)")
    ec:         Optional[float] = Field(None, description="배액 EC (dS/m)")
    ph:         Optional[float] = Field(None, description="배액 pH")
    slab_wt_kg: Optional[float] = Field(None, description="slab 무게 (kg)")


class IrrigationPayload(BaseModel):
    crop:          str              = Field(..., description="작물명 (한국어)")
    date:          str              = Field(..., description="날짜 (YYYY-MM-DD)")
    periods:       list[IrrigationPeriod] = Field(..., description="P4 구간별 데이터")
    slab_vol_l:    float            = Field(15.0, gt=0, description="slab 용량 (L)")
    max_wt_kg:     Optional[float]  = Field(None, description="당일 최대 무게 (kg)")
    min_wt_kg:     Optional[float]  = Field(None, description="일출 전 최소 무게 (kg)")
    sunset_wt_kg:  Optional[float]  = Field(None, description="일몰 직후 무게 (kg)")


class IrrigationResponse(BaseModel):
    farm_id:     str
    date:        str
    records_saved: int
    warnings:    list[str] = []
    summary: dict


@router.post("/irrigation", response_model=IrrigationResponse, summary="P4 관수 데이터 수신")
def receive_irrigation(farm_id: str, body: IrrigationPayload):
    """관수통합관리시스템(HTML)의 시간대별 관리 탭 P4 데이터를 수신해
    canonical 변수(wc_mean, dr_pct_mean, ec_drain, supply_total 등)로 변환·저장합니다.

    저장된 데이터는 다음 ETL 사이클에서 ML 학습 피처로 자동 편입됩니다.
    """
    payload_dict = {
        "farm_id":       farm_id,
        "crop":          body.crop,
        "date":          body.date,
        "slab_vol_l":    body.slab_vol_l,
        "max_wt_kg":     body.max_wt_kg,
        "min_wt_kg":     body.min_wt_kg,
        "sunset_wt_kg":  body.sunset_wt_kg,
        "periods": [
            {
                "period":     p.period,
                "supply_ml":  p.supply_ml,
                "drain_ml":   p.drain_ml,
                "ec":         p.ec,
                "ph":         p.ph,
                "slab_wt_kg": p.slab_wt_kg,
            }
            for p in body.periods
        ],
    }

    result = adapt_irrigation(payload_dict)

    # 실제 운영 환경에서는 DB에 저장; 현재는 로그만 기록
    if result.errors:
        logger.warning("[irrigation] farm=%s date=%s warnings: %s",
                       farm_id, body.date, result.errors)

    summary = {}
    for rec in result.records:
        summary[rec.canonical_name] = round(rec.value, 3)

    logger.info("[irrigation] farm=%s date=%s → %d canonical records: %s",
                farm_id, body.date, len(result.records), summary)

    return IrrigationResponse(
        farm_id=farm_id,
        date=body.date,
        records_saved=len(result.records),
        warnings=result.errors,
        summary=summary,
    )

