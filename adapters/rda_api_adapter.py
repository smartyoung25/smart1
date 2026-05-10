"""농진청(RDA) API adapter — maps API response fields to canonical variables.

농진청 provides environment + growth measurement data.
Growth data (초장, 엽수, etc.) maps to M1 Ground Truth variables.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
import logging

from adapters.base_adapter import (
    AdapterResult, NormalizedRecord, safe_float, validate_range,
)

logger = logging.getLogger(__name__)

SOURCE_ID = "rda_api"
QUALITY_TAG = "FINETUNED"

_FIELD_MAP: dict[str, tuple[str, Any]] = {
    # Environment
    "내부온도":       ("temp_internal",  None),
    "내부습도":       ("humidity_int",   None),
    # Growth measurements (ground truth for M1)
    "수확량":         ("yield_kg_m2",    None),
    "초장":           ("plant_height",   None),
    "엽수":           ("leaf_count",     None),
    "엽장":           ("leaf_length",    None),
    "엽폭":           ("leaf_width",     None),
    "관부직경":       ("crown_diameter", None),
    "화방별착과수":   ("fruit_count",    None),
}


def adapt_record(
    data: dict[str, Any],
    farm_id: str,
    time: datetime,
) -> AdapterResult:
    """Convert one RDA API response object to NormalizedRecords."""
    result = AdapterResult()
    for src_field, (canonical, transform) in _FIELD_MAP.items():
        raw = data.get(src_field)
        if raw is None:
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


def adapt_response_list(
    items: list[dict[str, Any]],
    farm_id: str,
    time_key: str = "측정일시",
) -> AdapterResult:
    """Adapt a list of RDA API response items.

    Args:
        items:    list of dict records from the API
        farm_id:  farm identifier
        time_key: key for the timestamp field in each item
    """
    combined = AdapterResult()
    for item in items:
        raw_time = item.get(time_key)
        try:
            time = datetime.fromisoformat(str(raw_time))
        except (ValueError, TypeError):
            combined.errors.append(f"[{SOURCE_ID}] bad timestamp '{raw_time}' — item skipped")
            continue
        r = adapt_record(item, farm_id, time)
        combined.records.extend(r.records)
        combined.errors.extend(r.errors)
    if combined.errors:
        logger.warning("[rda_api_adapter] %d warnings", len(combined.errors))
    return combined
