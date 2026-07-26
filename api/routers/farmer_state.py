"""공유 농가 상태 — farmer*.py 모듈이 공통으로 참조하는 메타/환경 데이터 및 헬퍼."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from api.middleware.auth import require_auth
from engine.farm_tier import FarmTier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Farm registry — IoT 가용성·작목·규모·지역
# ---------------------------------------------------------------------------
_FARM_META: dict[str, dict[str, Any]] = {
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

# ---------------------------------------------------------------------------
# Farm env baseline — IoT 실시간 환경값 기준
# ---------------------------------------------------------------------------
_FARM_ENV: dict[str, dict[str, float]] = {
    "farm_001": {
        "temp_internal": 23.0,
        "humidity_int":  76.0,
        "co2_ppm":       850.0,
        "solar_rad":     320.0,
        "ec_dsm":         2.0,
        "soil_temp":     19.0,
    },
    "farm_002": {
        "temp_internal": 25.3,
        "humidity_int":  67.0,
        "co2_ppm":      1120.0,
        "solar_rad":     490.0,
        "ec_dsm":         2.9,
        "soil_temp":     21.2,
    },
    "farm_003": {
        "temp_internal": 17.6,
        "humidity_int":  83.0,
        "co2_ppm":       860.0,
        "solar_rad":     185.0,
        "ec_dsm":         1.3,
        "soil_temp":     14.4,
    },
    "farm_004": {
        "temp_internal": 23.5,
        "humidity_int":  68.0,
        "co2_ppm":       950.0,
        "solar_rad":     480.0,
        "ec_dsm":         2.8,
        "soil_temp":     20.0,
    },
    "jonomheon": {
        "temp_internal": 22.0,
        "humidity_int":  65.0,
        "co2_ppm":       800.0,
        "solar_rad":     300.0,
        "ec_dsm":         2.0,
        "soil_temp":     18.0,
    },
    "sanwoo": {
        "temp_internal": 18.0,
        "humidity_int":  72.0,
        "co2_ppm":       900.0,
        "solar_rad":     200.0,
        "ec_dsm":         1.2,
        "soil_temp":     14.0,
    },
}


async def _verify_farm_ownership(
    farm_id: str, user: dict = Depends(require_auth)
) -> dict:
    """URL의 farm_id가 인증된 사용자의 소유인지 확인 (admin/manager/demo는 전체 허용)."""
    if user.get("role") not in ("admin", "manager", "superadmin", "demo"):
        token_farm = user.get("farm_id", "")
        if (not token_farm) or token_farm != farm_id:
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


def _equipment_path(farm_id: str):
    """농가 기자재 인벤토리 JSON 경로. farmer_equipment·get_system_diagnosis 공용."""
    from pathlib import Path as _P
    d = _P(__file__).resolve().parents[1] / "data" / "equipment"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{farm_id}.json"


def _activity_path(farm_id: str):
    """농가 이행 활동 로그 JSON 경로. farmer(activity)·get_system_diagnosis 공용."""
    from pathlib import Path as _P
    d = _P(__file__).resolve().parents[1] / "data" / "activity_logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{farm_id}.json"


def _checklist_path(farm_id: str):
    """농가 진단 체크리스트 JSON 경로. farmer(diagnosis)·get_system_diagnosis 공용."""
    from pathlib import Path as _P
    d = _P(__file__).resolve().parents[1] / "data" / "diagnosis"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{farm_id}.json"


def _load_checklist(farm_id: str) -> dict:
    import json as _json
    fp = _checklist_path(farm_id)
    if fp.exists():
        try:
            return _json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# 농가별 자원 소비 데이터 (일별 기준, 월 30일 적용). _compute_costs 기본값.
# 전기 105원/kWh · 용수 700원/m³ · 난방 85원/kWh(가스환산) · 인건비 12,000원/시간
_RESOURCE_COSTS: dict[str, dict] = {
    "farm_001": {   # 오이 1200m² — 고온·고습, 수막재배
        "electricity_kwh_day": 120.0, "electricity_rate": 105.0,
        "water_m3_day": 4.0, "water_rate": 700.0,
        "heating_kwh_day": 72.0, "heating_rate": 85.0,
        "labor_hours_day": 5.0, "labor_rate": 12_000.0,
        "nutrients_krw_day": 15_000.0, "pesticides_krw_day": 3_000.0,
    },
    "farm_002": {   # 방울토마토 800m² — 반자동
        "electricity_kwh_day": 112.0, "electricity_rate": 105.0,
        "water_m3_day": 3.2, "water_rate": 700.0,
        "heating_kwh_day": 80.0, "heating_rate": 85.0,
        "labor_hours_day": 3.0, "labor_rate": 12_000.0,
        "nutrients_krw_day": 14_000.0, "pesticides_krw_day": 4_000.0,
    },
    "farm_003": {   # 딸기(설향) 1500m² — 노동집약
        "electricity_kwh_day": 150.0, "electricity_rate": 105.0,
        "water_m3_day": 4.5, "water_rate": 700.0,
        "heating_kwh_day": 135.0, "heating_rate": 85.0,
        "labor_hours_day": 8.0, "labor_rate": 12_000.0,
        "nutrients_krw_day": 22_000.0, "pesticides_krw_day": 6_000.0,
    },
    "farm_004": {   # 완숙토마토 1000m² — 반자동
        "electricity_kwh_day": 130.0, "electricity_rate": 105.0,
        "water_m3_day": 4.0, "water_rate": 700.0,
        "heating_kwh_day": 90.0, "heating_rate": 85.0,
        "labor_hours_day": 4.0, "labor_rate": 12_000.0,
        "nutrients_krw_day": 16_000.0, "pesticides_krw_day": 3_500.0,
    },
    "farm_005": {   # 미등록 900m²
        "electricity_kwh_day": 90.0, "electricity_rate": 105.0,
        "water_m3_day": 1.8, "water_rate": 700.0,
        "heating_kwh_day": 54.0, "heating_rate": 85.0,
        "labor_hours_day": 3.0, "labor_rate": 12_000.0,
        "nutrients_krw_day": 9_000.0, "pesticides_krw_day": 2_000.0,
    },
}


def _compute_costs(farm_id: str):
    """비용 계산 공통 로직 (farmer.py 에서 이관 — ai_chat·pdca 도 사용).

    수기 입력값(persistence)이 있으면 우선 사용, 없으면 _RESOURCE_COSTS 기본값.
    외부 의존은 지연 import 로 순환 방지.
    """
    from api.services import persistence
    from api.data.stats_loader import get_electricity_rate, get_water_rate
    from api.schemas.farmer import CostBreakdownResponse, CostItem, ManualCostInput

    rc   = _RESOURCE_COSTS.get(farm_id) or _RESOURCE_COSTS.get("farm_001") or {}
    mc   = persistence.get_manual_cost(farm_id)
    meta = _FARM_META.get(farm_id) or _FARM_META.get("farm_001", {})
    DAYS = 30

    def _v(key_manual: str, default: float):
        v = mc.get(key_manual)
        return (v, True) if v is not None else (default, False)

    kwh_m,   kwh_manual   = _v("electricity_kwh_month", rc["electricity_kwh_day"] * DAYS)
    e_rate,  e_rate_manual = _v("electricity_rate",     get_electricity_rate())
    elec     = kwh_m * e_rate
    elec_manual = kwh_manual or e_rate_manual

    m3_m,    m3_manual    = _v("water_m3_month",  rc["water_m3_day"] * DAYS)
    w_rate,  w_rate_m     = _v("water_rate",       get_water_rate())
    water    = m3_m * w_rate
    water_manual = m3_manual or w_rate_m

    h_kwh,   h_kwh_m      = _v("heating_kwh_month", rc["heating_kwh_day"] * DAYS)
    h_rate,  h_rate_m     = _v("heating_rate",       rc["heating_rate"])
    heat     = h_kwh * h_rate
    heat_manual = h_kwh_m or h_rate_m

    l_hrs,   l_hrs_m      = _v("labor_hours_month", rc["labor_hours_day"] * DAYS)
    l_rate,  l_rate_m     = _v("labor_rate",         rc["labor_rate"])
    labor    = l_hrs * l_rate
    labor_manual = l_hrs_m or l_rate_m

    nutr,    nutr_manual  = _v("nutrients_krw_month",  rc["nutrients_krw_day"] * DAYS)
    pest,    pest_manual  = _v("pesticides_krw_month", rc["pesticides_krw_day"] * DAYS)

    total = elec + water + heat + labor + nutr + pest

    def pct(v: float) -> float:
        return round(v / total, 4) if total else 0.0

    stored_mc = ManualCostInput(**mc) if mc else None
    has_manual = bool(mc)

    def _elec_label() -> str:
        if elec_manual:
            return f"실제입력 {kwh_m:,.0f}kWh × {e_rate:.0f}원/kWh"
        return f"{rc['electricity_kwh_day']}kWh/일 × 30일 × {e_rate:.0f}원/kWh (KEPCO농업용갑)"

    def _water_label() -> str:
        if water_manual:
            return f"실제입력 {m3_m:,.1f}m³ × {w_rate:.0f}원/m³"
        return f"{rc['water_m3_day']}m³/일 × 30일 × {w_rate:.0f}원/m³ (농업용평균)"

    def _heat_label() -> str:
        if heat_manual:
            return f"실제입력 {h_kwh:,.0f}kWh × {h_rate:.0f}원/kWh"
        return f"{rc['heating_kwh_day']}kWh/일 × 30일 × {h_rate:.0f}원/kWh"

    def _labor_label() -> str:
        if labor_manual:
            return f"실제입력 {l_hrs:,.0f}시간 × {l_rate:,.0f}원/시간"
        return f"{rc['labor_hours_day']}시간/일 × 30일 × {l_rate:,.0f}원/시간"

    def _item(category: str, label_ko: str, amount: float, unit_label: str, is_manual: bool):
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
        total_krw=round(total),
        cost_per_m2=round(total / max(meta["area_m2"], 1.0), 1),
        electricity_kwh_month=kwh_m,
        water_m3_month=m3_m,
        has_manual_input=has_manual,
        manual_input=stored_mc,
    )


def _require_farm(farm_id: str) -> dict[str, Any]:
    meta = _FARM_META.get(farm_id)
    if meta is None:
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
                _FARM_META[farm_id] = meta
        except Exception:
            pass
    if meta is None:
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
        _FARM_META[farm_id] = meta
    return meta
