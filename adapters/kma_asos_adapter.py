"""KMA ASOS (기상청 종관기상관측) adapter.

ASOS 일별 데이터 → 정규 환경 변수 변환.
외부 기상 → 온실 내부 추정값으로 보정.

보정 로직:
  temp_internal  = avgTa + GREENHOUSE_OFFSET (하우스 보온 효과 +4°C)
  humidity_int   = avgRhm (외부 습도 — 내부는 관개·증산으로 더 높으나 근사값으로 사용)
  soil_temp      = avgTs  (지중온도)
  solar_rad      = hr1MaxIcsr (W/m²) if available, else sumGsr × 11.57 (MJ→W/m² 일평균 환산)
"""
from __future__ import annotations
from datetime import datetime, date
from typing import Any, Optional
import logging

from adapters.base_adapter import (
    AdapterResult, NormalizedRecord, safe_float, validate_range,
)

logger = logging.getLogger(__name__)

SOURCE_ID = "kma_asos"
QUALITY_TAG = "TRANSFER"          # 외부 기상 → 온실 내부 추정이므로 TRANSFER

# 온실 내부 온도 보정값 (°C) — 하우스 보온·태양열 효과
GREENHOUSE_TEMP_OFFSET = 4.0


def _solar_rad_from_asos(item: dict[str, Any]) -> Optional[float]:
    """일사량 W/m² 추정.

    ASOS 제공:
      hr1MaxIcsr : 최대 순간 일사량 (W/m²) — 바로 사용
      sumGsr     : 일 누적 일사량 (MJ/m²) → W/m² 일평균 환산 (÷ 86400 × 10⁶)
    """
    peak = safe_float(item.get("hr1MaxIcsr"))
    if peak is not None and peak > 0:
        # 피크값의 40% ≈ 하루 평균 일사량 (sin 곡선 적분)
        return round(peak * 0.40, 1)

    gsr = safe_float(item.get("sumGsr"))   # MJ/m²
    if gsr is not None and gsr > 0:
        # MJ/m²·day → W/m² 일평균: × 1_000_000 / 86_400 = × 11.574
        return round(gsr * 11.574, 1)

    return None


def adapt_daily_record(
    item: dict[str, Any],
    farm_id: str,
    obs_date: Optional[date] = None,
) -> AdapterResult:
    """ASOS 일별 레코드 1건 → NormalizedRecord 목록.

    Args:
        item:     ASOS JSON item dict
        farm_id:  대상 농가 ID
        obs_date: 관측 날짜 (None이면 item['tm'] 파싱)
    """
    result = AdapterResult()

    if obs_date is None:
        raw_tm = item.get("tm", "")
        try:
            obs_date = date.fromisoformat(str(raw_tm))
        except (ValueError, TypeError):
            result.errors.append(f"[{SOURCE_ID}] bad date '{raw_tm}' — skipped")
            return result

    obs_time = datetime(obs_date.year, obs_date.month, obs_date.day, 12, 0)

    def _add(canonical: str, raw_key: str, transform=None):
        val = safe_float(item.get(raw_key))
        if val is None:
            return
        if transform:
            val = transform(val)
        if not validate_range(canonical, val):
            result.errors.append(
                f"[{SOURCE_ID}] {canonical}={val} out of range — skipped"
            )
            return
        result.records.append(NormalizedRecord(
            time=obs_time,
            farm_id=farm_id,
            canonical_name=canonical,
            value=round(val, 2),
            source_id=SOURCE_ID,
            quality_tag=QUALITY_TAG,
            imputed=True,          # 외부→내부 추정이므로 imputed=True
        ))

    # 온도: 외부 평균 + 온실 오프셋
    _add("temp_internal",  "avgTa",  lambda v: v + GREENHOUSE_TEMP_OFFSET)
    _add("temp_external",  "avgTa")          # 외부 온도 원본도 보존
    _add("humidity_int",   "avgRhm")
    _add("soil_temp",      "avgTs")
    _add("wind_speed_ext", "avgWs")
    _add("wind_dir_ext",   "maxWd")

    # 일사량 (복합 계산)
    rad = _solar_rad_from_asos(item)
    if rad is not None and validate_range("solar_rad", rad):
        result.records.append(NormalizedRecord(
            time=obs_time,
            farm_id=farm_id,
            canonical_name="solar_rad",
            value=rad,
            source_id=SOURCE_ID,
            quality_tag=QUALITY_TAG,
            imputed=True,
        ))

    return result


def adapt_response(
    items: list[dict[str, Any]],
    farm_id: str,
) -> AdapterResult:
    """ASOS API 응답 items 전체 변환."""
    combined = AdapterResult()
    for item in items:
        r = adapt_daily_record(item, farm_id)
        combined.records.extend(r.records)
        combined.errors.extend(r.errors)
    if combined.errors:
        logger.warning("[kma_asos_adapter] %d warnings", len(combined.errors))
    return combined
