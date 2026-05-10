"""KAMIS (농산물유통정보) price adapter.

Maps wholesale price data to kamis_price canonical variable.
KAMIS data is daily; temporal alignment to 1-hour grid is handled
by the pipeline (price is propagated forward within the day).
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
import logging

from adapters.base_adapter import (
    AdapterResult, NormalizedRecord, safe_float, validate_range,
)

logger = logging.getLogger(__name__)

SOURCE_ID = "kamis"
QUALITY_TAG = "FINETUNED"

# KAMIS API field → canonical
_FIELD_MAP: dict[str, tuple[str, Any]] = {
    "가격": ("kamis_price", None),
    # alternative field names used by different KAMIS API versions
    "price": ("kamis_price", None),
    "dpr1":  ("kamis_price", None),
}


def adapt_price_record(
    data: dict[str, Any],
    farm_id: str,
    time: datetime,
) -> AdapterResult:
    """Convert one KAMIS price record to a NormalizedRecord."""
    result = AdapterResult()
    for src_field, (canonical, transform) in _FIELD_MAP.items():
        raw = data.get(src_field)
        if raw is None:
            continue
        # KAMIS sometimes returns price as string with commas: "2,500"
        cleaned = str(raw).replace(",", "").strip()
        value = safe_float(cleaned)
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
        break  # one price field per record is sufficient
    return result


def adapt_response(
    items: list[dict[str, Any]],
    farm_id: str,
    date_key: str = "날짜",
) -> AdapterResult:
    """Adapt a list of KAMIS API price records.

    Args:
        items:    list of price dicts from KAMIS API
        farm_id:  farm identifier (price is platform-wide but tagged per farm)
        date_key: key for the date string ("YYYY-MM-DD")
    """
    combined = AdapterResult()
    for item in items:
        raw_date = item.get(date_key) or item.get("yyyy") or item.get("date")
        try:
            time = datetime.fromisoformat(str(raw_date))
        except (ValueError, TypeError):
            combined.errors.append(f"[{SOURCE_ID}] bad date '{raw_date}' — item skipped")
            continue
        r = adapt_price_record(item, farm_id, time)
        combined.records.extend(r.records)
        combined.errors.extend(r.errors)
    if combined.errors:
        logger.warning("[kamis_adapter] %d warnings", len(combined.errors))
    return combined
