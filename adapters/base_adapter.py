from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

QualityTag = str  # FINETUNED | TRANSFER | SIMULATION | LITERATURE


@dataclass
class NormalizedRecord:
    time: datetime
    farm_id: str
    canonical_name: str
    value: float
    source_id: str
    quality_tag: QualityTag = "FINETUNED"
    imputed: bool = False


@dataclass
class AdapterResult:
    records: list[NormalizedRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# canonical_name → (valid_min, valid_max)
VALID_RANGES: dict[str, tuple[Optional[float], Optional[float]]] = {
    "temp_internal":  (0, 60),
    "temp_external":  (-20, 50),
    "humidity_int":   (0, 100),
    "co2_ppm":        (0, 5000),
    "solar_rad":      (0, 1500),
    "ec_dsm":         (0, 10),
    "ph":             (0, 14),
    "soil_temp":      (0, 50),
    "wind_speed_ext": (0, 50),
    "wind_dir_ext":   (0, 360),
    "cum_solar_ext":  (0, 99999),
    "rain_detect":    (0, 1),
    "yield_kg_m2":    (0, 100),
    "plant_height":   (0, 200),
    "leaf_count":     (0, 100),
    "leaf_length":    (0, 50),
    "leaf_width":     (0, 30),
    "crown_diameter": (0, 100),
    "fruit_count":    (0, 200),
    "kamis_price":    (0, 99999),
    "gdd_cumsum":     (0, 99999),
}


def validate_range(canonical_name: str, value: float) -> bool:
    import math
    if math.isnan(value) or math.isinf(value):
        return False
    bounds = VALID_RANGES.get(canonical_name)
    if bounds is None:
        return True
    low, high = bounds
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    return True


def safe_float(raw) -> Optional[float]:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
