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
        time_col: name of the timestamp column (auto-detected if not in df)
    """
    import re as _re
    # Strip unit bracket annotations from column names: 온도_외부[celsius[℃]] → 온도_외부
    df = df.copy()
    df.columns = [_re.sub(r'\[.*$', '', c).strip() for c in df.columns]

    # Auto-detect time column if provided name not in df
    if time_col not in df.columns:
        _TIME_PATTERNS = [
            "측정시간",  # 측정시간
            "측정시각",  # 측정시각
            "측정일시",  # 측정일시
            "일시",              # 일시
            "시간",              # 시간
        ]
        found = next((c for c in df.columns if any(p in c for p in _TIME_PATTERNS)), None)
        if found:
            time_col = found
        elif df.columns.tolist():
            # Last fallback: first column that has date-like values
            import re
            for col in df.columns:
                vals = df[col].dropna().astype(str)
                if vals.str.match(r"\d{4}-\d{2}-\d{2}").any():
                    time_col = col
                    break
    combined = AdapterResult()
    import pandas as _pd
    import math as _math

    # Vectorized timestamp parsing (much faster than iterrows fromisoformat)
    raw_times = df[time_col].astype(str)
    parsed_times = _pd.to_datetime(raw_times, errors="coerce")

    sensor_cols = [c for c in _FIELD_MAP if c in df.columns]

    for idx, (_, row) in enumerate(df.iterrows()):
        t = parsed_times.iloc[idx]
        if _pd.isna(t):
            combined.errors.append(f"[{SOURCE_ID}] unparseable timestamp '{raw_times.iloc[idx]}' — row skipped")
            continue
        time_dt = t.to_pydatetime()
        for src_field in sensor_cols:
            canonical, transform = _FIELD_MAP[src_field]
            raw = row.get(src_field)
            if raw is None or str(raw).strip() in ("", "-", "NA", "N/A"):
                continue
            value = safe_float(raw)
            if value is None:
                combined.errors.append(f"[{SOURCE_ID}] {src_field}='{raw}' is not numeric — skipped")
                continue
            if transform is not None:
                value = transform(value)
            if not validate_range(canonical, value):
                combined.errors.append(
                    f"[{SOURCE_ID}] {canonical}={value} out of valid range — skipped"
                )
                continue
            combined.records.append(NormalizedRecord(
                time=time_dt,
                farm_id=farm_id,
                canonical_name=canonical,
                value=value,
                source_id=SOURCE_ID,
                quality_tag=QUALITY_TAG,
            ))
    if combined.errors:
        logger.warning("[iot_sensor_adapter] %d warnings during adapt", len(combined.errors))
    return combined
