"""공유 농가 상태 — farmer*.py 모듈이 공통으로 참조하는 메타/환경 데이터 및 헬퍼."""
from __future__ import annotations

import logging
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
