"""관수·노지 필지 라우터 — farmer.py에서 분리.

farmer.py의 router 객체에 라우트를 등록한다(사이드 이펙트 임포트 방식).
main.py는 기존대로 farmer.router 하나만 include하면 이 라우트도 포함된다.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import Query, HTTPException
from pydantic import BaseModel, Field

from api.routers.farmer_state import router, _FARM_META, _require_farm
from adapters.irrigation_adapter import adapt_irrigation
from api.services.kma_service import get_solar_irrigation_schedule

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# P4 관수 데이터 수신
# ══════════════════════════════════════════════════════════════════════════════

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

    from api.services.irrigation_store import save_irrigation_day
    save_irrigation_day(farm_id, body.date, summary)

    return IrrigationResponse(
        farm_id=farm_id,
        date=body.date,
        records_saved=len(result.records),
        warnings=result.errors,
        summary=summary,
    )


# ══════════════════════════════════════════════════════════════════════════════
# KMA 일사량 기반 관수 스케줄
# ══════════════════════════════════════════════════════════════════════════════

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

        if _drain_auto is None:
            _pi_saved = load_pi_state(farm_id)
            _drain_auto = _pi_saved.get("drain_actual_pct_last")

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
# 노지 필지 — 토양·경계·클러스터·병해충
# ══════════════════════════════════════════════════════════════════════════════

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
        prof = (db.get("by_sigungu") or {}).get("제주시"); scope = "제주 평균"
    if not prof:
        return None
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

    real = _real_soil_lookup(meta)
    if real:
        real["farm_id"] = farm_id
        return real

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
        for k, v in db.get("by_emd", {}).items():
            if sgg and k.startswith(sgg): rec = v; scope = k; break
    if not rec:
        for k, v in db.get("by_emd", {}).items():
            rec = v; scope = f"{k} (제주 샘플)"; break
    if not rec:
        return None
    # 방어: parcel 값 중 float NaN(비표준 JSON 토큰 유발)을 None으로 새니타이즈
    import math as _math
    def _san(p):
        return {k: (None if isinstance(v, float) and not _math.isfinite(v) else v) for k, v in p.items()}
    parcels = [_san(p) for p in (rec.get("parcels", []) or [])]
    return {"farm_id": meta.get("_fid", ""), "source": "farmmap_real", "region": scope,
            "parcels": parcels,
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
    if live and live.get("parsed") and live.get("parcels"):
        # 파싱 확정된 실데이터
        return {"farm_id": farm_id, "source": "farmmap", "adm": adm,
                "parcels": live["parcels"],
                "note": f"팜맵 실데이터 ({len(live['parcels'])}필지)"}
    if live:
        # 응답은 받았으나 스펙 미검증으로 파싱 실패 — 정직하게 raw 표기(자동전환 아님)
        return {"farm_id": farm_id, "source": "farmmap_raw", "adm": adm,
                "data": live.get("raw"), "parcels": [],
                "note": "팜맵 응답 수신했으나 파싱 스펙 미검증 — 실 응답 샘플 확보 후 확정 필요"}

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


@router.get("/field/calendar", summary="노지 표준 재배력 (작목×이번달 + ERA5 평년기후, 표준 참고)")
def get_field_calendar(farm_id: str):
    """작목 표준재배력(cultivation_calendar SSOT) + 이번 달 phase + ERA5 평년 기후 병합.

    ★ 정직화: 미적재 작목은 available:false. 값은 '표준 참고(출처)'이며 필지·농가
      개인화가 아니다. 품종/날짜 세밀 해상도는 외부 표준재배력 적재 작목만.
    """
    import datetime as _dt
    _require_farm(farm_id)
    meta = _FARM_META.get(farm_id, {})
    crop = meta.get("crop") or "감귤"
    from models.cultivation_calendar import get_calendar
    out = get_calendar(crop, month=_dt.date.today().month)
    out["farm_id"] = farm_id
    return out


@router.get("/field/cluster", summary="노지 클러스터 작황 모니터링 (무센서·위성/기상 + 위치특정 이상알림)")
def get_field_cluster(farm_id: str):
    """위성 식생지수(미연동 시 프록시) + 16일 기상 스트레스로 무센서 광역 작황진단.
    클러스터(다수 필지) 평균·균일도·이상필지 + **위치특정 정량편차 이상알림(실행지시)** 반환."""
    _require_farm(farm_id)
    meta = _FARM_META.get(farm_id, {})
    region = f"{meta.get('sido','') or ''} {meta.get('sigungu','') or ''}".strip() or "-"
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
    region_wx = None
    try:
        from api.services.extended_weather import get_extended_forecast
        region_wx = get_extended_forecast(meta.get("sido", "") or "", meta.get("sigungu", "") or "", 16)
    except Exception:
        region_wx = None
    soil = None
    try:
        soil = get_field_soil(farm_id)
    except Exception:
        soil = None
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
