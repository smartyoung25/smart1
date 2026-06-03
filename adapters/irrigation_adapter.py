"""Irrigation adapter — P4 시간대별 관수 데이터를 NormalizedRecord로 변환.

관수통합관리시스템(HTML)의 시간대별 관리 탭에서 입력된
P1(일출)·P2(오전)·P3(오후)·P4(일몰) 4구간 데이터를 처리합니다.

입력 형식 (POST /api/v1/irrigation):
    {
        "farm_id": "farm_001",
        "crop":    "딸기",
        "date":    "2026-05-20",
        "periods": [
            {"period": 1, "supply_ml": 150, "drain_ml": 0,   "ec": 2.5, "ph": 6.0, "slab_wt_kg": 12.5},
            {"period": 2, "supply_ml": 300, "drain_ml": 80,  "ec": 2.4, "ph": 6.1, "slab_wt_kg": 14.2},
            {"period": 3, "supply_ml": 400, "drain_ml": 150, "ec": 2.6, "ph": 5.9, "slab_wt_kg": 14.8},
            {"period": 4, "supply_ml": 200, "drain_ml": 100, "ec": 2.7, "ph": 5.8, "slab_wt_kg": 13.5}
        ],
        "slab_vol_l":    15.0,   # slab 용량 (L)
        "max_wt_kg":     14.8,   # 당일 최대 무게
        "min_wt_kg":     12.0,   # 일출 전 최소 무게
        "sunset_wt_kg":  13.5    # 일몰 직후 무게 (야간소실률 계산)
    }

산출 canonical 변수:
    wc_mean      - 함수율 평균 (%)  = avg(slab_wt/slab_vol*100)
    wc_max       - 함수율 최대 (%)
    wc_min       - 함수율 최소 (%)
    dr_pct_mean  - 배액률 평균 (%)  = avg(drain/supply*100)
    ec_drain     - 배액 EC 평균 (dS/m)
    supply_total - 총 공급량 (ml/slab/일)
    irr_count    - 유효 관수 횟수 (supply>0인 구간 수)
    nl_pct       - 야간소실률 (%)   = (max_wt - sunset_wt)/max_wt*100
"""
from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Any, Optional

from adapters.base_adapter import AdapterResult, NormalizedRecord, safe_float, validate_range

logger = logging.getLogger(__name__)
SOURCE_ID  = "irrigation_p4"
QUALITY_TAG = "FINETUNED"


def _wc(slab_wt_kg: float, slab_vol_l: float) -> Optional[float]:
    """함수율 (Water Content) = slab무게/slab용량 * 100 (%)."""
    if slab_vol_l <= 0:
        return None
    return round(slab_wt_kg / slab_vol_l * 100, 2)


def _dr_pct(drain_ml: float, supply_ml: float) -> Optional[float]:
    """배액률 (Drain Ratio) = 배액/공급 * 100 (%)."""
    if supply_ml <= 0:
        return None
    return round(drain_ml / supply_ml * 100, 2)


def adapt_irrigation(payload: dict[str, Any]) -> AdapterResult:
    """P4 관수 데이터 1일치를 NormalizedRecord 목록으로 변환."""
    result = AdapterResult()

    farm_id   = payload.get("farm_id", "unknown")
    date_str  = payload.get("date")
    slab_vol  = safe_float(payload.get("slab_vol_l", 15.0)) or 15.0
    periods   = payload.get("periods", [])

    # 날짜 파싱
    try:
        if date_str:
            ts = datetime.fromisoformat(date_str)
        else:
            ts = datetime.utcnow()
    except ValueError as exc:
        result.errors.append(f"[{SOURCE_ID}] 날짜 파싱 오류: {exc}")
        return result

    if not periods:
        result.errors.append(f"[{SOURCE_ID}] periods 없음 — 건너뜀")
        return result

    # ── 구간별 계산 ────────────────────────────────────────────────────────
    wc_list, dr_list, ec_list, supply_sum = [], [], [], 0.0
    irr_count = 0

    for p in periods:
        sup  = safe_float(p.get("supply_ml", 0)) or 0.0
        dr   = safe_float(p.get("drain_ml",  0)) or 0.0
        ec   = safe_float(p.get("ec"))
        wt   = safe_float(p.get("slab_wt_kg"))

        supply_sum += sup
        if sup > 0:
            irr_count += 1

        wc_val = _wc(wt, slab_vol) if wt is not None else None
        dr_val = _dr_pct(dr, sup)  if sup > 0  else None

        if wc_val is not None:
            wc_list.append(wc_val)
        if dr_val is not None:
            dr_list.append(dr_val)
        if ec is not None and ec > 0:
            ec_list.append(ec)

    # ── 일별 집계 canonical 변수 ───────────────────────────────────────────
    def _push(canonical: str, value: Optional[float]) -> None:
        if value is None or not validate_range(canonical, value):
            return
        result.records.append(NormalizedRecord(
            time=ts,
            farm_id=farm_id,
            canonical_name=canonical,
            value=round(value, 3),
            source_id=SOURCE_ID,
            quality_tag=QUALITY_TAG,
        ))

    _push("wc_mean",        sum(wc_list) / len(wc_list) if wc_list else None)
    _push("wc_max",         max(wc_list) if wc_list else None)
    _push("wc_min",         min(wc_list) if wc_list else None)
    _push("dr_pct_mean",    sum(dr_list) / len(dr_list) if dr_list else None)
    _push("ec_drain",       sum(ec_list) / len(ec_list) if ec_list else None)
    _push("supply_total",   supply_sum if supply_sum > 0 else None)
    _push("irr_count",      float(irr_count) if irr_count > 0 else None)

    # 야간소실률(P5 일몰前 dry-down) + 야간 dry-back(P6 일몰→일출前)
    max_wt    = safe_float(payload.get("max_wt_kg"))
    sunset_wt = safe_float(payload.get("sunset_wt_kg"))
    min_wt    = safe_float(payload.get("min_wt_kg"))
    if max_wt and sunset_wt and max_wt > 0:
        nl = (max_wt - sunset_wt) / max_wt * 100   # 오후 dry-down (목표 2~5%)
        _push("nl_pct", nl)
    if sunset_wt and min_wt and sunset_wt > 0:
        # 야간 dry-back: 일몰 직후 → 일출 전 최소 무게 (P6, 목표 10~20%)
        db = (sunset_wt - min_wt) / sunset_wt * 100
        _push("dryback_night_pct", db)

    logger.info(
        "[irrigation_adapter] farm=%s date=%s | supply=%.0f ml | irr=%d회 | "
        "wc_mean=%.1f%% | dr_mean=%.1f%% | records=%d",
        farm_id, date_str, supply_sum, irr_count,
        sum(wc_list)/len(wc_list) if wc_list else 0,
        sum(dr_list)/len(dr_list) if dr_list else 0,
        len(result.records),
    )
    return result
