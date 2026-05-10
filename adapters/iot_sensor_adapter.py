"""IoT sensor adapter — maps Korean field names from 환경_2025.csv to canonical variables.

EC is sourced in mS/cm and converted to dS/m (×0.1).
All timestamps are assumed KST; stored as-is (tz-aware callers should attach +09:00).
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
import logging

from adapters.base_adapter import (
    AdapterResult, NormalizedRecord, safe_float, validate_range,
)

logger = logging.getLogger(__name__)

SOURCE_ID = "iot_sensor"
QUALITY_TAG = "FINETUNED"

# Korean field name → (canonical_name, transform_fn)
_FIELD_MAP: dict[str, tuple[str, Any]] = {
    "온도_내부":       ("temp_internal",  None),
    "온도_외부":       ("temp_external",  None),
    "상대습도_내부":   ("humidity_int",   None),
    "잔존CO2":         ("co2_ppm",        None),
    "일사량_외부":     ("solar_rad",      None),
    "누적일사량_외부": ("cum_solar_ext",  None),
    "토양온도":        ("soil_temp",      None),
    "풍속_외부":       ("wind_speed_ext", None),
    "풍향_외부":       ("wind_dir_ext",   None),
    "강우감지":        ("rain_detect",    None),
    "EC":              ("ec_dsm",         lambda v: v * 0.1),  # mS/cm → dS/m
}


def adapt_row(
    row: dict[str, str],
    farm_id: str,
    time: datetime,
) -> AdapterResult:
    """Convert one sensor CSV row to NormalizedRecords.

    Args:
        row:     dict of {field_name: raw_string_value} from the CSV row
        farm_id: identifier for the originating farm
        time:    parsed timestamp for this row (KST)
    """
    result = AdapterResult()
    for src_field, (canonical, transform) in _FIELD_MAP.items():
        raw = row.get(src_field)
        if raw is None or str(raw).strip() in ("", "-", "NA", "N/A"):
            continue
        value = safe_float(raw)
        if value is None:
            result.errors.append(f"[{SOURCE_ID}] {src_field}='{raw}' is not numeric — skipped")
            continue
        if transform is not None:
            value = transform(value)
        if not validate_range(canonical, value):
            result.errors.append(
                f"[{SOURCE_ID}] {canonical}={value} out of valid range — skipped"
            )
            continue
        result.records.append(NormalizedRecord(
            time=time,
            farm_id=farm_id,
            canonical_name=canonical,
            value=value,
            source_id=SOURCE_ID,
            quality_tag=QUALITY_TAG,
        ))
    return result


def adapt_dataframe(df, farm_id: str, time_col: str = "측정일시") -> AdapterResult:
    """Adapt a pandas DataFrame loaded from 환경_2025.csv.

    Args:
        df:       DataFrame with Korean column names
        farm_id:  farm identifier
        time_col: name of the timestamp column
    """
    combined = AdapterResult()
    for _, row in df.iterrows():
        raw_time = row.get(time_col)
        try:
            time = datetime.fromisoformat(str(raw_time))
        except (ValueError, TypeError):
            combined.errors.append(f"[{SOURCE_ID}] unparseable timestamp '{raw_time}' — row skipped")
            continue
        row_result = adapt_row(row.to_dict(), farm_id, time)
        combined.records.extend(row_result.records)
        combined.errors.extend(row_result.errors)
    if combined.errors:
        logger.warning("[iot_sensor_adapter] %d warnings during adapt", len(combined.errors))
    return combined
