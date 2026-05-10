"""WUR (Wageningen University) dataset adapter — one-time historical CSV import.

Maps English column names from WUR greenhouse dataset to canonical variables.
EC_solution is already in dS/m so no unit conversion is needed.
Quality tag is TRANSFER (foreign dataset, not locally calibrated).
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
import logging

from adapters.base_adapter import (
    AdapterResult, NormalizedRecord, safe_float, validate_range,
)

logger = logging.getLogger(__name__)

SOURCE_ID = "wur_dataset"
QUALITY_TAG = "TRANSFER"

_FIELD_MAP: dict[str, tuple[str, Any]] = {
    "T_air":          ("temp_internal",  None),
    "CO2_conc":       ("co2_ppm",        None),
    "I_glob":         ("solar_rad",      None),
    "EC_solution":    ("ec_dsm",         None),   # already dS/m
    "Fresh_weight":   ("yield_kg_m2",    None),
}


def adapt_row(
    row: dict[str, Any],
    farm_id: str,
    time: datetime,
) -> AdapterResult:
    """Convert one WUR CSV row to NormalizedRecords."""
    result = AdapterResult()
    for src_field, (canonical, transform) in _FIELD_MAP.items():
        raw = row.get(src_field)
        if raw is None or str(raw).strip() in ("", "NaN", "nan", "NA"):
            continue
        value = safe_float(raw)
        if value is None:
            result.errors.append(f"[{SOURCE_ID}] {src_field}='{raw}' not numeric — skipped")
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


def adapt_dataframe(
    df,
    farm_id: str,
    time_col: str = "DateTime",
) -> AdapterResult:
    """Adapt a WUR dataset DataFrame.

    Args:
        df:       pandas DataFrame with English column names
        farm_id:  farm identifier (WUR data maps to a reference farm)
        time_col: name of the timestamp column in the WUR CSV
    """
    combined = AdapterResult()
    for _, row in df.iterrows():
        raw_time = row.get(time_col)
        try:
            time = datetime.fromisoformat(str(raw_time))
        except (ValueError, TypeError):
            combined.errors.append(f"[{SOURCE_ID}] bad timestamp '{raw_time}' — row skipped")
            continue
        r = adapt_row(row.to_dict(), farm_id, time)
        combined.records.extend(r.records)
        combined.errors.extend(r.errors)
    logger.info(
        "[wur_dataset_adapter] %d records adapted, %d warnings",
        len(combined.records),
        len(combined.errors),
    )
    return combined
