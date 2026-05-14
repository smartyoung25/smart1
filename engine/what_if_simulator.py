"""What-if simulator — generates candidate environment parameter combinations
and estimates yield/revenue impact for each.

Used by profit_optimizer to find the highest-ROI adjustments.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
import itertools

logger = logging.getLogger(__name__)

_ENV_STATS_PATH = Path(__file__).parent.parent / "api" / "data" / "env_stats.json"


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


_PARAM_LABELS_KO: dict[str, str] = {
    "temp_internal": "내부 온도",
    "humidity_int":  "내부 습도",
    "co2_ppm":       "CO2 농도",
    "solar_rad":     "일사량",
    "ec_dsm":        "EC",
}

_UNIT_LABELS: dict[str, str] = {
    "temp_internal": "°C",
    "humidity_int":  "%",
    "co2_ppm":       "ppm",
    "solar_rad":     "W/m2",
    "ec_dsm":        "dS/m",
}

# Fallback adjustment deltas (used when env_stats.json not available)
_ADJUSTMENT_DELTAS_FALLBACK: dict[str, list[float]] = {
    "temp_internal":  [-2.0, -1.0, +1.0, +2.0],
    "humidity_int":   [-10.0, -5.0, +5.0, +10.0],
    "co2_ppm":        [-200.0, +200.0, +400.0],
    "solar_rad":      [+50.0, +100.0, +200.0],
    "ec_dsm":         [-0.5, +0.5, +1.0],
}

# Fallback bounds (used when env_stats.json not available)
_BOUNDS_FALLBACK: dict[str, tuple[float, float]] = {
    "temp_internal": (10.0, 40.0),
    "humidity_int":  (40.0, 95.0),
    "co2_ppm":       (400.0, 2000.0),
    "solar_rad":     (0.0, 1500.0),
    "ec_dsm":        (0.5, 4.0),
}


@lru_cache(maxsize=None)
def _load_env_stats() -> dict:
    if not _ENV_STATS_PATH.exists():
        return {}
    try:
        return json.loads(_ENV_STATS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[what_if_simulator] env_stats.json 로드 실패: %s", e)
        return {}


def get_adjustment_deltas(crop_ko: str = "딸기") -> dict[str, list[float]]:
    """env_stats.json의 조정_델타 로드. 없으면 폴백 사용."""
    stats = _load_env_stats()
    crop_stats = stats.get(crop_ko, {})
    delta_map = crop_stats.get("조정_델타", {})
    if not delta_map:
        return dict(_ADJUSTMENT_DELTAS_FALLBACK)
    result: dict[str, list[float]] = {}
    for var, deltas in delta_map.items():
        if var in _ADJUSTMENT_DELTAS_FALLBACK:
            result[var] = sorted(set(deltas))
    # keep fallback for variables missing in env_stats
    for var in _ADJUSTMENT_DELTAS_FALLBACK:
        if var not in result:
            result[var] = _ADJUSTMENT_DELTAS_FALLBACK[var]
    return result


def get_bounds(crop_ko: str = "딸기") -> dict[str, tuple[float, float]]:
    """env_stats.json의 최적_범위를 확장하여 탐색 범위로 사용.

    최적범위(P25-P75)를 3배 확장하여 상하한 설정.
    범위가 없으면 폴백 사용.
    """
    stats = _load_env_stats()
    crop_stats = stats.get(crop_ko, {})
    optimal = crop_stats.get("최적_범위", {})
    if not optimal:
        return dict(_BOUNDS_FALLBACK)
    result: dict[str, tuple[float, float]] = {}
    for var, (p25, p75) in optimal.items():
        if var not in _BOUNDS_FALLBACK:
            continue
        width = p75 - p25
        lo = round(p25 - width * 1.5, 1)
        hi = round(p75 + width * 1.5, 1)
        fallback_lo, fallback_hi = _BOUNDS_FALLBACK[var]
        result[var] = (max(lo, fallback_lo), min(hi, fallback_hi))
    for var in _BOUNDS_FALLBACK:
        if var not in result:
            result[var] = _BOUNDS_FALLBACK[var]
    return result


def _format_delta(name: str, delta: float) -> str:
    unit = _UNIT_LABELS.get(name, "")
    sign = "+" if delta >= 0 else ""
    return f"{_PARAM_LABELS_KO.get(name, name)} {sign}{delta:.1f}{unit}"


def generate_candidates(
    current: EnvState,
    max_simultaneous: int = 1,
    crop_ko: str = "딸기",
) -> list[Candidate]:
    """Generate single-variable adjustment candidates from the current state.

    Args:
        current:          current environment snapshot
        max_simultaneous: max number of variables to adjust at once
                          (keep at 1 for interpretable recommendations)
        crop_ko:          Korean crop name for loading env_stats bounds/deltas
    """
    adj_deltas = get_adjustment_deltas(crop_ko)
    bounds     = get_bounds(crop_ko)
    candidates: list[Candidate] = []
    for var, deltas in adj_deltas.items():
        current_val = current.values.get(var)
        if current_val is None:
            continue
        lo, hi = bounds.get(var, (-1e9, 1e9))
        for delta in deltas:
            new_val = current_val + delta
            if not (lo <= new_val <= hi):
                continue
            desc = _format_delta(var, delta)
            candidates.append(Candidate(changes={var: new_val}, description_ko=desc))
    return candidates
