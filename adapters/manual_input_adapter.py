"""Manual input adapter — converts farmer-submitted growth/harvest records to NormalizedRecords.

Farmer entries come from the manual_inputs table (payload JSONB).
input_type determines which fields are expected:
  harvest        → yield_kg_m2
  growth_survey  → plant_height, leaf_count, leaf_length, leaf_width, crown_diameter, fruit_count
  disease_report → (no numeric measurements; ignored here)
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
import logging

from adapters.base_adapter import (
    AdapterResult, NormalizedRecord, safe_float, validate_range,
)

logger = logging.getLogger(__name__)

SOURCE_ID = "manual"
QUALITY_TAG = "FINETUNED"

_HARVEST_FIELDS: dict[str, str] = {
    "harvest_weight": "yield_kg_m2",
}

_GROWTH_FIELDS: dict[str, str] = {
    "plant_height_cm": "plant_height",
    "leaf_count":      "leaf_count",
    "leaf_length_cm":  "leaf_length",
    "leaf_width_cm":   "leaf_width",
    "crown_dia_mm":    "crown_diameter",
    "fruit_count":     "fruit_count",
}


def _adapt_payload(
    payload: dict[str, Any],
    field_map: dict[str, str],
    farm_id: str,
    time: datetime,
) -> AdapterResult:
    result = AdapterResult()
    for src_field, canonical in field_map.items():
        raw = payload.get(src_field)
        if raw is None:
            continue
        value = safe_float(raw)
        if value is None:
            result.errors.append(
                f"[{SOURCE_ID}] {src_field}='{raw}' not numeric — skipped"
            )
            continue
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


def adapt_manual_input(
    farm_id: str,
    input_type: str,
    recorded_at: datetime,
    payload: dict[str, Any],
) -> AdapterResult:
    """Adapt a single manual_inputs row.

    Args:
        farm_id:     farm identifier
        input_type:  'harvest' | 'growth_survey' | 'disease_report'
        recorded_at: observation timestamp
        payload:     JSONB payload dict from the manual_inputs table
    """
    if input_type == "harvest":
        return _adapt_payload(payload, _HARVEST_FIELDS, farm_id, recorded_at)
    if input_type == "growth_survey":
        return _adapt_payload(payload, _GROWTH_FIELDS, farm_id, recorded_at)
    # disease_report has no numeric measurements to normalize
    return AdapterResult()


def adapt_manual_input_rows(rows: list[dict[str, Any]]) -> AdapterResult:
    """Batch-adapt rows fetched from the manual_inputs table.

    Each row dict must have: farm_id, input_type, recorded_at (ISO string), payload (dict).
    """
    combined = AdapterResult()
    for row in rows:
        try:
            recorded_at = datetime.fromisoformat(str(row["recorded_at"]))
        except (KeyError, ValueError, TypeError) as exc:
            combined.errors.append(f"[{SOURCE_ID}] bad recorded_at — row skipped: {exc}")
            continue
        r = adapt_manual_input(
            farm_id=row.get("farm_id", "unknown"),
            input_type=row.get("input_type", ""),
            recorded_at=recorded_at,
            payload=row.get("payload", {}),
        )
        combined.records.extend(r.records)
        combined.errors.extend(r.errors)
    if combined.errors:
        logger.warning("[manual_input_adapter] %d warnings", len(combined.errors))
    return combined
