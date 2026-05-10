"""What-if simulator — generates candidate environment parameter combinations
and estimates yield/revenue impact for each.

Used by profit_optimizer to find the highest-ROI adjustments.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import itertools


@dataclass
class EnvState:
    """Current environment snapshot for a farm (canonical names → values)."""
    farm_id: str
    values: dict[str, float] = field(default_factory=dict)


@dataclass
class Candidate:
    """One proposed environment adjustment."""
    changes: dict[str, float]       # canonical_name → new value
    description_ko: str             # human-readable Korean description


# Adjustment steps per variable (±delta options to try)
_ADJUSTMENT_DELTAS: dict[str, list[float]] = {
    "temp_internal":  [-2.0, -1.0, +1.0, +2.0],
    "humidity_int":   [-10.0, -5.0, +5.0, +10.0],
    "co2_ppm":        [-200.0, +200.0, +400.0],
    "solar_rad":      [+50.0, +100.0, +200.0],
    "ec_dsm":         [-0.5, +0.5, +1.0],
}

_PARAM_LABELS_KO: dict[str, str] = {
    "temp_internal": "내부 온도",
    "humidity_int":  "내부 습도",
    "co2_ppm":       "CO₂ 농도",
    "solar_rad":     "일사량",
    "ec_dsm":        "EC",
}

_UNIT_LABELS: dict[str, str] = {
    "temp_internal": "°C",
    "humidity_int":  "%",
    "co2_ppm":       "ppm",
    "solar_rad":     "W/m²",
    "ec_dsm":        "dS/m",
}

# Valid bounds for generated candidates
_BOUNDS: dict[str, tuple[float, float]] = {
    "temp_internal": (10.0, 40.0),
    "humidity_int":  (40.0, 95.0),
    "co2_ppm":       (400.0, 2000.0),
    "solar_rad":     (0.0, 1500.0),
    "ec_dsm":        (0.5, 4.0),
}


def _format_delta(name: str, delta: float) -> str:
    unit = _UNIT_LABELS.get(name, "")
    sign = "+" if delta >= 0 else ""
    return f"{_PARAM_LABELS_KO.get(name, name)} {sign}{delta:.1f}{unit}"


def generate_candidates(current: EnvState, max_simultaneous: int = 1) -> list[Candidate]:
    """Generate single-variable adjustment candidates from the current state.

    Args:
        current:          current environment snapshot
        max_simultaneous: max number of variables to adjust at once
                          (keep at 1 for interpretable recommendations)
    """
    candidates: list[Candidate] = []
    for var, deltas in _ADJUSTMENT_DELTAS.items():
        current_val = current.values.get(var)
        if current_val is None:
            continue
        lo, hi = _BOUNDS.get(var, (-1e9, 1e9))
        for delta in deltas:
            new_val = current_val + delta
            if not (lo <= new_val <= hi):
                continue
            desc = _format_delta(var, delta)
            candidates.append(Candidate(changes={var: new_val}, description_ko=desc))
    return candidates
