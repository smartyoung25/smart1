"""Farmer-facing API routes."""
from __future__ import annotations
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel, Field
from typing import Optional
from api.middleware.auth import require_auth

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
    WhatIfMultiInput,
    WhatIfMultiResult,
    WhatIfScenarioResult,
    ChatRequest,
    ChatResponse,
)
from engine.farm_tier import FarmTier
from engine.profit_optimizer import optimize
from engine.what_if_simulator import EnvState
from api.services.kma_service import (
    get_weather_summary, FARM_STATION, get_solar_irrigation_schedule,
    get_forecast_summary, get_forecast_3day,
)
from api.services.region_station import find_station, list_sido, list_sigungu
from api.data.stats_loader import (
    get_price_krw_kg,
    get_yield_kg_m2,
    get_electricity_rate,
    get_water_rate,
    estimate_harvest_days,
)
from api.services import persistence
from api.services.model_loader import predict_revenue_per_m2, get_model_meta, predict_yield_bounds
from models.m5_disease import env_risk_predict as _env_risk_predict
from adapters.irrigation_adapter import adapt_irrigation
from models.crop_config import CROP_CONFIGS
import time as _time, hashlib as _hashlib, json as _json_mod

# ── in-memory TTL 캐시 (Redis 없이 ML 추론 결과 캐싱) ────────────────────────
_RECO_CACHE:   dict[str, tuple[float, object]] = {}
_WHATIF_CACHE: dict[str, tuple[float, object]] = {}
_RECO_TTL   = 300   # 5분
_WHATIF_TTL = 120   # 2분

