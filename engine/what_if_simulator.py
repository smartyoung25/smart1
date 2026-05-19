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
    """Current environment snapshot for a farm (canonical names -> values)."""
    farm_id: str
    values: dict[str, float] = field(default_factory=dict)


@dataclass
class Candidate:
    """One proposed environment adjustment."""
    changes: dict[str, float]       # canonical_name -> new value
    description_ko: str             # human-readable Korean description


_PARAM_LABELS_KO: dict[str, str] = {
    "temp_internal": "내부 온도",
    "humidity_int":  "내부 습도",
    "co2_ppm":       "CO2 농도",
    "solar_rad":     "일사량",
    "ec_dsm":        "EC",
}

_UNIT_LABELS: dict[str, str] = {
    "temp_internal": "도C",
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

# Agronomically meaningful 2-variable pairs to try together
# (too cold + more CO2, lower temp + raise humidity, etc.)
_COMBO_PAIRS: list[tuple[str, str]] = [
    ("temp_internal", "co2_ppm"),
    ("temp_internal", "humidity_int"),
    ("temp_internal", "ec_dsm"),
    ("co2_ppm",       "humidity_int"),
    ("co2_ppm",       "ec_dsm"),
    ("humidity_int",  "ec_dsm"),
    ("solar_rad",     "temp_internal"),
    ("solar_rad",     "co2_ppm"),
]


@lru_cache(maxsize=None)
def _load_env_stats() -> dict:
    if not _ENV_STATS_PATH.exists():
        return {}
    try:
        return json.loads(_ENV_STATS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[what_if_simulator] env_stats.json load failed: %s", e)
        return {}


def get_adjustment_deltas(crop_ko: str = "딸기") -> dict[str, list[float]]:
    """Load adjustment deltas from env_stats.json, fallback if missing."""
    stats = _load_env_stats()
    crop_stats = stats.get(crop_ko, {})
    delta_map = crop_stats.get("조정_델타", {})
    if not delta_map:
        return dict(_ADJUSTMENT_DELTAS_FALLBACK)
    result: dict[str, list[float]] = {}
    for var, deltas in delta_map.items():
        if var in _ADJUSTMENT_DELTAS_FALLBACK:
            result[var] = sorted(set(deltas))
    for var in _ADJUSTMENT_DELTAS_FALLBACK:
        if var not in result:
            result[var] = _ADJUSTMENT_DELTAS_FALLBACK[var]
    return result


def get_bounds(crop_ko: str = "딸기") -> dict[str, tuple[float, float]]:
    """Load search bounds from env_stats.json optimal ranges (P25-P75 x3)."""
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


def _representative_deltas(var: str, all_deltas: list[float]) -> list[float]:
    """Pick at most 2 representative deltas per variable for combo candidates.

    Chooses the smallest positive and the largest negative delta to keep
    the combo candidate count manageable.
    """
    pos = [d for d in all_deltas if d > 0]
    neg = [d for d in all_deltas if d < 0]
    reps: list[float] = []
    if pos:
        reps.append(min(pos))      # smallest positive step
    if neg:
        reps.append(max(neg))      # smallest-magnitude negative step
    return reps


def _format_delta(name: str, delta: float) -> str:
    unit = _UNIT_LABELS.get(name, "")
    sign = "+" if delta >= 0 else ""
    return f"{_PARAM_LABELS_KO.get(name, name)} {sign}{delta:.1f}{unit}"


def generate_candidates(
    current: EnvState,
    max_simultaneous: int = 2,
    crop_ko: str = "딸기",
) -> list[Candidate]:
    """Generate environment adjustment candidates.

    Produces:
      - Single-variable candidates (all delta steps per variable)
      - Two-variable combination candidates (representative deltas,
        agronomically meaningful pairs only)

    Args:
        current:          current environment snapshot
        max_simultaneous: 1 = single-variable only, 2 = add pairwise combos
        crop_ko:          Korean crop name for env_stats lookup
    """
    adj_deltas = get_adjustment_deltas(crop_ko)
    bounds     = get_bounds(crop_ko)
    candidates: list[Candidate] = []
    seen: set[frozenset] = set()   # dedup by (var, new_val) pairs

    def _add(changes: dict[str, float], desc: str) -> None:
        key = frozenset((k, round(v, 4)) for k, v in changes.items())
        if key in seen:
            return
        seen.add(key)
        candidates.append(Candidate(changes=changes, description_ko=desc))

    # --- Single-variable candidates ---
    for var, deltas in adj_deltas.items():
        current_val = current.values.get(var)
        if current_val is None:
            continue
        lo, hi = bounds.get(var, (-1e9, 1e9))
        for delta in deltas:
            new_val = round(current_val + delta, 4)
            if not (lo <= new_val <= hi):
                continue
            _add({var: new_val}, _format_delta(var, delta))

    # --- Two-variable combination candidates ---
    if max_simultaneous >= 2:
        for var_a, var_b in _COMBO_PAIRS:
            val_a = current.values.get(var_a)
            val_b = current.values.get(var_b)
            if val_a is None or val_b is None:
                continue
            lo_a, hi_a = bounds.get(var_a, (-1e9, 1e9))
            lo_b, hi_b = bounds.get(var_b, (-1e9, 1e9))
            deltas_a = _representative_deltas(var_a, adj_deltas.get(var_a, []))
            deltas_b = _representative_deltas(var_b, adj_deltas.get(var_b, []))
            for da in deltas_a:
                for db in deltas_b:
                    new_a = round(val_a + da, 4)
                    new_b = round(val_b + db, 4)
                    if not (lo_a <= new_a <= hi_a):
                        continue
                    if not (lo_b <= new_b <= hi_b):
                        continue
                    desc = f"{_format_delta(var_a, da)} + {_format_delta(var_b, db)}"
                    _add({var_a: new_a, var_b: new_b}, desc)

    logger.debug("[what_if_simulator] crop=%s candidates=%d", crop_ko, len(candidates))
    return candidates