def _mk_cache_key(data: dict) -> str:
    return _hashlib.md5(_json_mod.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

def _cache_evict() -> None:
    now = _time.monotonic()
    for store in (_RECO_CACHE, _WHATIF_CACHE):
        for k in [k for k, (exp, _) in store.items() if exp < now]:
            del store[k]

async def _verify_farm_ownership(
    farm_id: str, user: dict = Depends(require_auth)
) -> dict:
    """URL의 farm_id가 인증된 사용자의 소유인지 확인 (admin/manager는 전체 허용)."""
    if user.get("role") not in ("admin", "manager", "superadmin"):
        token_farm = user.get("farm_id", "")
        if token_farm and token_farm != farm_id:
            raise HTTPException(
                status_code=403,
                detail="해당 농가에 대한 접근 권한이 없습니다.",
            )
    return user


router = APIRouter(
    prefix="/api/farms/{farm_id}",
    tags=["farmer"],
    dependencies=[Depends(_verify_farm_ownership)],
)

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
    # ── 실증 농가 (데이터 통합 완료) ──────────────────────────────────────────
    "jonomheon": {
        "tier": FarmTier.SEMI_AUTO, "area_m2": 6611, "iot_available": False,
        "name": "조남헌 파프리카 농장", "crop": "파프리카",
        "sido": "강원도", "sigungu": "철원군", "address_detail": "",
    },
    "sanwoo": {
        "tier": FarmTier.MANUAL,    "area_m2": 4000, "iot_available": False,
        "name": "SANWOO 딸기 농장",    "crop": "딸기",
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
    "jonomheon": {      # 조남헌 파프리카: 적온·적습
        "temp_internal": 22.0,
        "humidity_int":  65.0,
        "co2_ppm":       800.0,
        "solar_rad":     300.0,
        "ec_dsm":         2.0,
        "soil_temp":     18.0,
    },
    "sanwoo": {         # SANWOO 딸기: 저온·고습
        "temp_internal": 18.0,
        "humidity_int":  72.0,
        "co2_ppm":       900.0,
        "solar_rad":     200.0,
        "ec_dsm":         1.2,
        "soil_temp":     14.0,
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
    """환경값과 임계값을 비교해 FarmAlert 목록 반환 (레거시 정적 룰 기반)."""
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


def _detect_alerts(farm_id: str, env: dict[str, float], crop_ko: str = "딸기") -> list[FarmAlert]:
    """detect_anomalies() 물리·통계 엔진을 사용해 FarmAlert 목록 반환.

    _build_alerts()의 정적 룰 대신 anomaly_detector의 작기별·품종별
    VPD/통계 임계값을 활용한다. 결과가 없을 때 정적 룰로 폴백.
    """
    from api.services.anomaly_detector import detect_anomalies  # 순환 import 방지
    try:
        raw = detect_anomalies(
            crop_ko=crop_ko,
            env_values={k: v for k, v in env.items() if v is not None},
        )
    except Exception:
        raw = []

    alerts: list[FarmAlert] = []
    for i, a in enumerate(raw):
        # threshold: 위반 방향에 맞는 경계값
        if a.current_value > a.normal_max:
            threshold = a.normal_max
        else:
            threshold = a.normal_min
        # severity 매핑: anomaly_detector("minor/major/critical") → schema("info/warning/danger")
        sev_map = {"minor": "info", "major": "warning", "critical": "danger"}
        alerts.append(FarmAlert(
            id=f"{farm_id}_{a.variable}_{i}",
            severity=sev_map.get(a.severity, a.severity),
            variable=a.variable,
            message_ko=a.message_ko,
            value=round(a.current_value, 2),
            threshold=threshold,
            unit=a.unit,
        ))

    # 물리 엔진 결과가 없으면 정적 룰 폴백
    if not alerts:
        alerts = _build_alerts(farm_id, env)
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
# 인건비: 2026 농업 최저 근로 기준    12,000원/시간
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
        # farm_registry.json 폴백 (실제 농가 데이터)
        try:
            from api.data.stats_loader import _farm_registry
            reg = _farm_registry()
            reg_farm = reg.get("farms", {}).get(farm_id)
            if reg_farm:
                meta = {
                    "tier": FarmTier.MANUAL,
                    "area_m2": float(reg_farm.get("plant_area_m2") or 1000.0),
                    "iot_available": False,
                    "name": farm_id,
                    "crop": reg_farm.get("crop") or reg_farm.get("crop_ko", "미상"),
                    "sido": reg_farm.get("sido"), "sigungu": reg_farm.get("sigungu"),
                    "address_detail": "",
                }
                _FARM_META[farm_id] = meta  # 레지스트리 meta 캐시 — 후속 _FARM_META.get() 사이트가 지역/작물 인지
        except Exception:
            pass
    if meta is None:
        # 3단계 폴백: 온보딩 미완료 사용자를 위한 임시 메타 자동 생성
        # (farm_{username} 패턴 또는 온보딩 등록 전 최초 API 접근 시)
        logger.warning("[farmer] 미등록 farm_id '%s' — 임시 메타 생성 후 등록", farm_id)
        meta = {
            "tier":           FarmTier.MANUAL,
            "area_m2":        1000.0,
            "iot_available":  False,
            "name":           f"농장 ({farm_id})",
            "crop":           "미상",
            "sido":           None,
            "sigungu":        None,
            "address_detail": "",
        }
        _FARM_META[farm_id] = meta  # in-memory 캐시 등록 (재요청 시 빠른 응답)
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
    meta = _FARM_META.get(farm_id) or {}

    if not meta.get("iot_available", False):
        # IoT 없음: 수동 입력 있으면 사용, 없으면 빈 dict
        base = persistence.get_manual_env(farm_id)
    else:
        base = dict(_FARM_ENV.get(farm_id) or _FARM_ENV.get("farm_001", {}))

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
    crop     = meta.get("crop", "딸기")
    alerts = _detect_alerts(farm_id, env, crop_ko=crop) if env else []

    # 이번 달 순이익 = 수확량 × 단가 × 면적 - 실비용 (stats_loader 실데이터)
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

    # IoT 미구축 + 수동입력 없음 → _FARM_ENV에 합성 시뮬레이션값 있으면 활용
    # (/environment 호출 후 _FARM_ENV[farm_id]가 채워진 경우 포함)
    if not env_values:
        env_values = _FARM_ENV.get(farm_id, {})

    # 여전히 없으면 crop_ko 기준 작목 표준값 사용 (빈 권고 방지)
    if not env_values:
        _CROP_SIM_REC: dict[str, dict] = {
            "딸기":      {"temp_internal": 17.6, "humidity_int": 82.0, "co2_ppm": 860.0,
                          "solar_rad": 185.0, "ec_dsm": 1.3, "soil_temp": 14.4},
            "방울토마토": {"temp_internal": 25.3, "humidity_int": 67.0, "co2_ppm": 1120.0,
                          "solar_rad": 490.0, "ec_dsm": 2.9, "soil_temp": 21.2},
            "완숙토마토": {"temp_internal": 23.5, "humidity_int": 68.0, "co2_ppm": 950.0,
                          "solar_rad": 480.0, "ec_dsm": 2.8, "soil_temp": 20.0},
            "오이":      {"temp_internal": 23.0, "humidity_int": 76.0, "co2_ppm": 850.0,
                          "solar_rad": 320.0, "ec_dsm": 2.0, "soil_temp": 19.0},
            "파프리카":  {"temp_internal": 22.0, "humidity_int": 70.0, "co2_ppm": 900.0,
                          "solar_rad": 350.0, "ec_dsm": 2.5, "soil_temp": 18.5},
            "참외":      {"temp_internal": 25.0, "humidity_int": 65.0, "co2_ppm": 800.0,
                          "solar_rad": 400.0, "ec_dsm": 2.2, "soil_temp": 22.0},
        }
        crop_key = meta.get("crop", "딸기")
        env_values = _CROP_SIM_REC.get(crop_key) or _CROP_SIM_REC.get("딸기") or {}
        _FARM_ENV[farm_id] = dict(env_values)

    # 수동 입력값이 부분적일 수 있으므로 기본값으로 채움 (farm_001 없을 수도 있으므로 안전 접근)
    base = _FARM_ENV.get(farm_id) or _FARM_ENV.get("farm_001") or {}
    merged_env = {**base, **env_values}
    current_env = EnvState(farm_id=farm_id, values=merged_env)

    _cache_evict()
    _reco_ck = _mk_cache_key({"farm_id": farm_id, "env": merged_env})
    _reco_hit = _RECO_CACHE.get(_reco_ck)
    if _reco_hit and _reco_hit[0] > _time.monotonic():
        logger.info("[reco] cache hit farm=%s", farm_id)
        return _reco_hit[1]

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
    _resp = RecommendationsResponse(
        farm_id=farm_id,
        updated_at=_now(),
        recommendations=items,
    )
    _RECO_CACHE[_reco_ck] = (_time.monotonic() + _RECO_TTL, _resp)
    return _resp


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
# GET /journal/env  — 환경 수동 입력 이력
# ---------------------------------------------------------------------------

@router.get("/journal/env", summary="환경 수동 입력 이력 조회")
def get_env_journal(
    farm_id: str,
    limit: int = Query(20, ge=1, le=100, description="반환할 최대 레코드 수"),
):
    """농장의 수동 환경 입력 이력을 최신순으로 반환합니다."""
    history = persistence.get_env_history(farm_id, limit=limit)
    return {"farm_id": farm_id, "records": history, "total": len(history)}


# ---------------------------------------------------------------------------
# GET /journal/advisory  — 해당 농장 AI 권고 이력 (농장주용)
# ---------------------------------------------------------------------------

@router.get("/journal/advisory", summary="농장 AI 권고 이력 조회")
def get_advisory_journal(
    farm_id: str,
    limit: int = Query(30, ge=1, le=200, description="반환할 최대 건수"),
):
    """농장별 AI 권고 이력을 최신순으로 반환합니다 (농장주 계정 전용)."""
    try:
        from pipeline.crop_advisor import load_history
        entries = load_history(limit=limit, farm_id=farm_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"권고 이력 조회 실패: {e}")
    return {"farm_id": farm_id, "entries": entries, "total": len(entries)}


# ---------------------------------------------------------------------------
# GET /environment
# ---------------------------------------------------------------------------

@router.get("/environment", response_model=EnvironmentResponse)
def get_environment(farm_id: str):
    meta   = _require_farm(farm_id)
    iot_ok = meta["iot_available"]

    # ── 실내 환경 변수 ──────────────────────────────────────────────────────────
    _INDOOR_VARS = {"temp_internal", "humidity_int", "co2_ppm", "solar_rad", "ec_dsm", "soil_temp", "ph"}

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

    # UI 편의: flat 필드 — loadCurrentEnv() JS가 d.temp_internal 등으로 직접 접근
    flat: dict[str, float | None] = {}
    for pt in all_pts:
        flat.setdefault(pt.canonical_name, pt.value)

    # ── IoT·수동입력·ASOS 모두 없을 때 작목별 합성 시뮬레이션 값 주입 ──────────
    # (대시보드 빈 화면 방지 — 실측값 없는 신규 농가에도 참고 데이터 표시)
    _CROP_SIM: dict[str, dict[str, float]] = {
        "딸기":      {"temp_internal": 17.6, "humidity_int": 82.0, "co2_ppm": 860.0,
                      "solar_rad": 185.0, "ec_dsm": 1.3,  "soil_temp": 14.4, "ph": 6.0},
        "딸기(설향)": {"temp_internal": 17.6, "humidity_int": 82.0, "co2_ppm": 860.0,
                      "solar_rad": 185.0, "ec_dsm": 1.3,  "soil_temp": 14.4, "ph": 6.0},
        "방울토마토": {"temp_internal": 25.3, "humidity_int": 67.0, "co2_ppm": 1120.0,
                      "solar_rad": 490.0, "ec_dsm": 2.9,  "soil_temp": 21.2, "ph": 6.2},
        "완숙토마토": {"temp_internal": 23.5, "humidity_int": 68.0, "co2_ppm": 950.0,
                      "solar_rad": 480.0, "ec_dsm": 2.8,  "soil_temp": 20.0, "ph": 6.2},
        "오이":      {"temp_internal": 23.0, "humidity_int": 76.0, "co2_ppm": 850.0,
                      "solar_rad": 320.0, "ec_dsm": 2.0,  "soil_temp": 19.0, "ph": 6.0},
        "파프리카":  {"temp_internal": 22.0, "humidity_int": 70.0, "co2_ppm": 900.0,
                      "solar_rad": 350.0, "ec_dsm": 2.5,  "soil_temp": 18.5, "ph": 6.1},
        "참외":      {"temp_internal": 25.0, "humidity_int": 65.0, "co2_ppm": 800.0,
                      "solar_rad": 400.0, "ec_dsm": 2.2,  "soil_temp": 22.0, "ph": 6.3},
    }
    _sim_needed = not any(flat.get(k) for k in ("temp_internal", "humidity_int", "co2_ppm"))
    if _sim_needed:
        crop_key = meta.get("crop", "딸기")
        _sim_vals = _CROP_SIM.get(crop_key, _CROP_SIM["딸기"])
        flat.update(_sim_vals)
        # in-memory 환경값으로도 등록 (recommendations 등 동일 흐름에서 활용)
        if farm_id not in _FARM_ENV:
            _FARM_ENV[farm_id] = dict(_sim_vals)
        # indoor 섹션도 합성값으로 채워서 UI 표시
        indoor_pts = [
            EnvPoint(canonical_name=name, value=round(val, 2),
                     unit=_ENV_UNITS.get(name, ""), quality_tag="SIMULATED", imputed=True)
            for name, val in _sim_vals.items()
        ]
        indoor_section = EnvironmentSection(
            source="simulated", label_ko="환경 참고값 (작목 표준 시뮬레이션)",
            editable=True, has_data=True, measurements=indoor_pts,
        )
        all_pts = indoor_pts + outdoor_pts

    # 이상 감지 결과 — loadEnvAnomalies() JS가 d.alerts 로 접근
    from api.services.anomaly_detector import detect_anomalies
    anomaly_list: list[dict] = []
    if flat:
        try:
            results = detect_anomalies(
                crop_ko=meta.get("crop", "딸기"),
                env_values={k: v for k, v in flat.items() if v is not None},
            )
            for r in results:
                anomaly_list.append({
                    "variable":      r.variable,
                    "variable_ko":   r.variable_ko,
                    "current_value": r.current_value,
                    "unit":          r.unit,
                    "severity":      r.severity,
                    "message_ko":    r.message_ko,
                })
        except Exception:
            pass

    # 제어 모드: FarmTier → JS pill 문자열
    _tier_to_mode = {
        FarmTier.MANUAL:    "advisory",
        FarmTier.SEMI_AUTO: "approval",
        FarmTier.AUTO:      "full_auto",
    }
    farm_tier = meta.get("tier", FarmTier.MANUAL)
    ctrl_mode = _tier_to_mode.get(farm_tier, "advisory")
    fail_safe = "ok" if iot_ok else "degraded"

    return EnvironmentResponse(
        farm_id=farm_id,
        updated_at=_now(),
        iot_available=iot_ok,
        indoor=indoor_section,
        outdoor=outdoor_section,
        measurements=all_pts,
        # flat 편의 필드
        temp_internal=flat.get("temp_internal"),
        humidity_int=flat.get("humidity_int"),
        co2_ppm=flat.get("co2_ppm"),
        solar_rad=flat.get("solar_rad"),
        ec_dsm=flat.get("ec_dsm"),
        soil_temp=flat.get("soil_temp"),
        ph=flat.get("ph"),
        timestamp=_now().isoformat(),
        # 이상 감지
        alerts=anomaly_list,
        # 제어 모드 및 Fail-safe
        control_mode=ctrl_mode,
        failsafe_status=fail_safe,
    )


# ---------------------------------------------------------------------------
# GET /environment/weather  — 기상청 ASOS 외부 기상 원본
# ---------------------------------------------------------------------------

@router.get("/environment/weather")
def get_weather(farm_id: str):
    """기상청 ASOS 최근 1일 외부 기상 + 단기예보 3일 요약 반환.

    - asos: 전일 실측 (온도·습도·일사량·토양온도·풍속)
    - forecast: 향후 3일 단기예보 (최고/최저기온·강수확률·하늘상태·일사량 추정)
    """
    _require_farm(farm_id)
    try:
        wx  = get_weather_summary(farm_id)
        fcst = get_forecast_summary(farm_id)
        return {
            "farm_id":        farm_id,
            "updated_at":     _now(),
            # ── ASOS 실황 ──────────────────────────────────────────────────
            "source":         "kma_asos",
            "obs_date":       wx.get("obs_date"),
            "station_id":     wx.get("station_id"),
            "temp_external":  wx.get("temp_external"),
            "humidity_ext":   wx.get("humidity_ext"),
            "solar_rad_est":  wx.get("solar_rad_est"),
            "soil_temp":      wx.get("soil_temp"),
            "wind_speed_ext": wx.get("wind_speed_ext"),
            # ── 단기예보 3일 ───────────────────────────────────────────────
            "forecast":       fcst,
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"기상청 API 오류: {exc}")


@router.get("/environment/forecast")
def get_forecast(farm_id: str):
    """기상청 단기예보 3일 일별 상세 반환 (캐시 3시간).

    각 일별 dict:
      date, temp_max, temp_min, temp_avg, humidity_avg,
      precip_prob, sky_label, rain_expected, solar_est_wm2
    """
    _require_farm(farm_id)
    try:
        days = get_forecast_3day(farm_id)
        return {
            "farm_id":    farm_id,
            "updated_at": _now(),
            "days":       days,
            "count":      len(days),
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"단기예보 오류: {exc}")


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

    # 단기예보 3일 평균 외부온도 → 하우스 내부온도 추정 보정
    # (외부온도 + 내외 온도차 평균 3°C 반영) → GDD 계산에 사용
    try:
        fcst_days = get_forecast_3day(farm_id)
        if fcst_days:
            ext_temps = [d["temp_avg"] for d in fcst_days if d.get("temp_avg") is not None]
            if ext_temps:
                # 하우스는 외부보다 평균 +3°C 높다고 가정 (겨울 +5, 여름 +1 평균)
                fcst_temp_avg = sum(ext_temps) / len(ext_temps)
                indoor_offset = 3.0
                # 현재 IoT 실내온도와 평균 사용 (50:50 가중치)
                temp_now = round((temp_now + (fcst_temp_avg + indoor_offset)) / 2, 1)
    except Exception:
        pass  # 예보 실패 시 현재 IoT 온도만 사용

    days_to_harvest = estimate_harvest_days(crop, temp_now)
    if days_to_harvest >= 999:
        days_to_harvest = 45   # 온도 너무 낮은 예외 상황 기본값

    predicted_date = (date.today() + timedelta(days=days_to_harvest)).isoformat()
    yield_m2       = get_yield_kg_m2(crop)
    area           = meta["area_m2"]
    total_kg       = round(yield_m2 * area, 1)
    # 기본값 초기화 — LegacyAdapter/M2 블록 실패 시 NameError 방지
    confidence     = 0.60
    model_used     = "stats_fallback"

    # ── 생육단계(growth_stage_ko) / 정식 경과일 계산 ──────────────────────
    _plant_month_raw = meta.get("plant_month") or meta.get("season_start")
    _days_since = None
    _growth_stage_ko = None
    try:
        if _plant_month_raw:
            _pm = int(str(_plant_month_raw).split("-")[0])  # "3" 또는 "2024-03" 형식 지원
            _now_month = date.today().month
            _months_elapsed = (_now_month - _pm) % 12
            _days_since = _months_elapsed * 30
        if _days_since is None:
            # 정식 정보 없으면 days_to_harvest 역산으로 추정
            _crop_total_days = {"딸기": 150, "완숙토마토": 120, "방울토마토": 90,
                                "파프리카": 180, "참외": 90, "오이": 60}.get(crop, 120)
            _days_since = max(0, _crop_total_days - days_to_harvest)
        # 생육단계 결정
        _total_est = {"딸기": 150, "완숙토마토": 120, "방울토마토": 90,
                      "파프리카": 180, "참외": 90, "오이": 60}.get(crop, 120)
        _ratio = _days_since / _total_est
        if days_to_harvest <= 14:
            _growth_stage_ko = "수확기"
        elif _ratio < 0.20:
            _growth_stage_ko = "초기 (정식기)"
        elif _ratio < 0.50:
            _growth_stage_ko = "영양생장기"
        elif _ratio < 0.75:
            _growth_stage_ko = "착과·개화기"
        else:
            _growth_stage_ko = "성숙·수확기"
    except Exception:
        _growth_stage_ko = "생육중"

    # ── LegacyModelAdapter (RDA 5000행, R²≥0.75) — 딸기 등 우선 사용 ─────
    try:
        from api.engine.legacy_model_adapter import (
            LegacyModelAdapter, build_iot_features_from_env,
        )
        from datetime import datetime as _dt
        _la = LegacyModelAdapter()
        if _la.supports(crop):
            _plant_m = meta.get("plant_month")
            _days_elapsed = (
                (_dt.now().month - int(_plant_m)) % 12 * 30
                if _plant_m else 75
            )
            _iot_feats = build_iot_features_from_env(
                env or {},
                month=_dt.now().month,
                days_since_planting=_days_elapsed,
                crop_ko=crop,
            )
            _la_res = _la.predict(crop, _iot_feats)
            if _la_res["cv_r2"] >= 0.60:
                yield_m2   = _la_res["yield_per_m2"]
                total_kg   = round(yield_m2 * area, 1)
                confidence = min(0.92, _la_res["cv_r2"])
                model_used = "rda_legacy"
                logger.info("[harvest] LegacyAdapter 사용 crop=%s R²=%.3f y=%.3f kg/m²",
                            crop, _la_res["cv_r2"], yield_m2)
    except Exception as _la_err:
        logger.debug("[harvest] LegacyAdapter 미사용: %s", _la_err)

    # ── M2 모델 실제 Q10/Q90 신뢰구간 ──────────────────────────────────────
    env_feat_for_bounds = {
        "temp_internal_mean": float((env or {}).get("temp_internal", 20.0)),
        "humidity_int_mean":  float((env or {}).get("humidity_int",  70.0)),
        "co2_ppm_mean":       float((env or {}).get("co2_ppm",      800.0)),
        "solar_rad_mean":     float((env or {}).get("solar_rad",    100.0)),
        "soil_temp_mean":     float((env or {}).get("soil_temp",     18.0)),
    }
    bounds = predict_yield_bounds(crop, env_feat_for_bounds)
    if bounds["has_bounds"]:
        # M2 모델 Q10/Q90 → 면적 적용 (kg/m² × m²)
        yield_q10 = round(bounds["yield_lower"] * area, 1)
        yield_q90 = round(bounds["yield_upper"] * area, 1)
        # M2 점예측이 있으면 total_kg도 업데이트
        if bounds["yield_per_m2"]:
            total_kg  = round(bounds["yield_per_m2"] * area, 1)
            yield_m2  = bounds["yield_per_m2"]
        confidence = 0.82
        model_used = "m2_quantile"
    else:
        # 폴백: stats 기반 ±20% (M2 미학습 작목)
        yield_q10  = round(total_kg * 0.80, 1)
        yield_q90  = round(total_kg * 1.20, 1)
        confidence = 0.60
        model_used = "stats_fallback"

    # ── confidence_grade: MAPE 기반 신뢰도 등급 (농가 화면 표시용) ───────────────
    import json as _json
    from pathlib import Path as _Path
    _crop_cfg = CROP_CONFIGS.get(crop)
    _crop_en  = _crop_cfg.crop_en if _crop_cfg else "strawberry"
    _meta_path = _Path("models/artifacts") / _crop_en / "stage2_meta.json"
    _model_mape = None
    try:
        if _meta_path.exists():
            _meta = _json.loads(_meta_path.read_text(encoding="utf-8"))
            _model_mape = _meta.get("mape")
    except Exception:
        pass

    if _model_mape is not None and _model_mape <= 25.0:
        _conf_grade = "높음 (±25% 이내)"
        _mape_note  = f"예측 오차 약 ±{_model_mape:.0f}% — 의사결정에 활용 가능"
    elif _model_mape is not None and _model_mape <= 45.0:
        _conf_grade = "보통 (±45% 이내)"
        _mape_note  = f"예측 오차 약 ±{_model_mape:.0f}% — 추세 참고용으로 활용"
    else:
        _conf_grade = "낮음 (참고용)"
        _mape_note  = (f"예측 오차 약 ±{_model_mape:.0f}% — 데이터 추가 수집 필요"
                       if _model_mape else "모델 정보 없음")

    # M2 gate_pass 및 model_confidence 계산
    _m2_gate = None
    _m2_conf = None
    if _model_mape is not None:
        _mape_f = float(_model_mape)
        # gate: MAPE ≤ 35% AND cv_r2 ≥ 0.0 (일관 기준)
        try:
            _cv_r2 = float(_meta.get("cv_r2_mean", 0.0)) if _meta else 0.0
        except Exception:
            _cv_r2 = 0.0
        _m2_gate = (_mape_f <= 35.0) and (_cv_r2 >= 0.0)
        # stage2_meta.json의 gate_passed를 authoritative source로 사용
        try:
            if _meta_path.exists():
                _meta2 = _json.loads(_meta_path.read_text(encoding="utf-8"))
                _stored_gate = _meta2.get("gate_passed")
                if _stored_gate is not None:
                    _stored_r2   = float(_meta2.get("cv_r2_mean", 0.0))
                    _m2_gate = bool(_stored_gate) and (_stored_r2 >= 0.0)
        except Exception:
            pass
        _m2_conf = round(max(0.0, min(0.95, 1.0 - _mape_f / 100.0)), 3)

    return HarvestForecast(
        farm_id=farm_id,
        updated_at=_now(),
        predicted_date=predicted_date,
        predicted_yield_kg_m2=round(yield_m2, 2),
        confidence=confidence,
        # UI 편의 필드
        yield_kg_forecast=total_kg,
        yield_q10=yield_q10,
        yield_q90=yield_q90,
        days_to_harvest=days_to_harvest,
        crop_ko=crop,
        area_m2=area,
        growth_stage_ko=_growth_stage_ko,
        days_since_planting=_days_since,
        # Phase 42: 신뢰도 등급
        confidence_grade=_conf_grade,
        model_mape_pct=_model_mape,
        mape_note=_mape_note,
        # Phase 45+: M2 게이트 통과 여부
        model_gate_pass=_m2_gate,
        model_confidence=_m2_conf,
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# GET /market/price-history  — KAMIS 도매가격 이력 (최근 30일)
# ---------------------------------------------------------------------------

@router.get("/market/price-history", summary="KAMIS 도매가격 이력 (최근 30일)")
def get_price_history(
    farm_id: str,
    days: int = Query(30, ge=7, le=90, description="조회 일수 (기본 30일)"),
    crop_ko: Optional[str] = Query(None, description="조회 작목 (미지정 시 농장 기본 작목)"),
):
    """KAMIS 캐시에서 최근 N일 도매가격 이력을 반환합니다.

    - KAMIS API 키가 설정된 경우 실시간 수집 데이터 반영
    - 키 미설정 시 price_stats.json 기준 추정값 표시
    - 반환: {crop, history: [{date, price_krw_kg, source}], stats: {avg, min, max, latest}}
    """
    meta = _require_farm(farm_id)
    crop = crop_ko or meta.get("crop", "딸기")   # 쿼리 파라미터 우선, 없으면 농장 기본 작목

    from pipeline.kamis_fetcher import load_cache, get_price_with_fallback
    from api.data.stats_loader import get_price_krw_kg
    from datetime import timedelta

    cache   = load_cache()
    history_raw: dict[str, float] = cache.get("history", {}).get(crop, {})
    source  = cache.get("source", "rda_static")

    # 요청 기간 필터
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    history_filtered = {
        d: p for d, p in sorted(history_raw.items())
        if d >= cutoff
    }

    # KAMIS 이력이 부족하면 price_stats 기준 추정값으로 채움
    stats_price = get_price_krw_kg(crop)
    if len(history_filtered) < 3:
        # 지난 N일 날짜 생성 + stats 단가로 채움 (실시간 API 미사용 환경 대비)
        today_obj = date.today()
        history_filtered = {
            (today_obj - timedelta(days=i)).isoformat(): round(stats_price, 0)
            for i in range(days - 1, -1, -1)
        }
        source = "rda_static_estimated"

    records = [
        {"date": d, "price_krw_kg": round(p, 0), "source": source}
        for d, p in sorted(history_filtered.items())
    ]

    prices = [r["price_krw_kg"] for r in records]
    stats  = {
        "avg":    round(sum(prices) / len(prices), 0) if prices else 0,
        "min":    min(prices) if prices else 0,
        "max":    max(prices) if prices else 0,
        "latest": prices[-1] if prices else 0,
    }

    # 추세 (최근 7일 평균 vs 전 7일 평균)
    trend = "flat"
    if len(prices) >= 14:
        recent_avg = sum(prices[-7:]) / 7
        prev_avg   = sum(prices[-14:-7]) / 7
        if prev_avg:
            change_pct = (recent_avg - prev_avg) / prev_avg * 100
            trend = "up" if change_pct > 2 else ("down" if change_pct < -2 else "flat")

    logger.info("[price_history] farm=%s crop=%s days=%d records=%d source=%s",
                farm_id, crop, days, len(records), source)
    return {
        "farm_id":   farm_id,
        "crop":      crop,
        "days":      days,
        "source":    source,
        "history":   records,
        "stats":     stats,
        "trend":     trend,
    }


# GET /revenue
# ---------------------------------------------------------------------------

@router.get("/revenue", response_model=RevenueResponse)
def get_revenue(farm_id: str):
    meta     = _require_farm(farm_id)
    crop     = meta.get("crop", "딸기")
    area     = meta["area_m2"]

    # 실데이터 단가: KAMIS 캐시 → stats_loader 폴백
    from pipeline.kamis_fetcher import get_price_with_fallback
    _price_info = get_price_with_fallback(crop)
    price       = _price_info["price_krw_kg"]
    _price_src  = _price_info["source"]     # "kamis_cache" | "rda_static"

    # ── M2 수확량 예측 (confidence-weighted blending 포함) ───────────────────
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

    # M2 직접 호출 → yield_kg_total + gate_pass + mape_cv
    from models.m2_yield import predict_yield as _m2_predict
    _m2_result    = _m2_predict(crop, env_feat, area_m2=area, farm_id=farm_id)
    _m2_yield_kg  = _m2_result.get("yield_kg_total", 0.0)
    _m2_yield_m2  = _m2_result.get("yield_kg_m2", 0.0)
    _m2_mape      = float(_m2_result.get("mape_cv", 99.0))
    _m2_gate      = _m2_result.get("gate_pass", None)
    _m2_src       = _m2_result.get("source", "stub")
    # 신뢰도 = 1 - MAPE/100 (0 이상, 최대 0.95)
    _m2_conf      = round(max(0.0, min(0.95, 1.0 - _m2_mape / 100.0)), 3)

    # ── ML 모델 예측 (없으면 통계 기반 폴백) ──────────────────────────────────
    ml_rev_pm2 = predict_revenue_per_m2(crop, env_feat, month=_cur_month)
    model_meta = get_model_meta(crop)

    if ml_rev_pm2 is not None and ml_rev_pm2 > 0:
        # ML 예측값: 원/m²/월 → 시즌 전체 매출
        # ml_rev_pm2는 월별 단가이므로 season_months를 곱해 시즌 총 매출로 환산
        from api.services.model_loader import _SEASON_MONTHS as _sm_map, normalize_crop as _nc
        _season_m = _sm_map.get(_nc(crop), 8)
        revenue      = ml_rev_pm2 * area * _season_m
        revenue_src  = "ml_model"
        logger.info(
            "[get_revenue] farm=%s crop=%s ML예측 %.0f원/m²/월 × %.0fm² × %d개월 = %.0f원",
            farm_id, crop, ml_rev_pm2, area, _season_m, revenue,
        )
    elif _m2_yield_kg > 0:
        # M2 수확량 × 단가 → 매출 (gate 통과/미통과 무관, blending 이미 적용)
        revenue     = _m2_yield_kg * price
        revenue_src = "m2_yield_x_price"
        logger.info(
            "[get_revenue] farm=%s crop=%s M2×가격 yield=%.0fkg × %.0f원/kg = %.0f원",
            farm_id, crop, _m2_yield_kg, price, revenue,
        )
    else:
        # 통계 폴백: 수확량 × 단가 × 면적
        _stat_yield_m2 = get_yield_kg_m2(crop)
        _m2_yield_kg   = _stat_yield_m2 * area
        _m2_yield_m2   = _stat_yield_m2
        revenue        = _m2_yield_kg * price
        revenue_src    = "stats_fallback"
        logger.info(
            "[get_revenue] farm=%s crop=%s 통계폴백 yield=%.2f kg/m² → %.0f원",
            farm_id, crop, _stat_yield_m2, revenue,
        )

    # 비용: _compute_costs 상세 항목 합산 (실단가 반영)
    cb   = _compute_costs(farm_id)
    cost = cb.total_cost_krw

    _profit          = round(revenue - cost, 0)
    _profit_margin   = round((_profit / revenue * 100) if revenue else 0.0, 1)

    return RevenueResponse(
        farm_id=farm_id,
        updated_at=_now(),
        kamis_price_krw_kg=round(price, 0),
        predicted_revenue_krw=round(revenue, 0),
        predicted_cost_krw=round(cost, 0),
        predicted_profit_krw=_profit,
        # UI 별칭
        price_krw_kg=round(price, 0),
        revenue_krw=round(revenue, 0),
        cost_krw=round(cost, 0),
        price_source=_price_src,                  # "kamis_cache" | "rda_static"
        crop_ko=crop,
        # 소득 예측 상세
        yield_kg_forecast=round(_m2_yield_kg, 1),
        yield_kg_m2=round(_m2_yield_m2, 4),
        model_confidence=_m2_conf,
        model_gate_pass=_m2_gate,
        revenue_source=revenue_src,
        area_m2=area,
        profit_margin_pct=_profit_margin,
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
    base_env = {**(_FARM_ENV.get(farm_id) or _FARM_ENV.get("farm_001") or {}), **current_env}

    # 가상 환경값: 현재값 위에 body 값 덮어쓰기
    hypo_env = {**base_env, **body.model_dump(exclude_none=True)}

    _cache_evict()
    _wi_ck = _mk_cache_key({"farm_id": farm_id, "hypo": hypo_env, "crop": crop, "month": month})
    _wi_hit = _WHATIF_CACHE.get(_wi_ck)
    if _wi_hit and _wi_hit[0] > _time.monotonic():
        logger.info("[whatif] cache hit farm=%s", farm_id)
        return _wi_hit[1]

    baseline_rev, src  = _predict(base_env,  crop, area, month)
    whatif_rev,   _    = _predict(hypo_env,  crop, area, month)
    delta              = whatif_rev - baseline_rev
    delta_pct          = (delta / baseline_rev * 100) if baseline_rev else 0.0

    logger.info(
        "[whatif] farm=%s crop=%s base=%.0f whatif=%.0f delta=%.0f",
        farm_id, crop, baseline_rev, whatif_rev, delta,
    )
    # yield_kg_forecast: revenue / price 역산
    _price = get_price_krw_kg(crop) or 1.0
    _yield_est = round(whatif_rev / _price, 1) if _price and whatif_rev else None

    _wi_result = WhatIfResult(
        baseline_revenue_krw=round(baseline_rev),
        whatif_revenue_krw=round(whatif_rev),
        delta_krw=round(delta),
        delta_pct=round(delta_pct, 2),
        confidence=0.75 if src == "ml_model" else 0.5,
        model_used=src,
        # UI 별칭
        profit_gain_krw=round(delta),
        revenue_gain_krw=round(delta),
        revenue_krw=round(whatif_rev),
        yield_kg_forecast=_yield_est,
    )
    _WHATIF_CACHE[_wi_ck] = (_time.monotonic() + _WHATIF_TTL, _wi_result)
    return _wi_result


# ---------------------------------------------------------------------------
# POST /whatif/multi  — 다중 시나리오 비교 (Pro 전용)
# ---------------------------------------------------------------------------

@router.post("/whatif/multi", response_model=WhatIfMultiResult)
def whatif_multi(farm_id: str, body: WhatIfMultiInput):
    """여러 환경 시나리오를 동시에 비교하여 최적 조합을 찾습니다.

    - 최대 10개 시나리오 지원
    - 각 시나리오는 현재 환경값에서 지정된 변수만 교체 (unspecified = 현재값 유지)
    - 응답에 수익 기준 rank 포함 (1=최고)
    """
    import datetime as _dt
    meta   = _require_farm(farm_id)
    crop   = meta.get("crop", "딸기")
    area   = meta["area_m2"]
    month  = _dt.date.today().month

    current_env = _get_env(farm_id)
    base_env    = {**(_FARM_ENV.get(farm_id) or _FARM_ENV.get("farm_001") or {}), **current_env}

    _cache_evict()
    _wm_ck = _mk_cache_key({
        "farm_id": farm_id, "crop": crop, "month": month,
        "scenarios": [s.model_dump() for s in body.scenarios],
    })
    _wm_hit = _WHATIF_CACHE.get(_wm_ck)
    if _wm_hit and _wm_hit[0] > _time.monotonic():
        logger.info("[whatif_multi] cache hit farm=%s", farm_id)
        return _wm_hit[1]

    # 베이스라인 매출
    baseline_rev, baseline_src = _predict(base_env, crop, area, month)

    results: list[WhatIfScenarioResult] = []
    for sc in body.scenarios:
        sc_dict   = sc.model_dump(exclude={"label"}, exclude_none=True)
        hypo_env  = {**base_env, **sc_dict}
        rev, src  = _predict(hypo_env, crop, area, month)
        delta     = rev - baseline_rev
        delta_pct = (delta / baseline_rev * 100) if baseline_rev else 0.0
        results.append(WhatIfScenarioResult(
            label=sc.label,
            whatif_revenue_krw=round(rev),
            delta_krw=round(delta),
            delta_pct=round(delta_pct, 2),
            confidence=0.75 if src == "ml_model" else 0.5,
            model_used=src,
            rank=0,   # 정렬 후 채움
        ))

    # 수익 순위 정렬
    results.sort(key=lambda r: r.whatif_revenue_krw, reverse=True)
    for i, r in enumerate(results):
        r.rank = i + 1

    best = results[0]
    logger.info(
        "[whatif_multi] farm=%s crop=%s scenarios=%d best='%s' delta=%.0f",
        farm_id, crop, len(results), best.label, best.delta_krw,
    )
    _wm_result = WhatIfMultiResult(
        farm_id=farm_id,
        baseline_revenue_krw=round(baseline_rev),
        scenarios=results,
        best_label=best.label,
        best_delta_krw=round(best.delta_krw),
    )
    _WHATIF_CACHE[_wm_ck] = (_time.monotonic() + _WHATIF_TTL, _wm_result)
    return _wm_result


# _predict 헬퍼: whatif / whatif_multi 공용
def _predict(env: dict, crop: str, area: float, month: int) -> tuple[float, str]:
    feat   = _env_to_feat(env, crop)
    ml_rev = predict_revenue_per_m2(crop, feat, month=month)
    if ml_rev is not None and ml_rev > 0:
        return ml_rev * area, "ml_model"
    from api.data.stats_loader import get_yield_kg_m2
    yield_m2   = get_yield_kg_m2(crop)
    price      = get_price_krw_kg(crop)
    temp_bonus = max(0.0, (env.get("temp_internal", 20.0) - 20.0) * 0.01)
    return (yield_m2 + temp_bonus) * price * area, "stats_fallback"


# ---------------------------------------------------------------------------
# GET /costs  — 자원별 비용 분석
# ---------------------------------------------------------------------------

def _compute_costs(farm_id: str) -> CostBreakdownResponse:
    """
    비용 계산 공통 로직.
    _MANUAL_COSTS[farm_id] 에 실제값이 있으면 해당 항목 우선 사용,
    없으면 _RESOURCE_COSTS 기본값 사용.
    """
    # farm_id가 _RESOURCE_COSTS에 없으면 farm_001 기본값 사용 (면적은 실제 메타에서 가져옴)
    rc   = _RESOURCE_COSTS.get(farm_id) or _RESOURCE_COSTS.get("farm_001") or {}
    mc   = persistence.get_manual_cost(farm_id)
    # _FARM_META: _require_farm()이 이미 호출된 이후이므로 farm_id 키가 존재
    meta = _FARM_META.get(farm_id) or _FARM_META.get("farm_001", {})
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

    def _item(category: str, label_ko: str, amount: float, unit_label: str, is_manual: bool) -> CostItem:
        return CostItem(
            category=category, label_ko=label_ko, label=label_ko,
            amount_krw=round(amount), unit_label=unit_label,
            pct_of_total=pct(amount), is_manual=is_manual,
        )

    items = [
        _item("electricity", "전기료",    elec,  _elec_label(),  elec_manual),
        _item("water",       "용수비",    water, _water_label(), water_manual),
        _item("heating",     "난방비",    heat,  _heat_label(),  heat_manual),
        _item("labor",       "인건비",    labor, _labor_label(), labor_manual),
        _item("nutrients",   "영양제·비료", nutr,
              "실제입력" if nutr_manual else f"{rc['nutrients_krw_day']:,.0f}원/일 × 30일",
              nutr_manual),
        _item("pesticides",  "농약·방제",  pest,
              "실제입력" if pest_manual else f"{rc['pesticides_krw_day']:,.0f}원/일 × 30일",
              pest_manual),
    ]

    return CostBreakdownResponse(
        farm_id=farm_id,
        updated_at=_now(),
        items=items,
        total_cost_krw=round(total),
        total_krw=round(total),           # UI 별칭
        cost_per_m2=round(total / max(meta["area_m2"], 1.0), 1),
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
    crop   = meta.get("crop", "작물")
    alerts = _detect_alerts(farm_id, env, crop_ko=crop) if env else []
    area   = float(meta.get("area_m2") or 1000.0)  # 0/None 기본값 방지

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

    # ── 온도·환경 종합 ────────────────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["온도", "기온", "더워", "추워", "냉방", "난방", "환경", "어때", "현황"]):
        referenced.append("environment")
        def _ev(k):
            v = env.get(k)
            v = v.get("value", v) if isinstance(v, dict) else v
            return v if isinstance(v, (int, float)) else None
        _t, _h, _c, _v = _ev("temp_internal"), _ev("humidity_int"), _ev("co2_ppm"), _ev("vpd")
        _f = lambda v, u="", d=1: (f"{v:.{d}f}{u}" if isinstance(v, (int, float)) else "—")
        return ChatResponse(
            reply=f"🌡️ {crop} 실내 환경 현황\n"
                  f"온도 {_f(_t,'°C')} · 습도 {_f(_h,'%',0)} · CO₂ {_f(_c,'ppm',0)} · VPD {_f(_v,' kPa',2)}\n\n"
                  f"최적: 낮 18~22°C·밤 12~15°C, VPD 0.6~1.2 kPa, CO₂ 800~1,200ppm. "
                  f"VPD 1.8↑이면 증산 과다(급액 보완), 0.6↓이면 과습(환기 강화)으로 대응하세요.",
            suggestions=["VPD가 높으면?", "결로 위험 있어?", "온도 높이면 수익 얼마나 늘어?"],
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

    # ── 관수·양액 ─────────────────────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["관수", "급액", "배액", "함수율", "양액", "물 주", "물주", "ec", "ph"]):
        referenced.append("irrigation")
        _drain = _ec = None
        try:
            from api.services.irrigation_store import get_irrigation_analysis as _gia
            _summ = (_gia(farm_id, days=7) or {}).get("summary", {})
            _drain = (_summ.get("dr_pct_mean") or {}).get("latest")
            _ec    = (_summ.get("ec_drain") or {}).get("latest")
        except Exception:
            pass
        _parts = []
        if _drain is not None:
            _st = "정상(20~30%)" if 20 <= _drain <= 30 else ("부족 — 급액량↑" if _drain < 20 else "과잉 — 급액량↓")
            _parts.append(f"최근 배액률 {_drain:.1f}% → {_st}")
        if _ec is not None:
            _parts.append(f"배액 EC {_ec:.1f} dS/m (정상 3.0~4.5)")
        _body = " · ".join(_parts) if _parts else "관수 센서값이 축적되면 자동 진단합니다."
        return ChatResponse(
            reply=f"💧 {crop} 관수 진단\n{_body}\n\n"
                  f"오늘은 일사 적산(J/cm²) 기반 P1~P6 단계로 관수가 진행됩니다. "
                  f"배액률 12% 미만이면 즉시 추가 관수하고, 야간(P6)은 dry-back 10~20%가 목표입니다. "
                  f"급액 EC는 처방(Recipe) 2.5~3.5 dS/m·pH 5.5~6.5 기준입니다.",
            suggestions=["배액률 정상 범위는?", "야간 dry-back이 뭐야?", "EC 높을 때 조치는?"],
            referenced_data=["irrigation"],
        )

    # ── 에너지·전력 ───────────────────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["에너지", "전기", "전력", "요금", "난방비", "냉방비"]):
        referenced.append("energy")
        return ChatResponse(
            reply="⚡ 에너지 절감 전략\n한전 시간대별 요금 기준, 피크시간(10~17시)에 난방·LED를 20~50% 자동 감축하면 "
                  "연 350~400만원 절감이 가능합니다.\n\n"
                  "G2 환경화면의 'AI 에이전트(빠른 루프)' 카드에서 현재 피크 여부와 절감 상태를 확인하고, "
                  "축열조 활용·LED 스펙트럼 단계제어로 추가 절감하세요.",
            suggestions=["지금 피크시간이야?", "LED 스펙트럼 자동 제어란?", "이번 달 전기요금 분석"],
            referenced_data=["energy"],
        )

    # ── 작물 재배 일반 ────────────────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["재배", "생육", "성장", "관리", "방법", "tip", "팁"]):
        return ChatResponse(
            reply=f"{crop} 스마트팜 운영 핵심 포인트:\n\n"
                  f"• 일조: 하루 14~16시간 유지 (보광등 활용)\n"
                  f"• 관비: EC {_ALERT_RULES.get(farm_id, [None])[0][2] if _ALERT_RULES.get(farm_id) else '1.5~2.5'} dS/m\n"
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
    # ── 쿼터 검사 및 소비 ─────────────────────────────────────────────────────
    from api.services.billing import check_chat_quota, consume_chat_quota
    from fastapi import HTTPException
    quota = check_chat_quota(farm_id)
    if not quota["allowed"]:
        tier   = quota["tier"]
        max_q  = quota["max"]
        if max_q == 0:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"AI 채팅은 Smart 플랜 이상에서 사용 가능합니다 (현재: {tier} 플랜). "
                    "설정 탭에서 플랜 업그레이드 후 이용해 주세요. "
                    "※ 이 오류는 쿼터 소진이 아닌 플랜 미포함 항목입니다."
                ),
            )
        raise HTTPException(
            status_code=429,
            detail=f"이번 달 AI 채팅 쿼터를 모두 사용했습니다 ({quota['used']}/{max_q}회). 다음 달 초기화 또는 플랜 업그레이드 후 이용해 주세요.",
        )
    consume_chat_quota(farm_id)
    # ──────────────────────────────────────────────────────────────────────────

    # ── 티어 기반 AI 라우팅 ────────────────────────────────────────────────────
    from api.services.ai_chat import _cfg as _ai_cfg
    _api_key = _ai_cfg("ANTHROPIC_API_KEY")
    _tier    = quota.get("tier", "basic")
    _use_llm = bool(_api_key) and _tier in ("pro", "enterprise")

    if _use_llm:  # 멀티프로바이더: 키/티어 보유 시 AI 라우팅
        from api.services.ai_chat import call_ai, build_farm_context
        _meta    = _FARM_META.get(farm_id, {})
        _env     = _get_env(farm_id) or {}
        _alerts  = _detect_alerts(farm_id, _env, crop_ko=_meta.get("crop", "딸기")) if _env else []
        _ctx     = build_farm_context(farm_id, _meta, _env, _alerts)
        _history = [{"role": m.role, "content": m.content} for m in body.history]
        _result  = call_ai(
            farm_id=farm_id,
            message=body.message,
            history=_history,
            context=_ctx,
            tier=_tier,
        )
        return ChatResponse(
            reply           = _result["reply"],
            suggestions     = _result.get("suggestions", []),
            model_used      = _result.get("model_used", "claude"),
            referenced_data = _result.get("referenced_data", []),
        )

    # Smart 이하 또는 API 키 미설정 → 컨텍스트 기반 규칙형 응답(진단·역량·작황·경영전략 포함)
    try:
        from api.services.ai_chat import build_farm_context, _rule_based_reply
        _meta   = _FARM_META.get(farm_id, {})
        _env    = _get_env(farm_id) or {}
        _alerts = _detect_alerts(farm_id, _env, crop_ko=_meta.get("crop", "딸기")) if _env else []
        _ctx    = build_farm_context(farm_id, _meta, _env, _alerts)
        _r      = _rule_based_reply(body.message, _ctx)
        return ChatResponse(reply=_r["reply"], suggestions=_r.get("suggestions", []),
                            model_used=_r.get("model_used", "rule-v2"),
                            referenced_data=_r.get("referenced_data", []))
    except Exception:
        return _stub_reply(farm_id, body.message)

# ── P4 관수 데이터 수신 (관수통합관리시스템 연동) ─────────────────────────────

class IrrigationPeriod(BaseModel):
    period:     int   = Field(..., ge=1, le=6, description="구간 번호 (1=일출/첫관수, 2=오전, 3=오후, 4=일몰, 6=야간 — P5·P6 확장)")
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

    if result.errors:
        logger.warning("[irrigation] farm=%s date=%s warnings: %s",
                       farm_id, body.date, result.errors)

    summary = {}
    for rec in result.records:
        summary[rec.canonical_name] = round(rec.value, 3)

    logger.info("[irrigation] farm=%s date=%s → %d canonical records: %s",
                farm_id, body.date, len(result.records), summary)

    # ── 저장 (DB → JSON 폴백) ─────────────────────────────────────────────
    from api.services.irrigation_store import save_irrigation_day
    save_irrigation_day(farm_id, body.date, summary)

    return IrrigationResponse(
        farm_id=farm_id,
        date=body.date,
        records_saved=len(result.records),
        warnings=result.errors,
        summary=summary,
    )


# ── KMA 일사량 기반 관수 스케줄 조회 ─────────────────────────────────────────────

class IrrigationScheduleResponse(BaseModel):
    farm_id:                str
    daily_gsr_mj_m2:        Optional[float] = None
    solar_rad_avg_wm2:      Optional[float] = None
    n_irrigations:          int
    total_supply_ml:        float
    supply_per_trigger_ml:  float
    first_irrigation:       str
    last_irrigation:        str
    trigger_mj_m2:          float
    obs_date:               Optional[str]   = None
    station_id:             Optional[int]   = None
    source:                 str
    note:                   str


# ── 노지 공공데이터: 토양·필지 (흙토람/팜맵 → Mock 폴백) ──────────────────────

_REAL_SOIL_CACHE = {"loaded": False, "data": None}

def _real_soil_lookup(meta: dict):
    """흙토람 토양검정 적재분(api/data/real/soil_jeju.json)에서 농장 지역 토양특성 조회.
    sido에 '제주' 포함 시 시군구/읍면동 매칭 → 실측 ph·EC·유기물 반환. 없으면 None."""
    import json as _json
    from pathlib import Path as _P
    sido = (meta.get("sido") or "")
    if "제주" not in sido:
        return None
    if not _REAL_SOIL_CACHE["loaded"]:
        try:
            fp = _P(__file__).resolve().parents[1] / "data" / "real" / "soil_jeju.json"
            _REAL_SOIL_CACHE["data"] = _json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else None
        except Exception:
            _REAL_SOIL_CACHE["data"] = None
        _REAL_SOIL_CACHE["loaded"] = True
    db = _REAL_SOIL_CACHE["data"]
    if not db:
        return None
    sgg = (meta.get("sigungu") or "").strip()
    emd = (meta.get("emd") or meta.get("address_detail") or "").strip()
    prof = None; scope = ""
    if sgg and emd and f"{sgg} {emd}" in db.get("by_emd", {}):
        prof = db["by_emd"][f"{sgg} {emd}"]; scope = f"{sgg} {emd}"
    elif sgg and sgg in db.get("by_sigungu", {}):
        prof = db["by_sigungu"][sgg]; scope = sgg
    else:
        # 제주 농장이나 세부지역 불명 → 시군구 평균(제주시) 사용
        prof = (db.get("by_sigungu") or {}).get("제주시"); scope = "제주 평균"
    if not prof:
        return None
    # EC(dS/m) → 토양수분 프록시 매핑 불가하므로 토양특성 자체 + 검정 표본수 제공
    return {
        "farm_id": meta.get("_fid", ""), "source": "naas_soil_real",
        "region": scope,
        "soil": {"ph": prof.get("ph"), "ec_dsm": prof.get("ec"),
                 "organic_matter": prof.get("organic"), "phosphate": prof.get("phosphate"),
                 "potassium": prof.get("potassium"), "samples": prof.get("n")},
        "parcels": [],
        "note": f"흙토람 토양검정 2024 실데이터({scope} {prof.get('n')}필지 평균). 출처: {db.get('source')}",
    }


@router.get("/field/soil", summary="노지 필지별 토양특성 (흙토람 적재 실데이터 → Mock 폴백)")
def get_field_soil(farm_id: str):
    """흙토람 토양검정/토양특성을 PNU 기준 조회. 미연동 시 Mock 토양수분 반환.

    응답 source: 'naas_soil'(실데이터) | 'mock'(미연동)
    """
    import os
    _require_farm(farm_id)
    meta = _FARM_META.get(farm_id, {})
    pnu  = meta.get("pnu") or os.environ.get("DEFAULT_FIELD_PNU", "")

    from api.services.external_api_hub import naas_soil_by_pnu
    live = naas_soil_by_pnu(pnu) if pnu else None
    if live:
        return {"farm_id": farm_id, "source": "naas_soil", "pnu": pnu, "data": live.get("soil"),
                "parcels": [], "note": "흙토람 실데이터"}

    # 흙토람 실데이터 적재분(제주 토양검정 2024) — 농장 지역 매칭 시 실값 제공
    real = _real_soil_lookup(meta)
    if real:
        real["farm_id"] = farm_id
        return real

    # Mock 폴백 — 필지별 토양수분(센서 미연동)
    mock_parcels = [
        {"name": "1번 필지", "moisture": 62, "area_ha": 0.5, "soil_type": "양토", "drainage": "양호"},
        {"name": "2번 필지", "moisture": 38, "area_ha": 0.8, "soil_type": "사양토", "drainage": "약간불량"},
        {"name": "3번 필지", "moisture": 71, "area_ha": 0.4, "soil_type": "식양토", "drainage": "양호"},
        {"name": "4번 필지", "moisture": 45, "area_ha": 0.6, "soil_type": "양토", "drainage": "보통"},
    ]
    return {"farm_id": farm_id, "source": "mock", "pnu": pnu or None,
            "parcels": mock_parcels,
            "note": "실측 토양수분 센서·흙토람 미연동 (NAAS_SOIL_API_URL 설정 시 자동 전환)"}


_REAL_PARCEL_CACHE = {"loaded": False, "data": None}

def _real_parcels_lookup(meta: dict):
    """팜맵 적재분(api/data/real/parcels_jeju.json)에서 농장 지역 실 필지 조회."""
    import json as _json
    from pathlib import Path as _P
    if "제주" not in (meta.get("sido") or ""):
        return None
    if not _REAL_PARCEL_CACHE["loaded"]:
        try:
            fp = _P(__file__).resolve().parents[1] / "data" / "real" / "parcels_jeju.json"
            _REAL_PARCEL_CACHE["data"] = _json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else None
        except Exception:
            _REAL_PARCEL_CACHE["data"] = None
        _REAL_PARCEL_CACHE["loaded"] = True
    db = _REAL_PARCEL_CACHE["data"]
    if not db:
        return None
    sgg = (meta.get("sigungu") or "").strip()
    emd = (meta.get("emd") or meta.get("address_detail") or "").strip()
    rec = None; scope = ""
    if sgg and emd and f"{sgg} {emd}" in db.get("by_emd", {}):
        rec = db["by_emd"][f"{sgg} {emd}"]; scope = f"{sgg} {emd}"
    else:
        # 시군구 첫 읍면동 샘플
        for k, v in db.get("by_emd", {}).items():
            if sgg and k.startswith(sgg): rec = v; scope = k; break
    if not rec:
        # 제주 농장이나 세부지역 불일치(예: 읍면명 '한경') → 제주 첫 읍면동 샘플 폴백
        for k, v in db.get("by_emd", {}).items():
            rec = v; scope = f"{k} (제주 샘플)"; break
    if not rec:
        return None
    return {"farm_id": meta.get("_fid", ""), "source": "farmmap_real", "region": scope,
            "parcels": rec.get("parcels", []),
            "region_total": {"count": rec.get("count"), "area_ha": rec.get("total_area_ha")},
            "note": f"팜맵 농경지전자지도 2024 실데이터({scope} {rec.get('count')}필지 중 샘플). 출처: {db.get('source')}"}


@router.get("/field/parcels", summary="노지 필지 경계 (팜맵 적재 실데이터 → Mock 폴백)")
def get_field_parcels(farm_id: str):
    """팜맵 농경지전자지도 필지 조회. 미연동 시 Mock 필지 반환.

    응답 source: 'farmmap'(실데이터) | 'mock'(미연동)
    """
    import os
    _require_farm(farm_id)
    meta = _FARM_META.get(farm_id, {})
    adm  = meta.get("adm_code") or os.environ.get("DEFAULT_ADM_CODE", "")

    from api.services.external_api_hub import farmmap_parcels
    live = farmmap_parcels(adm) if adm else None
    if live:
        return {"farm_id": farm_id, "source": "farmmap", "adm": adm, "data": live.get("raw"),
                "note": "팜맵 실데이터"}

    # 팜맵 실데이터 적재분(제주 2024) — 농장 지역 매칭 시 실 필지 제공
    real = _real_parcels_lookup(meta)
    if real:
        real["farm_id"] = farm_id
        return real

    mock = [
        {"name": "1번 필지", "jimok": "전", "area_ha": 0.5, "crop": "배추"},
        {"name": "2번 필지", "jimok": "전", "area_ha": 0.8, "crop": "무"},
        {"name": "3번 필지", "jimok": "답", "area_ha": 0.4, "crop": "대파"},
        {"name": "4번 필지", "jimok": "전", "area_ha": 0.6, "crop": "양파"},
    ]
    return {"farm_id": farm_id, "source": "mock", "adm": adm or None,
            "parcels": mock,
            "note": "팜맵 미연동 (FARMMAP_API_URL 설정 시 자동 전환)"}


@router.get("/field/cluster", summary="노지 클러스터 작황 모니터링 (무센서·위성/기상 + 위치특정 이상알림)")
def get_field_cluster(farm_id: str):
    """위성 식생지수(미연동 시 프록시) + 16일 기상 스트레스로 무센서 광역 작황진단.
    클러스터(다수 필지) 평균·균일도·이상필지 + **위치특정 정량편차 이상알림(실행지시)** 반환."""
    _require_farm(farm_id)
    meta = _FARM_META.get(farm_id, {})
    region = f"{meta.get('sido','') or ''} {meta.get('sigungu','') or ''}".strip() or "-"
    # 필지 수집 (팜맵→Mock 폴백)
    adm = ""
    try:
        pr = get_field_parcels(farm_id)
        adm = pr.get("adm") or ""
        parcels = pr.get("parcels") or pr.get("data") or []
        if not isinstance(parcels, list) or not parcels:
            raise ValueError
    except Exception:
        parcels = [{"name": f"{i+1}번 필지", "crop": c, "area_ha": a}
                   for i, (c, a) in enumerate([("배추", 0.5), ("무", 0.8), ("대파", 0.4), ("양파", 0.6)])]
    # 16일 기상(무센서 스트레스)
    region_wx = None
    try:
        from api.services.extended_weather import get_extended_forecast
        region_wx = get_extended_forecast(meta.get("sido", "") or "", meta.get("sigungu", "") or "", 16)
    except Exception:
        region_wx = None
    # 토양수분(흙토람) 보정 — 있으면
    soil = None
    try:
        soil = get_field_soil(farm_id)
    except Exception:
        soil = None
    # 위성 NDVI 실측 — SATELLITE_NDVI_URL 주입 시 자동 활성(프록시→실측 전환)
    satellite_live = False
    try:
        import os as _os
        if _os.environ.get("SATELLITE_NDVI_URL"):
            from api.services.external_api_hub import satellite_ndvi
            sat = satellite_ndvi(adm or "", [p.get("name") for p in parcels])
            if sat:
                for p in parcels:
                    if p.get("name") in sat:
                        p["ndvi"] = sat[p["name"]]
                satellite_live = any("ndvi" in p for p in parcels)
    except Exception:
        satellite_live = False
    from api.services.field_cluster import build_cluster
    return build_cluster(cluster_id=farm_id, region=region, parcels=parcels,
                         region_wx=region_wx, soil=soil, satellite_live=satellite_live)


_REAL_PEST_CACHE = {"loaded": False, "data": None}

@router.get("/field/pest", summary="병해충 예찰 실발병률 (감귤 예찰조사 → 룰기반 폴백)")
def get_field_pest(farm_id: str):
    """감귤 병해충 예찰조사 적재분(api/data/real/pest_jeju.json)에서 지역 실발병률 제공.
    제주 농장 매칭 시 source='pest_survey_real', 미적재/비제주는 'none'(G5/F6 룰기반 유지)."""
    import json as _json
    from pathlib import Path as _P
    _require_farm(farm_id)
    meta = _FARM_META.get(farm_id, {})
    if "제주" not in (meta.get("sido") or ""):
        return {"farm_id": farm_id, "source": "none", "diseases": [],
                "note": "비제주 — 예찰 실데이터 없음(G5/F6 룰기반 조기경보 유지)"}
    if not _REAL_PEST_CACHE["loaded"]:
        try:
            fp = _P(__file__).resolve().parents[1] / "data" / "real" / "pest_jeju.json"
            _REAL_PEST_CACHE["data"] = _json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else None
        except Exception:
            _REAL_PEST_CACHE["data"] = None
        _REAL_PEST_CACHE["loaded"] = True
    db = _REAL_PEST_CACHE["data"]
    if not db:
        return {"farm_id": farm_id, "source": "pending_import", "diseases": [],
                "note": "예찰 parquet 적재 대기 — python scripts/import_real_pest.py 실행 시 활성화"}
    emd = (meta.get("emd") or meta.get("address_detail") or "").strip()
    rec = (db.get("by_emd") or {}).get(emd)
    diseases = (rec or {}).get("disease") if rec else db.get("overall", {})
    scope = emd if rec else "제주 평균"
    items = sorted([{"name": k, "rate_pct": v,
                     "level": "위험" if v >= 20 else "주의" if v >= 5 else "낮음"}
                    for k, v in (diseases or {}).items()], key=lambda x: -x["rate_pct"])
    return {"farm_id": farm_id, "source": "pest_survey_real", "region": scope,
            "diseases": items, "note": f"감귤 병해충 예찰조사 실발병률({scope}). 출처: {db.get('source')}"}


# ── 관수 분석 결과 조회 ────────────────────────────────────────────────────────

@router.get("/irrigation/analysis", summary="관수 품질 분석 (함수율·배액률·EC 등)")
def get_irrigation_analysis(
    farm_id: str,
    days: int = Query(7, ge=1, le=90, description="조회 기간 (일, 기본 7일)"),
):
    """POST /irrigation 으로 수신된 P4 관수 데이터의 분석 결과를 반환합니다.

    반환 항목:
    - **records**: 날짜별 wc_mean, dr_pct_mean, ec_drain, nl_pct 등
    - **summary**: 각 변수의 평균·최솟값·최댓값·최신값·상태(normal/high/low)
    - **alerts**: 정상 범위(wc 60–95%, dr 20–40%, ec 2.0–4.5 dS/m) 이탈 항목
    """
    _require_farm(farm_id)
    from api.services.irrigation_store import get_irrigation_analysis
    return get_irrigation_analysis(farm_id, days=days)


@router.get("/irrigation/schedule", response_model=IrrigationScheduleResponse,
            summary="KMA 일사량 기반 내일 관수 스케줄 예측")
def get_irrigation_schedule(
    farm_id: str,
    trigger_mj_m2: float = 2.0,
    supply_ml: float = 250.0,
    growth_stage: str = Query("mid", description="생육단계"),
):
    """KMA ASOS 전일 일사량을 기반으로 내일 권장 관수 스케줄을 계산합니다.

    Priva 일사비례 관수 방식:
    - 누적 일사량 `trigger_mj_m2` (기본 2 MJ/m²) 마다 1회 관수
    - 첫 관수: 일출 후 30분, 마지막 관수: 일몰 2시간 전

    Query params:
    - `trigger_mj_m2`: 관수 트리거 임계값 (기본 2.0 MJ/m²)
    - `supply_ml`: 1회 관수량 (ml/slab, 기본 250ml)
    """
    _require_farm(farm_id)
    meta = _FARM_META.get(farm_id, {})
    crop_ko = meta.get("crop", None)
    for _c in ["딸기", "방울토마토", "완숙토마토", "파프리카", "참외", "오이"]:
        if crop_ko and _c in crop_ko:
            crop_ko = _c
            break
    sched = get_solar_irrigation_schedule(
        farm_id,
        trigger_mj_m2=trigger_mj_m2,
        supply_ml_per_trigger=supply_ml,
        crop_ko=crop_ko,
        growth_stage=growth_stage,
    )
    return IrrigationScheduleResponse(farm_id=farm_id, **{
        k: v for k, v in sched.items()
        if k in IrrigationScheduleResponse.model_fields
    })


# ══════════════════════════════════════════════════════════════════════════════
# Priva 관수 최적화 스케줄 (전체 알고리즘)
# ══════════════════════════════════════════════════════════════════════════════

class PrivaPhase(BaseModel):
    phase_no: int
    name_ko: str
    start_hhmm: str
    end_hhmm: str
    supply_ml: float
    n_max: int
    drain_target_pct: float
    note: str = ""


class PrivaScheduleOut(BaseModel):
    farm_id: str
    crop_ko: str
    growth_stage: str
    date_str: str
    et0_mm: float
    etc_mm: float
    kc: float
    plant_size_pct: float
    transpiration_mm: float
    supply_total_ml: float
    n_irrigations: int
    phases: list[PrivaPhase]
    drain_target_pct: float
    radiation_j_cm2: float
    trigger_j_cm2: float
    pi_correction_lm2: float
    method: str
    note: str


@router.get("/irrigation/schedule/priva", response_model=PrivaScheduleOut,
            summary="Priva 증산량 기반 관수 스케줄 (ET₀·P/I·3상황)")
def get_priva_schedule(
    farm_id: str,
    growth_stage: str = Query("mid", description="생육단계 initial|dev|mid|late"),
    plant_size_pct: float = Query(100.0, ge=5, le=1000, description="작물크기계수 %"),
    drain_actual_pct: Optional[float] = Query(None, description="전날 실측 배액률 (P/I 교정용)"),
    trigger_j_cm2: float = Query(80.0, ge=10, le=500, description="적산일사 트리거 J/cm²"),
):
    """Priva 매뉴얼 5알고리즘 통합 관수 스케줄.

    1. 적산일사 트리거 — trigger_j_cm2 마다 1회 관수
    2. 증산량 기반 공급량 — ET₀×Kc×증산상수×작물크기계수
    3. P/I 배액 교정 — drain_actual_pct (자동 또는 수동) 기반 공급량 보정
    4. 3-상황 스케줄 — Phase1(아침)/Phase2(낮)/Phase3(오후)
    5. 일사 배액% 증가 — 강한 일사 → 목표 배액률 동적 상향

    drain_actual_pct 미제공 시 irrigation_store의 전일 배액률을 자동으로 사용합니다.
    P/I 적분항(I-term)은 priva_pi_store에 일간 영속화되어 연속 교정이 가능합니다.
    """
    try:
        return _get_priva_schedule_impl(
            farm_id, growth_stage, plant_size_pct, drain_actual_pct, trigger_j_cm2
        )
    except HTTPException:
        raise
    except Exception as _exc:
        logger.error("[priva] farm=%s 500 error: %s", farm_id, _exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"관수 스케줄 계산 실패: {_exc}")


def _get_priva_schedule_impl(
    farm_id: str,
    growth_stage: str,
    plant_size_pct: float,
    drain_actual_pct: Optional[float],
    trigger_j_cm2: float,
) -> "PrivaScheduleOut":
    """Priva 스케줄 계산 구현체 (예외 로깅을 위해 분리)."""
    _require_farm(farm_id)
    meta = _FARM_META.get(farm_id, {})
    crop_ko = meta.get("crop", "딸기")
    for _c in ["딸기", "방울토마토", "완숙토마토", "파프리카", "참외", "오이"]:
        if _c in crop_ko:
            crop_ko = _c
            break

    from api.services.external_api_hub import get_weather_forecast_full
    from api.services.priva_irrigation import (
        get_default_config, compute_priva_schedule, PIControllerState,
    )
    from api.services.kma_service import calc_et0_hargreaves
    from api.services.priva_pi_store import load_pi_state, save_pi_state

    # ── 기상 데이터 (KMA → Open-Meteo 폴백) ──────────────────────────────────
    wx = get_weather_forecast_full(farm_id, days=1)
    et0_mm    = float((wx.get("et0_forecast_mm") or [3.0])[0] or 3.0)
    _daily    = wx.get("daily") or {}
    _daily    = _daily if isinstance(_daily, dict) else {}
    gsr_mj    = float((_daily.get("shortwave_radiation_sum") or [12.0])[0] or 12.0)
    solar_avg = round(gsr_mj * 11.574, 1) if gsr_mj > 0 else 200.0
    try:
        from api.services.kma_service import get_latest_weather
        item = get_latest_weather(farm_id)
        if item:
            _t_max  = float(item.get("maxTa", 25) or 25)
            _t_min  = float(item.get("minTa", 15) or 15)
            _t_mean = (_t_max + _t_min) / 2
            _gsr    = float(item.get("sumGsr", 0) or 0)
            if _gsr > 0:
                gsr_mj    = _gsr
                solar_avg = round(_gsr * 11.574, 1)
                et0_mm    = calc_et0_hargreaves(_t_max, _t_min, _t_mean, _gsr)
    except Exception:
        pass

    # ── 전일 실측 배액률 자동 조회 (drain_actual_pct 미제공 시) ───────────────
    _drain_auto: Optional[float] = drain_actual_pct
    if _drain_auto is None:
        try:
            from api.services.irrigation_store import get_irrigation_analysis
            _analysis = get_irrigation_analysis(farm_id, days=1)
            _rows = _analysis.get("rows") or _analysis.get("data") or []
            if _rows:
                _latest = _rows[-1] if isinstance(_rows, list) else list(_rows.values())[-1]
                _dr = (_latest.get("dr_pct_mean") if isinstance(_latest, dict) else None)
                if _dr is not None and 0 < float(_dr) < 100:
                    _drain_auto = float(_dr)
        except Exception as _e_irr:
            logger.debug("[priva] irrigation_store 자동배액 조회 실패: %s", _e_irr)

        # irrigation_store도 없으면 PI 스토어의 마지막 값 사용
        if _drain_auto is None:
            _pi_saved = load_pi_state(farm_id)
            _drain_auto = _pi_saved.get("drain_actual_pct_last")

    # ── PI Controller 상태 복원 ───────────────────────────────────────────────
    pi_state = PIControllerState()
    if _drain_auto is not None:
        _saved = load_pi_state(farm_id)
        pi_state.i_action_lm2 = float(_saved.get("i_action_lm2", 0.0))

    cfg = get_default_config(crop_ko, growth_stage)
    cfg.plant_size_pct = plant_size_pct
    cfg.trigger_j_cm2  = trigger_j_cm2

    result = compute_priva_schedule(
        et0_mm=et0_mm,
        daily_gsr_mj_m2=gsr_mj,
        solar_avg_wm2=solar_avg if solar_avg > 50 else 200.0,
        config=cfg,
        pi_state=pi_state if _drain_auto is not None else None,
        drain_actual_pct=_drain_auto,
        date_str=str(date.today()),
    )

    # ── PI 상태 영속화 (다음날 연속 교정을 위해 저장) ────────────────────────
    save_pi_state(
        farm_id,
        i_action_lm2=pi_state.i_action_lm2,
        drain_actual_pct=_drain_auto,
        drain_target_pct=result.drain_target_pct,
    )

    return PrivaScheduleOut(
        farm_id=farm_id,
        **{k: v for k, v in result.to_dict().items() if k != "phases"},
        phases=[PrivaPhase(**ph) for ph in result.to_dict()["phases"]],
    )


# ══════════════════════════════════════════════════════════════════════════════
# 기상 예보 풀체인 (KMA + Open-Meteo ET₀)
# ══════════════════════════════════════════════════════════════════════════════

class WeatherForecastOut(BaseModel):
    farm_id: str
    source: str
    days: int
    et0_forecast_mm: list
    summary_7d: dict
    daily: dict = {}


@router.get("/environment/weather/extended", summary="장기 16일 기상예보 (Open-Meteo — ET₀·일사·재해)")
def get_extended_weather(farm_id: str, days: int = Query(16, ge=1, le=16)):
    """2주(14~16일) 일별 장기예보. 기상청 단기(~3일)·중기(~10일) 한계 보완.
    농업변수(ET₀·일사·강수확률·풍속) + 재해경보(강풍·호우·폭염·서리) 포함."""
    _require_farm(farm_id)
    meta = _FARM_META.get(farm_id, {})
    from api.services.extended_weather import get_extended_forecast
    out = get_extended_forecast(meta.get("sido", ""), meta.get("sigungu", ""), days)
    if out is None:
        return {"source": "unavailable", "days": 0, "items": [], "hazards": [],
                "note": "장기예보 일시 조회 실패 — 잠시 후 재시도"}
    return out


@router.get("/environment/weather/forecast", response_model=WeatherForecastOut,
            summary="기상 예보 + ET₀ 예측 (KMA + Open-Meteo 폴백)")
def get_weather_et0_forecast(
    farm_id: str,
    days: int = Query(7, ge=1, le=16, description="예보 일수 (최대 16일)"),
):
    """KMA ASOS → Open-Meteo(무료) 순서로 기상 예보를 조회합니다.
    Hargreaves 공식으로 일별 ET₀(증발산량)를 계산해 반환합니다.
    """
    _require_farm(farm_id)
    from api.services.external_api_hub import get_weather_forecast_full
    result = get_weather_forecast_full(farm_id, days=days)
    et0_list = result.get("et0_forecast_mm") or [3.0]
    summary  = result.get("summary_7d") or {}
    daily    = result.get("daily") or {}
    if isinstance(daily, list):
        daily = {"items": daily}
    return WeatherForecastOut(
        farm_id=farm_id,
        source=result.get("source", "unknown"),
        days=days,
        et0_forecast_mm=et0_list,
        summary_7d=summary,
        daily=daily,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 병해 위험도 보강 (M5 + EPPO + RDA)
# ══════════════════════════════════════════════════════════════════════════════

class DiseaseRiskAugmentedOut(BaseModel):
    farm_id: str
    crop: str
    m5_result: dict
    eppo_pests: list = []
    rda_pests: list = []
    api_sources: list[str] = []
    updated_at: str


@router.get("/disease-risk/augmented", response_model=DiseaseRiskAugmentedOut,
            summary="병해 위험도 보강 (M5 규칙 + EPPO DB + RDA 병해충)")
def get_disease_risk_augmented(
    farm_id: str,
    include_eppo: bool = Query(True, description="EPPO 병해충 DB 포함 여부"),
):
    """M5 환경 기반 병해 위험도에 EPPO 글로벌 병해충 DB와 RDA 농진청 정보를 추가합니다.
    M5 이미지 모델이 없을 때도 EPPO/RDA 정보로 작목별 주요 병해충을 제공합니다.
    """
    _require_farm(farm_id)
    meta = _FARM_META.get(farm_id, {})
    crop_ko = meta.get("crop", "딸기")
    for _c in ["딸기", "방울토마토", "완숙토마토", "파프리카", "참외", "오이"]:
        if _c in crop_ko:
            crop_ko = _c
            break

    env = _get_env(farm_id)
    env_snap = {
        "temp_internal": float(env.get("temp_internal", 20.0)),
        "humidity_int":  float(env.get("humidity_int", 70.0)),
        "co2_ppm":       float(env.get("co2_ppm", 800.0)),
    }

    from api.services.external_api_hub import get_disease_risk_augmented as _aug
    result = _aug(env_snap, crop_ko, include_eppo=include_eppo)

    return DiseaseRiskAugmentedOut(
        farm_id=farm_id,
        crop=crop_ko,
        m5_result=result.get("m5_result", {}),
        eppo_pests=result.get("eppo_pests", []),
        rda_pests=result.get("rda_pests", []),
        api_sources=result.get("api_sources", []),
        updated_at=_now().isoformat(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 모델 성능 매트릭스 + API 연결 상태
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/system/model-performance",
            summary="전체 ML 모델 성능 매트릭스")
def get_model_performance(farm_id: str):
    """M1~M5 모델 성능 현황 + API 연결 상태를 반환합니다."""
    _require_farm(farm_id)  # 존재 검증 (farm_id가 유효한 농장인지 확인)
    import json as _json
    from pathlib import Path

    artifacts = Path(__file__).resolve().parents[2] / "models" / "artifacts"

    def _read_meta(path: Path) -> dict:
        try:
            return _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    crops = ["strawberry", "cherry_tomato", "tomato", "paprika", "melon", "cucumber"]
    crop_ko_map = {
        "strawberry": "딸기", "cherry_tomato": "방울토마토", "tomato": "완숙토마토",
        "paprika": "파프리카", "melon": "참외", "cucumber": "오이",
    }

    m1_results, m2_results, m3_results = [], [], []

    for c in crops:
        ko = crop_ko_map.get(c, c)
        d = artifacts / c
        if not d.exists():
            continue

        # M1 생육
        m1 = _read_meta(d / "m1_meta.json")
        if m1:
            targets = m1.get("targets", {})
            for tgt, tinfo in targets.items():
                m1_results.append({
                    "crop": ko, "target": tgt,
                    "r2": round(tinfo.get("r2_ensemble", 0), 3),
                    "mae": round(tinfo.get("mae", 0), 2),
                    "n_train": tinfo.get("n_train", 0),
                    "gate_pass": tinfo.get("gate_pass", False),
                    "grade": "⭐⭐⭐" if tinfo.get("r2_ensemble", 0) >= 0.90 else
                             "⭐⭐"  if tinfo.get("r2_ensemble", 0) >= 0.75 else "⭐",
                })

        # M2 수확량 (stage2)
        m2 = _read_meta(d / "stage2_meta.json")
        if m2:
            # mape: training MAPE (gate 기준, 일관성) → cv_mape_mean은 LOYO 수치로 비정상 높음
            mape = m2.get("mape") or m2.get("cv_mape_mean") or m2.get("cv_mape") or 999
            cv_r2 = m2.get("cv_r2_mean") or m2.get("cv_r2") or 0.0
            # 현행 gate 기준(MAPE ≤ 35%)으로 재산정 — 저장된 gate_passed는 구 기준(40%)으로 세팅됐을 수 있음
            gate = float(mape) <= 35.0
            m2_results.append({
                "crop": ko,
                "mape_pct": round(float(mape), 1),
                "cv_r2": round(float(cv_r2), 3),
                "n_samples": m2.get("n_samples", m2.get("n_train", 0)),
                "gate_pass": gate,
                "grade": "⭐⭐⭐" if mape <= 15 else "⭐⭐" if mape <= 30 else "⭐",
            })

        # M3 매출 (stage3)
        m3 = _read_meta(d / "stage3_meta.json")
        if m3:
            mape = m3.get("mape", m3.get("cv_mape", 999))
            m3_results.append({
                "crop": ko,
                "mape_pct": round(float(mape), 1),
                "grade": "⭐⭐⭐" if mape <= 15 else "⭐⭐" if mape <= 20 else "⭐",
            })

    # API 연결 상태
    from api.services.external_api_hub import get_api_status_report
    api_status = get_api_status_report()

    return {
        "generated_at": _now().isoformat(),
        "m1_growth": sorted(m1_results, key=lambda x: -x["r2"]),
        "m2_yield":  sorted(m2_results, key=lambda x: x["mape_pct"]),
        "m3_revenue": sorted(m3_results, key=lambda x: x["mape_pct"]),
        "m4_cost": {"status": "parameter_based", "grade": "✅"},
        "m5_disease": {"status": "rule_based_v2_8diseases", "grade": "⚠️ 이미지모델 미구축"},
        "priva_irrigation": {"status": "active", "grade": "⭐⭐⭐ 신규"},
        "api_connections": {k: v["status"] for k, v in api_status["apis"].items()},
        "missing_guide_url": "/api/farms/{farm_id}/system/api-status",
    }



# ══════════════════════════════════════════════════════════════════════════════
# 병해 탐지 — Plant.id + NCPMS + M5 규칙기반 (4계층 폴백)
# ══════════════════════════════════════════════════════════════════════════════

class DiseaseDetectRequest(BaseModel):
    image_base64: Optional[str] = None   # base64 JPEG/PNG (없으면 환경 기반)
    region_code: str = "3600000"          # 시도 코드 (발생예보 지역)


class DiseaseDetectOut(BaseModel):
    farm_id:         str
    crop:            str
    disease:         str
    disease_ko:      str
    risk_level:      str
    score:           float
    confidence:      float
    action_ko:       str
    reasons:         list[str]
    source_chain:    list[str]
    all_risks:       list[dict]
    ncpms_forecast:  list[dict]
    ncpms_detail:    list[dict]
    updated_at:      str


@router.post("/disease/detect", response_model=DiseaseDetectOut,
             summary="병해 탐지 (Plant.id + NCPMS + M5 규칙기반 4계층)")
def detect_disease_endpoint(farm_id: str, body: DiseaseDetectRequest):
    """병해 탐지 통합 엔드포인트.

    **계층 우선순위:**
    1. Plant.id API (이미지 있을 때, PLANT_ID_API_KEY 필요)
    2. M5 환경기반 규칙 v2 (온습도·VPD 기반 8가지 병해)
    3. NCPMS 농촌진흥청 병해충 발생 예보 (보강 정보)
    4. EPPO Global Database (EU 병해충 목록)

    **키 미설정 시:** M5 규칙기반 + NCPMS(DATA_GO_KR_SERVICE_KEY) 자동 사용.

    **Plant.id 키 발급:** https://web.plant.id/ → 무료 100건/월
    """
    _require_farm(farm_id)
    meta    = _FARM_META.get(farm_id, {})
    crop_ko = meta.get("crop", "딸기")
    for _c in ["딸기", "방울토마토", "완숙토마토", "파프리카", "참외", "오이"]:
        if _c in crop_ko:
            crop_ko = _c
            break

    env = _get_env(farm_id) or {}
    env_snap = {
        "temp_internal": float(env.get("temp_internal", 20.0)),
        "humidity_int":  float(env.get("humidity_int", 70.0)),
        "co2_ppm":       float(env.get("co2_ppm", 800.0)),
        "solar_rad":     float(env.get("solar_rad", 150.0)),
    }

    # 농장 좌표 (Open-Meteo 좌표 재사용)
    from api.services.external_api_hub import _FARM_COORDS  # type: ignore
    lat, lon = _FARM_COORDS.get(farm_id, (36.5, 127.5))

    from api.services.plant_disease_service import detect_disease as _detect  # type: ignore
    result = _detect(
        env=env_snap,
        crop_ko=crop_ko,
        image_base64=body.image_base64,
        farm_lat=lat,
        farm_lon=lon,
        region_code=body.region_code,
    )

    logger.info("[disease/detect] farm=%s crop=%s disease=%s risk=%s sources=%s",
                farm_id, crop_ko, result.get("disease_ko"), result.get("risk_level"),
                result.get("source_chain"))

    return DiseaseDetectOut(
        farm_id=farm_id,
        crop=crop_ko,
        disease=result.get("disease", "healthy"),
        disease_ko=result.get("disease_ko", "이상 없음"),
        risk_level=result.get("risk_level", "none"),
        score=float(result.get("score", 0.0)),
        confidence=float(result.get("confidence", result.get("score", 0.0))),
        action_ko=result.get("action_ko", "현재 환경 유지"),
        reasons=result.get("reasons", []),
        source_chain=result.get("source_chain", []),
        all_risks=result.get("all_risks", []),
        ncpms_forecast=result.get("ncpms_forecast", []),
        ncpms_detail=result.get("ncpms_detail", []),
        updated_at=result.get("updated_at", _now().isoformat()),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 도매시장 가격 + 수확량 기준 (M3 보완 + M2 클리핑)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/market/wholesale",
            summary="도매시장 가격 + M2 수확량 기준 (aT + KAMIS + FAO + USDA)")
def get_wholesale_market(
    farm_id: str,
    days: int = Query(30, ge=7, le=90, description="조회 기간 (기본 30일)"),
    crop_ko: Optional[str] = Query(None, description="조회 작목 (미지정 시 농장 기본 작목)"),
):
    """도매시장 가격 통합 조회.

    **데이터 소스 우선순위:**
    1. aT/KAMIS 도매시장 경락가격 (DATA_GO_KR_SERVICE_KEY — 기존)
    2. FAO FAOSTAT 국제 가격 (무료, 연간 기준)
    3. stats_loader 정적 데이터 (최종 폴백)

    **M2 수확량 클리핑 기준:**
    - RDA 스마트팜 기준 (내장, 키 불필요)
    - USDA NASS 참고값 (USDA_NASS_API_KEY 선택)

    **완숙토마토 gate 미통과 보완:**
    M3 예측 오차(cv_mape=31.7%)를 실시간 도매가격으로 보정합니다.
    """
    _require_farm(farm_id)
    meta = _FARM_META.get(farm_id, {})
    crop = crop_ko or meta.get("crop", "딸기")
    for _c in ["딸기", "방울토마토", "완숙토마토", "파프리카", "참외", "오이"]:
        if _c in crop:
            crop = _c
            break

    from api.services.at_wholesale_service import get_market_data  # type: ignore
    data = get_market_data(crop, days_back=days)

    # M2 예측값 클리핑 적용 예시 (현재 수확량 예측에 바로 반영)
    from api.services.at_wholesale_service import clip_yield_prediction  # type: ignore
    yield_bounds = data.get("yield_bounds", {})

    logger.info("[market/wholesale] farm=%s crop=%s price=%.0f src=%s",
                farm_id, crop,
                data.get("price_krw_kg", 0),
                data.get("price_source", "?"))

    return {
        "farm_id":              farm_id,
        "crop":                 crop,
        "crop_ko":              crop,   # JS 편의 별칭
        "updated_at":           _now().isoformat(),
        "price_krw_kg":         data.get("price_krw_kg"),
        "price_source":         data.get("price_source"),
        "price_history":        data.get("price_history", [])[-days:],
        "wholesale_stats":      data.get("wholesale", {}),
        "fao_ref_price_krw_kg": data.get("fao_ref_price_krw_kg"),
        "m3_correction_factor": data.get("m3_correction_factor", 1.0),
        "yield_bounds":         yield_bounds,
        "yield_clipping_note":  (
            f"{crop} 수확량 합리적 범위: "
            f"{yield_bounds.get('lower_kg_m2', '?')}~{yield_bounds.get('upper_kg_m2', '?')} "
            f"kg/m²/시즌 ({yield_bounds.get('reference', 'RDA')})"
        ) if yield_bounds else "수확량 기준 없음",
        "source_chain":         data.get("source_chain", []),
        "api_guide": {
            "aT_도매가격": "DATA_GO_KR_SERVICE_KEY 기존 키 사용 중",
            "USDA_NASS": "https://quickstats.nass.usda.gov/api (무료 키 발급)",
            "FAO_FAOSTAT": "키 불필요 — 자동 연결",
        },
    }


def _cfg_check(env_var: str) -> bool:
    """환경변수 값이 실제로 있는지 확인."""
    import os
    v = os.environ.get(env_var, "")
    return bool(v) and v not in ("none", "None", "", "your_key_here")


class ActivityLog(BaseModel):
    """농가 이행 활동 로그 (To-do 완료·교육 이수·수확 입력 등)."""
    kind:   str = Field(..., description="todo|education|harvest|irrigation|disease_check")
    item:   str = Field("", max_length=200, description="활동 항목명")
    value:  Optional[float] = Field(None, description="수치값(선택)")
    detail: str = Field("", max_length=500)


def _activity_path(farm_id: str):
    from pathlib import Path as _P
    d = _P(__file__).resolve().parents[1] / "data" / "activity_logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{farm_id}.json"


@router.post("/activity", summary="이행 활동 로그 적재 (폐루프 학습 — 정책 컨설팅 사이클)")
def post_activity(farm_id: str, body: ActivityLog):
    """농가 이행 활동(To-do·교육·점검)을 서버에 적재.

    localStorage에 갇힌 이행 데이터를 서버로 끌어올려 학습 기여·이행률 집계의
    근거 자료로 축적한다. 수확/생육 실측은 /api/data/harvest·/growth 사용.
    """
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    _require_farm(farm_id)
    fp = _activity_path(farm_id)
    logs = []
    if fp.exists():
        try: logs = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: logs = []
    rec = {"ts": _dt.now(_tz.utc).isoformat(), "kind": body.kind,
           "item": body.item, "value": body.value, "detail": body.detail}
    logs.append(rec)
    # 최근 1000건 유지
    logs = logs[-1000:]
    try: fp.write_text(_json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass

    # 기여 점수 (kind별 가중)
    _pts = {"harvest": 30, "irrigation": 20, "education": 25,
            "disease_check": 15, "todo": 10}.get(body.kind, 5)
    # 이번 달 활동 집계
    _ym = rec["ts"][:7]
    month_logs = [l for l in logs if l["ts"][:7] == _ym]
    by_kind = {}
    for l in month_logs:
        by_kind[l["kind"]] = by_kind.get(l["kind"], 0) + 1

    return {
        "farm_id": farm_id, "saved": True, "kind": body.kind,
        "contribution_points": _pts,
        "month": _ym, "month_total": len(month_logs), "by_kind": by_kind,
        "note": "이행 활동이 학습 기여·이행률 집계에 반영됩니다.",
    }


@router.get("/activity/summary", summary="이행 활동 요약 (학습 기여·이행률)")
def get_activity_summary(farm_id: str):
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    _require_farm(farm_id)
    fp = _activity_path(farm_id)
    logs = []
    if fp.exists():
        try: logs = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: logs = []
    _ym = _dt.now(_tz.utc).isoformat()[:7]
    month_logs = [l for l in logs if l["ts"][:7] == _ym]
    by_kind = {}
    pts = 0
    _w = {"harvest": 30, "irrigation": 20, "education": 25, "disease_check": 15, "todo": 10}
    for l in month_logs:
        by_kind[l["kind"]] = by_kind.get(l["kind"], 0) + 1
        pts += _w.get(l["kind"], 5)
    # 최근 활동 목록 (kind 필터 지원, 최신순)
    recent = sorted(logs, key=lambda l: l.get("ts", ""), reverse=True)[:30]
    return {
        "farm_id": farm_id, "month": _ym,
        "total_activities": len(month_logs), "by_kind": by_kind,
        "contribution_points": pts, "total_lifetime": len(logs),
        "recent": recent,
    }


# ───────────────────────────────────────────────────────────────────────────
# 시설 기자재 인벤토리 + 이기종 통합 매핑 (equipment_schema.json 기반)
# ───────────────────────────────────────────────────────────────────────────
def _equipment_path(farm_id: str):
    from pathlib import Path as _P
    d = _P(__file__).resolve().parents[1] / "data" / "equipment"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{farm_id}.json"


def _checklist_path(farm_id: str):
    from pathlib import Path as _P
    d = _P(__file__).resolve().parents[1] / "data" / "diagnosis"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{farm_id}.json"


def _load_checklist(farm_id: str) -> dict:
    import json as _json
    fp = _checklist_path(farm_id)
    if fp.exists():
        try: return _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: return {}
    return {}


def _diag_history_path(farm_id: str):
    from pathlib import Path as _P
    d = _P(__file__).resolve().parents[1] / "data" / "diagnosis"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{farm_id}_history.json"


def _append_diag_snapshot(farm_id: str, consultant: str = "") -> dict:
    """현재 진단을 스냅샷으로 누적(같은 날짜는 갱신). 회차별 개선 추적용."""
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    try:
        diag = get_system_diagnosis(farm_id)
    except Exception:
        return {}
    now = _dt.now(_tz.utc)
    snap = {
        "date": now.isoformat()[:10], "ts": now.isoformat(),
        "overall": diag.get("overall_score"), "grade": diag.get("grade"),
        "domains": {d["key"]: d["score"] for d in diag.get("domains", [])},
        "consultant": consultant or "",
    }
    fp = _diag_history_path(farm_id)
    hist = []
    if fp.exists():
        try: hist = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: hist = []
    hist = [h for h in hist if h.get("date") != snap["date"]]  # 같은 날 갱신
    hist.append(snap)
    hist = sorted(hist, key=lambda h: h.get("ts", ""))[-24:]   # 최근 24회
    fp.write_text(_json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    return snap


@router.get("/capability", summary="역량 단계별 핵심 서비스 큐레이션")
def get_capability(farm_id: str):
    """C17 종합진단 → 역량 단계(기반구축/데이터정착/정밀제어/경영고도화) +
    단계별 핵심 서비스 3~5개 + 다음 단계 진입 과제. (서비스 과잉 방지·역량 맞춤 라우팅)"""
    _require_farm(farm_id)
    from api.services.capability_router import build_capability
    diag = get_system_diagnosis(farm_id)
    farm_type = (_FARM_META.get(farm_id, {}) or {}).get("farm_type", "greenhouse")
    return build_capability(diag, farm_type=farm_type)


@router.get("/diagnosis/history", summary="진단 점수 이력(회차별 추세)")
def get_diagnosis_history(farm_id: str):
    import json as _json
    _require_farm(farm_id)
    fp = _diag_history_path(farm_id)
    hist = []
    if fp.exists():
        try: hist = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: hist = []
    delta = None
    if len(hist) >= 2 and hist[-1].get("overall") is not None and hist[-2].get("overall") is not None:
        delta = hist[-1]["overall"] - hist[-2]["overall"]
    return {"snapshots": hist, "count": len(hist), "latest_delta": delta}


@router.post("/diagnosis/snapshot", summary="현재 진단을 이력에 저장")
def post_diagnosis_snapshot(farm_id: str, body: dict = Body(default={})):
    _require_farm(farm_id)
    snap = _append_diag_snapshot(farm_id, (body or {}).get("consultant", ""))
    return {"ok": bool(snap), "snapshot": snap}


@router.get("/diagnosis/checklist", summary="현장컨설팅 문진 체크리스트 스키마 + 저장응답")
def get_diagnosis_checklist(farm_id: str):
    import json as _json
    from pathlib import Path as _P
    _require_farm(farm_id)
    sp = _P(__file__).resolve().parents[1] / "data" / "diagnosis_checklist_schema.json"
    try: schema = _json.loads(sp.read_text(encoding="utf-8"))
    except Exception: schema = {"sections": [], "status_options": []}
    saved = _load_checklist(farm_id)
    return {"schema": schema, "responses": saved.get("responses", {}),
            "updated_at": saved.get("updated_at"), "consultant": saved.get("consultant", "")}


@router.post("/diagnosis/checklist", summary="현장컨설팅 문진 응답 저장")
def post_diagnosis_checklist(farm_id: str, body: dict = Body(...)):
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    _require_farm(farm_id)
    rec = {
        "responses": body.get("responses", {}) or {},
        "consultant": (body.get("consultant") or "").strip(),
        "updated_at": _dt.now(_tz.utc).isoformat(),
    }
    _checklist_path(farm_id).write_text(_json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(rec["responses"])
    # 문진 저장 시 진단 스냅샷 자동 누적(회차 추적)
    try: _append_diag_snapshot(farm_id, rec["consultant"])
    except Exception: pass
    return {"ok": True, "saved_items": n, "updated_at": rec["updated_at"]}


@router.get("/equipment/schema", summary="기자재 분류·통합 입력 스키마 반환")
def get_equipment_schema(farm_id: str):
    import json as _json
    from pathlib import Path as _P
    _require_farm(farm_id)
    sp = _P(__file__).resolve().parents[1] / "data" / "equipment_schema.json"
    try: return _json.loads(sp.read_text(encoding="utf-8"))
    except Exception: return {"categories": [], "integration_fields": {}, "canonical_names": []}


@router.get("/equipment", summary="농가 시설 기자재 인벤토리 조회")
def get_equipment(farm_id: str):
    import json as _json
    _require_farm(farm_id)
    fp = _equipment_path(farm_id)
    items = []
    if fp.exists():
        try: items = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: items = []
    return {"farm_id": farm_id, "count": len(items), "items": items}


class EquipmentItem(BaseModel):
    """장비 1대 = 이기종 통합 매핑표 1행."""
    device_id:    str = Field(..., max_length=64)
    category:     str = Field("", max_length=32)
    device_type:  str = Field("", max_length=64)
    location:     str = Field("", max_length=64)
    maker:        str = Field("", max_length=64)
    model:        str = Field("", max_length=64)
    protocol:     str = Field("", max_length=32)
    host:         str = Field("", max_length=128)
    port:         Optional[int] = None
    unit_id:      Optional[int] = None
    datapoints:   list = Field(default_factory=list)  # [{tag,address,data_type,unit,scale,offset,rw,poll_interval,canonical_name}]
    install_date: str = Field("", max_length=20)


@router.post("/equipment", summary="시설 기자재 등록 (이기종 통합 매핑 포함)")
def post_equipment(farm_id: str, body: EquipmentItem):
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    _require_farm(farm_id)
    fp = _equipment_path(farm_id)
    items = []
    if fp.exists():
        try: items = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: items = []
    rec = body.model_dump()
    rec["ts"] = _dt.now(_tz.utc).isoformat()
    # device_id 중복 시 교체(upsert)
    items = [i for i in items if i.get("device_id") != rec["device_id"]]
    items.append(rec)
    try: fp.write_text(_json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass
    # 매핑된 표준변수 집계
    mapped = sorted({dp.get("canonical_name") for i in items for dp in (i.get("datapoints") or []) if dp.get("canonical_name")})
    return {"farm_id": farm_id, "saved": True, "device_id": rec["device_id"],
            "total_devices": len(items), "mapped_variables": mapped,
            "note": "표준변수로 매핑된 포인트는 제조사·프로토콜 무관하게 화면·모델이 사용합니다."}


@router.delete("/equipment/{device_id}", summary="기자재 삭제")
def delete_equipment(farm_id: str, device_id: str):
    import json as _json
    _require_farm(farm_id)
    fp = _equipment_path(farm_id)
    items = []
    if fp.exists():
        try: items = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception: items = []
    n0 = len(items)
    items = [i for i in items if i.get("device_id") != device_id]
    try: fp.write_text(_json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass
    return {"farm_id": farm_id, "deleted": n0 - len(items), "remaining": len(items)}


@router.get("/diagnosis", summary="시스템 종합진단·업그레이드 추천 (장비·데이터·운영·연동 성숙도 + ROI 우선순위)")
def get_system_diagnosis(farm_id: str):
    """장비 상태·데이터 품질·운영 성숙도·연동 수준을 점수화하고
    개선 우선순위(ROI 추정)를 제시하는 종합진단. (사업계획서 종합진단·업그레이드 추천 AI)"""
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    _require_farm(farm_id)

    # ── 데이터 수집 ──────────────────────────────────────────────
    eq = []
    ep = _equipment_path(farm_id)
    if ep.exists():
        try: eq = _json.loads(ep.read_text(encoding="utf-8"))
        except Exception: eq = []
    acts = []
    ap = _activity_path(farm_id)
    if ap.exists():
        try: acts = _json.loads(ap.read_text(encoding="utf-8"))
        except Exception: acts = []
    _ym = _dt.now(_tz.utc).isoformat()[:7]
    month_acts = [a for a in acts if a.get("ts", "")[:7] == _ym]
    try:
        from api.services.billing import get_farm_tier, tier_rank
        tier = get_farm_tier(farm_id); trank = tier_rank(tier)
    except Exception:
        tier = "basic"; trank = 1

    # 매핑된 표준변수
    mapped = {dp.get("canonical_name") for i in eq for dp in (i.get("datapoints") or []) if dp.get("canonical_name")}
    CORE_VARS = {"temp_internal", "humidity_int", "co2_ppm", "ec_dsm", "ph", "drain_pct"}
    cal_pts = sum(1 for i in eq for dp in (i.get("datapoints") or [])
                  if dp.get("actuator_response_s") or dp.get("cmd_feedback_offset"))

    # ── 점수화 (0~100) ──────────────────────────────────────────
    s_equip = min(100, len(eq) * 25)                                  # 장비 등록
    s_link  = round(len(mapped & CORE_VARS) / len(CORE_VARS) * 100)   # 핵심변수 연동
    s_data  = min(100, len(month_acts) * 12)                          # 데이터 축적(이행)
    s_oper  = min(100, trank * 25 + (20 if len(month_acts) >= 5 else 0))  # 운영 성숙도(등급+이행)
    s_calib = min(100, cal_pts * 34)                                  # 물리 캘리브레이션
    overall = round((s_equip + s_link + s_data + s_oper + s_calib) / 5)
    grade = "우수" if overall >= 75 else "보통" if overall >= 45 else "개선필요"

    # ── 병목·개선 추천 (우선순위·ROI 추정) ───────────────────────
    recs = []
    if s_link < 100:
        miss = sorted(CORE_VARS - mapped)
        recs.append({"title": "핵심 센서 표준변수 매핑 보강", "priority": "높음",
                     "detail": f"미연동 변수: {', '.join(miss) or '없음'}", "roi": "AI 추천 정확도↑ · 즉시",
                     "effort": "낮음", "target": "c16_equipment.html"})
    if s_calib < 50:
        recs.append({"title": "액추에이터 물리 캘리브레이션", "priority": "중간",
                     "detail": "제어명령-실반응 편차·응답시간 보정 입력", "roi": "제어 정밀도↑ · 과/부족급액 손실 절감",
                     "effort": "중간", "target": "c16_equipment.html"})
    if s_data < 60:
        recs.append({"title": "운영 기록 누적(관수·생육·환경)", "priority": "높음",
                     "detail": f"이번 달 {len(month_acts)}건 — 재학습 임계까지 축적 필요", "roi": "모델 재학습→예측 정확도↑",
                     "effort": "낮음", "target": "g3_period.html"})
    if trank < 3:
        recs.append({"title": "상위 등급(pro) 전환 검토", "priority": "중간",
                     "detail": "수확량 신뢰구간·드레인 EC·이익률 분석 잠금 해제", "roi": "고급 의사결정 기능 확보",
                     "effort": "낮음", "target": "/smartos"})
    if not eq:
        recs.insert(0, {"title": "시설 기자재 등록(이기종 통합)", "priority": "높음",
                        "detail": "장비 0대 — 표준변수 연동 시작 필요", "roi": "실데이터 기반 운영 전환",
                        "effort": "낮음", "target": "c16_equipment.html"})

    # ── 현장컨설팅 6대 도메인 진단 (센서·구동기·재배·경영노동·유통·데이터) ──
    #    출처: RDA/이암허브 스마트농업 현장컨설팅 체크리스트·결과보고서
    domains = []; consult = {}
    try:
        from api.services.consulting_diagnosis import build_domains, summarize
        meta = _FARM_META.get(farm_id, {})
        # 보조 지표(관수 배액률·경영 마진) — 실패해도 진단 지속
        _irr = None
        try:
            from api.services.irrigation_store import get_irrigation_analysis as _gia
            _irr = _gia(farm_id, days=7)
        except Exception: _irr = None
        _margin = None
        try:
            _crop = meta.get("crop", "딸기"); _area = float(meta.get("area_m2") or 1000.0)
            _yld = float(get_yield_kg_m2(_crop)); _price = float(get_price_krw_kg(_crop))
            _cost = _compute_costs(farm_id).cost_per_m2
            _rev = _yld * _price
            if _rev > 0: _margin = round((_rev - _cost) / _rev * 100, 0)
        except Exception: _margin = None
        _chk = _load_checklist(farm_id).get("responses", {})
        domains = build_domains(eq=eq, acts=acts, month_acts=month_acts, meta=meta,
                                trank=trank, irr=_irr, margin_pct=_margin, checklist=_chk)
        consult = summarize(domains)
    except Exception as _e:
        domains = []; consult = {}

    return {
        "farm_id": farm_id, "tier": tier,
        "overall_score": consult.get("overall", overall), "grade": consult.get("grade", grade),
        "scores": {
            "장비 등록": s_equip, "핵심변수 연동": s_link, "데이터 축적": s_data,
            "운영 성숙도": s_oper, "물리 캘리브레이션": s_calib,
        },
        "domains": domains,                          # ★ 6대 컨설팅 도메인(점수+진단+처방)
        "priority_decisions": consult.get("priority", []),  # ★ ROI 우선순위 의사결정
        "stats": {"devices": len(eq), "mapped_vars": len(mapped), "month_activities": len(month_acts), "calib_points": cal_pts},
        "recommendations": recs,
        "note": "현장컨설팅 체크리스트(센서·구동기·재배·경영노동·유통·데이터) 기반 종합진단. 우선순위 높은 처방부터 실행 시 ROI가 큽니다.",
    }


_REAL_INCOME_CACHE = {"loaded": False, "data": None}

def _real_income_benchmark(crop: str):
    """농진청 소득조사 적재분(api/data/real/income_benchmark.json)에서 작목 벤치마크 조회."""
    import json as _json
    from pathlib import Path as _P
    if not _REAL_INCOME_CACHE["loaded"]:
        try:
            fp = _P(__file__).resolve().parents[1] / "data" / "real" / "income_benchmark.json"
            _REAL_INCOME_CACHE["data"] = _json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else None
        except Exception:
            _REAL_INCOME_CACHE["data"] = None
        _REAL_INCOME_CACHE["loaded"] = True
    db = _REAL_INCOME_CACHE["data"]
    if not db:
        return None
    rec = (db.get("by_crop") or {}).get(crop)
    if not rec:
        return None
    return {**rec, "_source": f"농진청 소득조사 2022 · {rec.get('orig', crop)} {rec.get('n')}농가 평균(상위 25% 기준)"}


@router.get("/benchmark", summary="우수농가 대비 벤치마킹 (농진청 소득조사 실데이터)")
def get_benchmark(farm_id: str):
    """내 농장 실값(수확량·마진율·에너지효율·배액률) vs 우수농가/RDA 기준 비교."""
    _require_farm(farm_id)
    meta  = _FARM_META.get(farm_id, {})
    crop  = meta.get("crop", "딸기")
    area  = float(meta.get("area_m2") or 1000.0)

    # 내 농장 실값
    try: yld = float(get_yield_kg_m2(crop))
    except Exception: yld = 0.0
    try:
        costs = _compute_costs(farm_id)
        cost_pm2 = costs.cost_per_m2
        energy_pm2 = sum(i.amount_krw for i in costs.items if i.category in ("electricity","heating","water"))
    except Exception:
        cost_pm2 = energy_pm2 = 0.0
    try: price = float(get_price_krw_kg(crop))
    except Exception: price = 0.0
    rev_pm2 = yld * price
    margin = round((rev_pm2 - cost_pm2) / rev_pm2 * 100, 0) if rev_pm2 else 0
    # 배액률 적정도(20~30% 목표 근접도 → 점수)
    try:
        from api.services.irrigation_store import get_irrigation_analysis as _gia
        dr = (_gia(farm_id, days=7) or {}).get("summary", {}).get("dr_pct_mean", {}).get("latest")
    except Exception: dr = None
    drain_ok = round(max(0, 100 - abs((dr or 25) - 25) * 4), 0)  # 25%에서 멀수록 감점
    # 에너지 효율: 총비용 대비 에너지비 비중(낮을수록 고효율). 단위 안전 보정 + 합리적 밴드.
    total_cost = cost_pm2 * area
    share = (energy_pm2 / total_cost * 100) if total_cost > 0 else 35.0
    share = max(10.0, min(60.0, share))   # 비현실값 클리핑
    en_eff = round(100 - share)            # 효율 점수 40~90

    # 우수농가 기준 (RDA 표준 상위)
    metrics = [
        {"key":"수확량 (kg/m²)", "mine":round(yld,1),     "top":round(yld*1.15,1), "unit":"", "higher":True},
        {"key":"마진율 (%)",     "mine":margin,            "top":max(margin, 82),   "unit":"%","higher":True},
        {"key":"에너지 효율",    "mine":en_eff,            "top":88,                "unit":"","higher":True},
        {"key":"배액률 적정도",  "mine":drain_ok,          "top":90,                "unit":"","higher":True},
    ]
    # 농진청 소득조사 실 벤치마크 주입 (작목 매칭 시 상위농가 실값 사용)
    real_src = None
    rb = _real_income_benchmark(crop)
    if rb:
        real_src = rb.get("_source")
        # 마진율 → 소득률 상위25%(실측)로 비교 기준 교체
        for m in metrics:
            if m["key"].startswith("마진율") and rb.get("income_rate_top25_pct"):
                m["key"] = "소득률 (%)"; m["top"] = rb["income_rate_top25_pct"]
        # 농가수취가 메트릭 추가(내 시세 vs 실 평균 수취가)
        if rb.get("farmprice_wn_kg"):
            metrics.append({"key":"농가수취가 (원/kg)", "mine":round(price), "top":round(rb["farmprice_wn_kg"]), "unit":"", "higher":True})

    for m in metrics:
        m["pct"] = round(min(100, (m["mine"]/m["top"]*100) if m["top"] else 0))
        m["status"] = "good" if m["mine"] >= m["top"]*0.95 else ("warn" if m["mine"] >= m["top"]*0.8 else "low")
    weak = min(metrics, key=lambda m: m["pct"])
    return {
        "farm_id": farm_id, "crop": crop, "metrics": metrics,
        "weakest": weak["key"],
        "advice": f"{weak['key']} 항목이 우수농가 대비 낮습니다(내 {weak['mine']} / 상위 {weak['top']}). 해당 영역 화면에서 개선 조치를 확인하세요.",
        "note": (f"비교군: {real_src}" if real_src else "비교군은 RDA 표준·우수농가 기준. 익명 집계 데이터 확보 시 동일 작기 피어 비교로 자동 고도화."),
    }


@router.get("/report/monthly",
            summary="월간 경영성과 리포트 (스마트농업법 제5·6·9조 — 6대영역+성과지표)")
def get_monthly_report(farm_id: str, month: str = ""):
    """농가별 월간 경영성과 종합 리포트.

    6대 모니터링 영역 요약 + 9대 성과지표(목표/기준 대비 변화율)
    + 취약항목 도출 + 실행 To-do 이행률. 정책 사후관리·컨설팅 근거 자료.
    """
    import os
    from datetime import date as _date
    _require_farm(farm_id)
    meta  = _FARM_META.get(farm_id, {})
    crop  = meta.get("crop", "딸기")
    area  = float(meta.get("area_m2") or 1000.0)
    period = month or _date.today().strftime("%Y-%m")

    # ── 데이터 수집 (기존 헬퍼 재사용) ────────────────────────────────────
    env    = _get_env(farm_id) or {}
    alerts = _detect_alerts(farm_id, env, crop_ko=crop) if env else []
    costs  = _compute_costs(farm_id)
    price  = get_price_krw_kg(crop)
    yield_ = get_yield_kg_m2(crop)
    try:
        from api.services.irrigation_store import get_irrigation_analysis as _gia
        irr = _gia(farm_id, days=30)
    except Exception:
        irr = {"summary": {}}
    try:
        hv = get_harvest(farm_id)
        hv_date = hv.predicted_date; hv_yield = hv.predicted_yield_kg_m2; hv_conf = hv.confidence
    except Exception:
        hv_date = None; hv_yield = yield_; hv_conf = 0.6

    cfg = get_config(crop) if "get_config" in globals() else None

    # ── 6대 영역 요약 ─────────────────────────────────────────────────────
    cost_per_kg   = round(costs.cost_per_m2 / max(yield_, 0.1), 0)
    revenue_total = round(yield_ * price * area / 10000)            # 만원
    cost_total    = round(costs.cost_per_m2 * area / 10000)         # 만원
    profit_total  = revenue_total - cost_total
    income_rate   = round(profit_total / revenue_total * 100, 1) if revenue_total else 0.0
    margin_per_kg = round(price - cost_per_kg, 0)
    energy_per_m2 = next((i.amount_krw for i in costs.items if i.category in ("electricity","heating")), 0)
    # 에너지비/kg
    energy_total_m2 = sum(i.amount_krw for i in costs.items if i.category in ("electricity","heating","water"))
    energy_per_kg = round(energy_total_m2 / max(yield_*area, 1), 1) if yield_ else 0

    vpd = env.get("vpd")
    dr  = (irr.get("summary", {}).get("dr_pct_mean", {}) or {}).get("latest")

    areas = {
        "경영": {"소득률": f"{income_rate}%", "kg당원가": f"{cost_per_kg:,.0f}원",
                "kg당마진": f"{margin_per_kg:,.0f}원", "예상매출": f"{revenue_total:,}만원"},
        "환경": {"온도": f"{env.get('temp_internal','—')}°C", "습도": f"{env.get('humidity_int','—')}%",
                "CO2": f"{env.get('co2_ppm','—')}ppm", "VPD": f"{vpd:.2f}kPa" if vpd else "—"},
        "관수": {"배액률": f"{dr:.0f}%" if dr is not None else "—",
                "배액EC": f"{(irr.get('summary',{}).get('ec_drain',{}) or {}).get('latest','—')}"},
        "에너지": {"에너지비/kg": f"{energy_per_kg:,.0f}원", "월에너지비": f"{round(energy_total_m2/10000):,}만원"},
        "병해": {"활성알림": f"{len(alerts)}건", "위험": "낮음" if not alerts else "주의"},
        "수확": {"예상수확일": hv_date or "—", "수확량": f"{hv_yield:.1f}kg/m²", "신뢰도": f"{int(hv_conf*100)}%"},
    }

    # ── 9대 성과지표 (목표/기준 대비 — 변화율 또는 달성률) ─────────────────
    def _kpi(name, value, unit, target, higher_better=True):
        if target and value is not None:
            raw = (value/target)*100 if higher_better else (target/max(value,0.1))*100
            ach = round(min(raw, 150))           # 0~150% cap (초과달성 왜곡 방지)
            status = "good" if ach >= 95 else "warn" if ach >= 80 else "low"
        else:
            ach, status = None, "na"
        return {"name": name, "value": value, "unit": unit, "target": target,
                "achievement_pct": ach, "status": status}

    drain_t = cfg.drain_target_pct if cfg and cfg.drain_target_pct else 25.0

    # ── 이행 활동 로그에서 상품률·To-do 이행률 산출 (폐루프 데이터 활용) ───────
    import json as _json0
    from pathlib import Path as _P0
    _act_fp0 = _P0(__file__).resolve().parents[1] / "data" / "activity_logs" / f"{farm_id}.json"
    _alogs = []
    if _act_fp0.exists():
        try: _alogs = _json0.loads(_act_fp0.read_text(encoding="utf-8"))
        except Exception: _alogs = []
    _macts = [l for l in _alogs if l.get("ts","")[:7] == period]
    # 상품률: 수확 활동의 A등급 비중 (detail에 'A등급' 포함). 데이터 없으면 None
    _harvest_acts = [l for l in _macts if l.get("kind") == "harvest"]
    quality_rate = None
    if _harvest_acts:
        a_cnt = sum(1 for l in _harvest_acts if "A" in (l.get("detail","")))
        quality_rate = round(a_cnt / len(_harvest_acts) * 100)
    # To-do 이행률: 이번 달 todo 활동 건수 / 권장 기준(월 20건 가정)
    _todo_acts = [l for l in _macts if l.get("kind") == "todo"]
    todo_rate = min(round(len(_todo_acts) / 20 * 100), 100) if _todo_acts else None

    kpis = [
        _kpi("생산량(목표대비)", round(yield_,1), "kg/m²", round(get_yield_kg_m2(crop)*1.1,1)),
        _kpi("상품률", quality_rate, "%", 90),
        _kpi("kg당 원가(낮을수록↑)", cost_per_kg, "원/kg", round(price*0.6), higher_better=False),
        _kpi("에너지비/kg(낮을수록↑)", energy_per_kg, "원/kg", round(price*0.12), higher_better=False),
        _kpi("노동시간/kg(낮을수록↑)", round(meta.get("labor_hours_day",5)/max(yield_*area/1000,1),2), "h/ton", 3.0, higher_better=False),
        _kpi("병해 안전도", round(max(0,100-len(alerts)*15)), "점", 90),
        _kpi("출하단가(시세대비)", round(price), "원/kg", round(price)),
        _kpi("소득률", income_rate, "%", 70),
        _kpi("To-do 이행률", todo_rate, "%", 100),
    ]

    # ── 취약항목 도출 ─────────────────────────────────────────────────────
    weak = []
    for k in kpis:
        if k["status"] == "low":
            weak.append({"area": k["name"], "detail": f"{k['name']} 목표 대비 {k['achievement_pct']}% — 개선 필요"})
    if vpd is not None and (vpd < 0.6 or vpd > 1.8):
        weak.append({"area": "환경", "detail": f"VPD {vpd:.2f}kPa 부적정 — 환기·관수 조정"})
    if dr is not None and dr < 20:
        weak.append({"area": "관수", "detail": f"배액률 {dr:.0f}% 부족 — 급액량 증가"})
    if not weak:
        weak.append({"area": "종합", "detail": "주요 지표 양호 — 현 수준 유지 권장"})

    # ── 실행 To-do (취약항목 기반) ────────────────────────────────────────
    todos = [{"title": w["detail"], "area": w["area"], "done": False} for w in weak[:5]]

    # 종합 등급
    achs = [k["achievement_pct"] for k in kpis if k["achievement_pct"] is not None]
    avg_ach = round(sum(achs)/len(achs)) if achs else 0
    grade = "우수" if avg_ach >= 95 else "양호" if avg_ach >= 80 else "보통" if avg_ach >= 65 else "개선필요"

    # ── 월 스냅샷 이력 → 전월 대비 변화율 (정책 제11조 성과지표 추세) ─────────
    import json as _json
    from pathlib import Path as _Path
    _snap_dir = _Path(__file__).resolve().parents[1] / "data" / "report_snapshots"
    _snap_dir.mkdir(parents=True, exist_ok=True)
    _snap_file = _snap_dir / f"{farm_id}.json"
    # 핵심 지표 스냅샷
    _cur = {"income_rate": income_rate, "cost_per_kg": cost_per_kg,
            "energy_per_kg": energy_per_kg, "yield": round(yield_, 2),
            "price": round(price), "alerts": len(alerts), "avg_ach": avg_ach}
    _hist = {}
    if _snap_file.exists():
        try: _hist = _json.loads(_snap_file.read_text(encoding="utf-8"))
        except Exception: _hist = {}
    # 직전 기록(현재 period 제외 최신)
    _prev_period = max([p for p in _hist.keys() if p < period], default=None)
    _prev = _hist.get(_prev_period) if _prev_period else None

    def _chg(key, higher_better=True):
        if not _prev or _prev.get(key) in (None, 0):
            return None
        base = _prev[key]; cur = _cur.get(key)
        if cur is None: return None
        pct = round((cur - base) / abs(base) * 100, 1)
        # 낮을수록 좋은 지표는 부호 반전해 '개선율'로 표기
        return pct if higher_better else round(-pct, 1)

    changes = {
        "소득률":       _chg("income_rate", True),
        "kg당원가절감": _chg("cost_per_kg", False),
        "에너지비절감": _chg("energy_per_kg", False),
        "생산량":       _chg("yield", True),
        "출하단가":     _chg("price", True),
        "병해발생":     _chg("alerts", False),
    }
    # 이번 달 스냅샷 갱신 저장 (최근 24개월 유지)
    _hist[period] = _cur
    for _old in sorted(_hist.keys())[:-24]:
        del _hist[_old]
    try: _snap_file.write_text(_json.dumps(_hist, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass

    _has_prev = _prev is not None

    # ── 학습 기여 피드백 (폐루프: 이행→학습→환원) ────────────────────────
    _act_logs = []
    _act_fp = _activity_path(farm_id)
    if _act_fp.exists():
        try: _act_logs = _json.loads(_act_fp.read_text(encoding="utf-8"))
        except Exception: _act_logs = []
    _month_acts = [l for l in _act_logs if l.get("ts","")[:7] == period]
    # 재학습 누적 카운트 (관수·수확 실측이 학습 데이터화된 양)
    try:
        _rt = _json.loads((_Path(__file__).resolve().parents[2] / "pipeline" / "state" / "new_rows_since_retrain.json").read_text(encoding="utf-8"))
        _pending = _rt.get("new_env_rows", 0) + _rt.get("new_prod_rows", 0)
    except Exception:
        _pending = 0
    # 농가 본인이 입력한 모델 학습용 실측(생육·수확) 누적
    _my_model_recs = sum(1 for l in _act_logs if l.get("kind") in ("growth", "harvest"))
    _remaining = max(0, 500 - _pending)
    _near = _pending >= 400  # 임계(500) 80% 도달 시 임박
    _learning = {
        "month_activities": len(_month_acts),
        "contribution_points": sum({"harvest":30,"irrigation":20,"education":25,"disease_check":15,"todo":10,"growth":20}.get(l.get("kind"),5) for l in _month_acts),
        "pending_train_rows": _pending,
        "retrain_threshold": 500,
        "remaining_rows": _remaining,
        "my_model_records": _my_model_recs,
        "near_retrain": _near,
        "progress_pct": min(round(_pending/500*100), 100),
        "message": (f"재학습 임박! 임계(500)까지 {_remaining}행 남음 — 곧 모델이 자동 재학습됩니다."
                    if _near else
                    f"이행 데이터 {_pending}행 축적 (재학습까지 {_remaining}행). 내 생육·수확 입력({_my_model_recs}건)이 추천 정확도를 높입니다."),
    }

    return {
        "farm_id": farm_id, "period": period, "crop": crop, "area_m2": area,
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "overall_grade": grade, "avg_achievement_pct": avg_ach,
        "areas": areas, "kpis": kpis, "weak_points": weak, "todos": todos,
        "changes_vs_prev": changes, "prev_period": _prev_period, "has_prev": _has_prev,
        "learning": _learning,
        "note": ("전월(" + _prev_period + ") 대비 변화율 산출됨." if _has_prev
                 else "목표값은 작물 표준·시세 기준 추정. 첫 리포트라 전월 비교 없음(다음 달부터 변화율 표시)."),
    }


@router.get("/erp/realtime",
            summary="ERP 실시간 원가·마진·소득률 (SFROP v2.0 혁신4)")
def get_erp_realtime(
    farm_id: str,
    _user: dict = Depends(require_auth),
):
    """수확 시마다 kg당 원가·마진·소득률·출하 타이밍을 실시간으로 산출합니다.

    응답 예시:
    ```json
    {
      "cost_per_kg": 2380,
      "market_price_per_kg": 8500,
      "margin_per_kg": 6120,
      "income_rate_pct": 72.0,
      "breakeven_kg": 140,
      "harvest_timing": {
        "today_margin": 6120,
        "tomorrow_margin_est": 6440,
        "advice": "내일 출하 유리 (+320원/kg 예상)",
        "diff": 320
      },
      "growth_stage": "성숙·수확기",
      "led_spectrum": { "red": 50, "blue": 20, "uv": 30, ... }
    }
    ```
    """
    from datetime import datetime
    from api.engine.erp_calculator import calc_erp

    # 농장 메타 조회
    try:
        from api.data_access import get_farm_meta
        meta = get_farm_meta(farm_id) or {}
    except Exception:
        meta = {}

    crop_ko   = meta.get("crop", "딸기")
    area_m2   = float(meta.get("plant_area_m2", meta.get("area_m2", 1200.0)) or 1200.0)
    current_m = datetime.now().month
    plant_m   = meta.get("plant_month")

    # 최근 수확량 추정 (M2 예측 또는 메타 기본값)
    _Y_DEFAULT = {"딸기": 0.95, "방울토마토": 2.5, "완숙토마토": 3.0,
                  "참외": 1.1, "파프리카": 1.5, "오이": 4.0}
    try:
        from models.m2_yield import predict_yield
        yres = predict_yield(crop_ko, {}, area_m2=area_m2, farm_id=farm_id)
        # yield_kg_m2_monthly: 월평균 kg/m² 사용 (연간값보다 ERP 적합)
        yield_per_m2 = yres.get("yield_kg_m2_monthly") or yres.get("yield_kg_m2", 0.8)
    except Exception:
        yield_per_m2 = _Y_DEFAULT.get(crop_ko, 1.0)

    result = calc_erp(
        farm_id=farm_id,
        crop_ko=crop_ko,
        area_m2=area_m2,
        yield_per_m2=yield_per_m2,
        current_month=current_m,
        plant_month=plant_m,
    )
    out = result.to_dict()
    # 제어 모드 첨부 (Hero 배너 pill + 환경탭 일관성)
    _tier = _FARM_META.get(farm_id, {}).get("tier", FarmTier.MANUAL)
    out["control_mode"] = {
        FarmTier.MANUAL:    "advisory",
        FarmTier.SEMI_AUTO: "approval",
        FarmTier.AUTO:      "full_auto",
    }.get(_tier, "advisory")
    return out


@router.get("/system/api-status",
            summary="외부 API 연결 상태 + 미연결 서비스 설정 방법")
def get_api_status(farm_id: str):
    """연결된/미연결 외부 API 전체 현황과 미연결 서비스 설정 가이드를 반환합니다."""
    _require_farm(farm_id)  # 존재 검증
    from api.services.external_api_hub import get_api_status_report
    report = get_api_status_report()
    # 민감 정보 마스킹
    safe = {
        "report_time": report["report_time"],
        "apis": report["apis"],
        "missing_keys": {
            k: {
                "service": v["service"],
                "used_for": v["used_for"],
                "get_key_url": v["get_key_url"],
                "cost": v.get("cost", ""),
                "env_var": v["env_var"],
            }
            for k, v in report.get("missing_guide", {}).items()
            if not _cfg_check(v["env_var"])
        },
        "mcp_servers": {
            k: {"name": v["name"], "description": v["description"],
                "key_required": v.get("key_required", True),
                "status": v.get("status", "not_connected")}
            for k, v in report.get("mcp_guide", {}).items()
        },
    }
    return safe


# ══════════════════════════════════════════════════════════════════════════════
# GET /anomalies/latest  — 최신 환경 이상 감지 결과 (대시보드 To-Do 연동)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/anomalies/latest",
            summary="최신 환경 이상 감지 결과 (critical/major/minor)")
def get_anomalies_latest(farm_id: str):
    """현재 환경 센서값을 anomaly_detector로 분석해 이상 항목을 반환합니다.

    대시보드 To-Do 리스트의 🚨 이상감지 항목에 자동 표시됩니다.

    severity 등급:
    - **critical**: 정상 범위(p5~p95) 완전 이탈 → 즉시 조치 필요
    - **major**   : 평균 ±2σ 이탈 → 주의 필요
    - **minor**   : 평균 ±1σ 이탈 → 모니터링 권고

    응답 항목:
    - `variable`    : 정규 변수명 (temp_internal 등)
    - `variable_ko` : 한국어 변수명
    - `value`       : 현재 측정값
    - `unit`        : 단위
    - `severity`    : critical | major | minor
    - `message_ko`  : 상세 한국어 메시지
    - `season_stage`: 작기 단계 (early/mid/late/unknown)
    """
    import datetime as _dt
    meta   = _require_farm(farm_id)
    crop   = meta.get("crop", "딸기")
    env    = _get_env(farm_id) or {}
    month  = _dt.date.today().month

    # 숫자 값만 추출 (dict 형태 센서값 처리)
    env_flat: dict[str, float] = {}
    for k, v in env.items():
        try:
            env_flat[k] = float(v["value"] if isinstance(v, dict) else v)
        except (TypeError, ValueError, KeyError):
            pass

    anomalies: list[dict] = []

    if env_flat:
        from api.services.anomaly_detector import detect_anomalies
        try:
            alerts = detect_anomalies(crop, env_flat, month=month)
            for a in alerts:
                anomalies.append({
                    "variable":    a.variable,
                    "variable_ko": a.variable_ko,
                    "value":       a.current_value,
                    "unit":        a.unit,
                    "severity":    a.severity,     # critical | major | minor
                    "message_ko":  a.message_ko,
                    "season_stage": a.season_stage,
                    "normal_min":  a.normal_min,
                    "normal_max":  a.normal_max,
                })
        except Exception as _e:
            logger.warning("[anomalies/latest] detect_anomalies 실패 farm=%s: %s", farm_id, _e)

    # _detect_alerts 결과도 보강 (FarmAlert → critical/high 매핑)
    if env:
        static_alerts = _detect_alerts(farm_id, env, crop_ko=crop)
        existing_vars = {a["variable"] for a in anomalies}
        _sev_map = {"danger": "critical", "warning": "high", "info": "minor"}
        for fa in static_alerts:
            if fa.variable not in existing_vars:
                anomalies.append({
                    "variable":    fa.variable,
                    "variable_ko": fa.variable,
                    "value":       fa.value,
                    "unit":        fa.unit,
                    "severity":    _sev_map.get(fa.severity, fa.severity),
                    "message_ko":  fa.message_ko,
                    "season_stage": "unknown",
                    "normal_min":  None,
                    "normal_max":  None,
                })

    # 심각도 순 정렬 (critical 우선)
    _sev_order = {"critical": 0, "high": 1, "major": 2, "minor": 3}
    anomalies.sort(key=lambda x: _sev_order.get(x["severity"], 9))

    critical_count = sum(1 for a in anomalies if a["severity"] in ("critical", "high"))

    logger.info("[anomalies/latest] farm=%s crop=%s total=%d critical=%d",
                farm_id, crop, len(anomalies), critical_count)

    return {
        "farm_id":        farm_id,
        "updated_at":     _now().isoformat(),
        "anomalies":      anomalies,
        "count":          len(anomalies),
        "critical_count": critical_count,
        "has_data":       bool(env_flat),
    }
