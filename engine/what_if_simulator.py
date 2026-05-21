"""What-if simulator v2 — environment adjustment candidate generator

개선 사항 (2026-05-20):
  - 작기 단계(초기/중기/후기)별 조정 델타 차등화
  - VPD 최적 범위 타겟 후보 추가 (온도·습도 복합 조정)
  - 개화기(mid) 구간 후보 수 확대 및 민감 구간 집중

Used by profit_optimizer to find the highest-ROI adjustments.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ENV_STATS_PATH = Path(__file__).parent.parent / "api" / "data" / "env_stats.json"

# ── 작기 단계 정의 (anomaly_detector와 동일 기준) ─────────────────────────────
_SEASON_STAGES: dict[str, dict[str, list[int]]] = {
    "딸기":     {"early": [9, 10],    "mid": [11, 12, 1, 2], "late": [3, 4, 5]},
    "방울토마토": {"early": [2, 3],     "mid": [4, 5, 6, 7],   "late": [8, 9, 10]},
    "완숙토마토": {"early": [2, 3],     "mid": [4, 5, 6, 7],   "late": [8, 9, 10]},
    "참외":     {"early": [3, 4],     "mid": [5, 6],          "late": [7, 8]},
    "파프리카":  {"early": [1, 2],     "mid": [3, 4, 5, 6, 7], "late": [8, 9, 10]},
}

# ── 작기 단계별 조정 우선 변수 ───────────────────────────────────────────────
# early: 뿌리 활착 → 온도·지온 중요
# mid  : 개화·착과 → CO2·VPD 중요
# late : 수확량 확보 → 광량·EC 중요
_STAGE_PRIORITY_VARS: dict[str, list[str]] = {
    "early":   ["temp_internal", "soil_temp", "humidity_int"],
    "mid":     ["co2_ppm", "temp_internal", "humidity_int", "ec_dsm"],
    "late":    ["solar_rad", "ec_dsm", "co2_ppm"],
    "unknown": ["temp_internal", "co2_ppm", "humidity_int"],
}

# ── 작기 단계별 델타 스케일 계수 ─────────────────────────────────────────────
# mid(개화기): 조정폭을 작게 → 세밀한 제어
# early/late: 조정폭 정상
_STAGE_DELTA_SCALE: dict[str, float] = {
    "early":   1.0,
    "mid":     0.6,   # 개화기: ±60% 스케일로 세밀하게
    "late":    1.0,
    "unknown": 1.0,
}

# ── VPD 최적 범위 (anomaly_detector와 동일) ───────────────────────────────────
_VPD_OPTIMAL: dict[str, dict[str, tuple[float, float]]] = {
    "딸기":     {"early": (0.4, 0.8), "mid": (0.6, 1.0), "late": (0.5, 0.9)},
    "방울토마토": {"early": (0.6, 1.0), "mid": (0.8, 1.4), "late": (0.8, 1.2)},
    "완숙토마토": {"early": (0.6, 1.0), "mid": (0.8, 1.4), "late": (0.8, 1.2)},
    "참외":     {"early": (0.5, 0.9), "mid": (0.7, 1.2), "late": (0.6, 1.0)},
    "파프리카":  {"early": (0.6, 1.0), "mid": (0.8, 1.2), "late": (0.7, 1.1)},
}

@dataclass
class EnvState:
    """Current environment snapshot for a farm (canonical names -> values)."""
    farm_id: str
    values: dict[str, float] = field(default_factory=dict)


@dataclass
class Candidate:
    """One proposed environment adjustment."""
    changes:        dict[str, float]
    description_ko: str
    stage:          str = "unknown"   # 생성 시 작기 단계 기록
    target_type:    str = "single"    # "single" | "combo" | "vpd_target"


_PARAM_LABELS_KO: dict[str, str] = {
    "temp_internal": "내부 온도",
    "humidity_int":  "내부 습도",
    "co2_ppm":       "CO2 농도",
    "solar_rad":     "일사량",
    "ec_dsm":        "EC",
    "soil_temp":     "지온",
}
_UNIT_LABELS: dict[str, str] = {
    "temp_internal": "℃",
    "humidity_int":  "%",
    "co2_ppm":       "ppm",
    "solar_rad":     "W/m²",
    "ec_dsm":        "dS/m",
    "soil_temp":     "℃",
}

# ── 관수 지표 기준값 (Priva 표준) ─────────────────────────────────────────────
_DR_NORMAL_MIN = 20.0   # 배액률 정상 하한 (%)
_DR_NORMAL_MAX = 40.0   # 배액률 정상 상한 (%)
_SUPPLY_MIN_ML = 100.0  # 공급량 최소값 (ml/slab/day)

# Fallback adjustment deltas
_ADJUSTMENT_DELTAS_FALLBACK: dict[str, list[float]] = {
    "temp_internal":  [-2.0, -1.0, +1.0, +2.0],
    "humidity_int":   [-10.0, -5.0, +5.0, +10.0],
    "co2_ppm":        [-200.0, +200.0, +400.0],
    "solar_rad":      [+50.0, +100.0, +200.0],
    "ec_dsm":         [-0.5, +0.5, +1.0],
}
_BOUNDS_FALLBACK: dict[str, tuple[float, float]] = {
    "temp_internal": (10.0, 40.0),
    "humidity_int":  (40.0, 95.0),
    "co2_ppm":       (400.0, 2000.0),
    "solar_rad":     (0.0, 1500.0),
    "ec_dsm":        (0.5, 4.0),
}

# Agronomically meaningful 2-variable pairs
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


def get_season_stage(crop_ko: str, month: int) -> str:
    """현재 월 기반 작기 단계 반환."""
    stages = _SEASON_STAGES.get(crop_ko, {})
    for stage, months in stages.items():
        if month in months:
            return stage
    return "unknown"


def get_adjustment_deltas(
    crop_ko: str = "딸기",
    stage: str = "unknown",
) -> dict[str, list[float]]:
    """작기 단계 반영 조정 델타 로드.

    stage='mid'(개화기)이면 델타 스케일을 줄여 세밀한 제어 후보 생성.
    """
    stats      = _load_env_stats()
    crop_stats = stats.get(crop_ko, {})
    delta_map  = crop_stats.get("조정_델타", {})
    scale      = _STAGE_DELTA_SCALE.get(stage, 1.0)

    result: dict[str, list[float]] = {}
    for var, fallback_deltas in _ADJUSTMENT_DELTAS_FALLBACK.items():
        raw_deltas = delta_map.get(var, fallback_deltas)
        scaled = sorted({round(d * scale, 2) for d in raw_deltas if d != 0})
        result[var] = scaled or fallback_deltas
    return result


def get_bounds(crop_ko: str = "딸기") -> dict[str, tuple[float, float]]:
    """작물별 환경 조정 탐색 범위."""
    stats      = _load_env_stats()
    crop_stats = stats.get(crop_ko, {})
    optimal    = crop_stats.get("최적_범위", {})
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


def _calc_vpd(temp_c: float, humidity_pct: float) -> float:
    """VPD(kPa) 계산."""
    if humidity_pct <= 0 or humidity_pct > 100:
        return float("nan")
    svp = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
    return svp * (1.0 - humidity_pct / 100.0)


def _vpd_target_candidates(
    crop_ko: str,
    current: EnvState,
    stage: str,
    bounds: dict[str, tuple[float, float]],
) -> list[Candidate]:
    """VPD 최적 범위 진입을 목표로 온도·습도 조합 후보 생성.

    현재 VPD가 최적 범위를 이탈한 경우에만 후보 생성.
    온도와 습도를 함께 조정하여 VPD를 최적 범위 중앙값으로 수렴.
    """
    temp = current.values.get("temp_internal")
    humi = current.values.get("humidity_int")
    if temp is None or humi is None:
        return []

    current_vpd = _calc_vpd(temp, humi)
    if math.isnan(current_vpd):
        return []

    optimal_ranges = _VPD_OPTIMAL.get(crop_ko, _VPD_OPTIMAL.get("방울토마토"))
    vpd_min, vpd_max = optimal_ranges.get(stage, optimal_ranges.get("mid", (0.6, 1.2)))
    vpd_target = (vpd_min + vpd_max) / 2.0

    # VPD가 이미 최적 범위 안이면 후보 불필요
    if vpd_min <= current_vpd <= vpd_max:
        return []

    candidates: list[Candidate] = []
    t_lo, t_hi = bounds.get("temp_internal", (10.0, 40.0))
    h_lo, h_hi = bounds.get("humidity_int",  (40.0, 95.0))

    # 온도를 ±1, ±2°C 변화 → 목표 VPD 달성에 필요한 습도 역산
    for dt in [-2.0, -1.0, +1.0, +2.0]:
        new_t = round(temp + dt, 1)
        if not (t_lo <= new_t <= t_hi):
            continue
        # svp(new_t) × (1 - h_target/100) = vpd_target
        # → h_target = (1 - vpd_target/svp) × 100
        svp_new = 0.6108 * math.exp(17.27 * new_t / (new_t + 237.3))
        if svp_new <= 0:
            continue
        h_target = round((1.0 - vpd_target / svp_new) * 100.0, 1)
        if not (h_lo <= h_target <= h_hi):
            continue
        dh = round(h_target - humi, 1)
        if abs(dh) < 1.0:
            continue

        vpd_new = _calc_vpd(new_t, h_target)
        desc = (
            f"내부 온도 {'+' if dt>=0 else ''}{dt:.1f}℃ + "
            f"내부 습도 {'+' if dh>=0 else ''}{dh:.1f}% "
            f"→ VPD {current_vpd:.2f}→{vpd_new:.2f}kPa (목표 {vpd_target:.2f}kPa)"
        )
        candidates.append(Candidate(
            changes={"temp_internal": new_t, "humidity_int": h_target},
            description_ko=desc,
            stage=stage,
            target_type="vpd_target",
        ))

    return candidates


def _representative_deltas(var: str, all_deltas: list[float]) -> list[float]:
    """콤보 후보용 대표 델타 2개 선택."""
    pos = [d for d in all_deltas if d > 0]
    neg = [d for d in all_deltas if d < 0]
    reps: list[float] = []
    if pos:
        reps.append(min(pos))
    if neg:
        reps.append(max(neg))
    return reps


def _format_delta(name: str, delta: float) -> str:
    unit = _UNIT_LABELS.get(name, "")
    sign = "+" if delta >= 0 else ""
    return f"{_PARAM_LABELS_KO.get(name, name)} {sign}{delta:.1f}{unit}"


def _drain_fraction_candidates(
    current: EnvState,
    stage: str,
) -> list[Candidate]:
    """배액률(dr_pct_mean) 이탈 시 총 공급량(supply_total) ±10/20% 조정 후보 생성.

    Priva 일사비례 관수 규칙:
      - 배액률 < 20%: 공급 부족 → 공급량 증량 또는 트리거 임계값 낮춤
      - 배액률 > 40%: 과잉 공급 → 공급량 감량 또는 트리거 간격 연장
    supply_total 없으면 대표값 1000ml/slab으로 추정.
    """
    dr = current.values.get("dr_pct_mean")
    if dr is None:
        return []
    # 정상 범위 내이면 후보 불필요
    if _DR_NORMAL_MIN <= dr <= _DR_NORMAL_MAX:
        return []

    supply = current.values.get("supply_total")
    if supply is None or supply <= 0:
        supply = 1000.0   # fallback 대표값 (ml/slab/day)
        supply_note = " (추정값)"
    else:
        supply_note = ""

    candidates: list[Candidate] = []

    if dr < _DR_NORMAL_MIN:
        # 공급 부족 → 증량
        for pct in [0.10, 0.20]:
            new_supply = round(supply * (1 + pct))
            new_supply = max(_SUPPLY_MIN_ML, new_supply)
            desc = (
                f"총 공급량 +{pct*100:.0f}%{supply_note} "
                f"({supply:.0f}→{new_supply:.0f}ml/slab) — "
                f"배액률 {dr:.1f}% < {_DR_NORMAL_MIN:.0f}% (공급 부족, 근권 건조 위험)"
            )
            candidates.append(Candidate(
                changes={"supply_total": new_supply},
                description_ko=desc,
                stage=stage,
                target_type="irrigation",
            ))
    else:
        # 과잉 공급 → 감량
        for pct in [0.10, 0.20]:
            new_supply = round(supply * (1 - pct))
            new_supply = max(_SUPPLY_MIN_ML, new_supply)
            desc = (
                f"총 공급량 -{pct*100:.0f}%{supply_note} "
                f"({supply:.0f}→{new_supply:.0f}ml/slab) — "
                f"배액률 {dr:.1f}% > {_DR_NORMAL_MAX:.0f}% (과잉 공급, 양분 손실)"
            )
            candidates.append(Candidate(
                changes={"supply_total": new_supply},
                description_ko=desc,
                stage=stage,
                target_type="irrigation",
            ))

    return candidates


def generate_candidates(
    current: EnvState,
    max_simultaneous: int = 2,
    crop_ko: str = "딸기",
    month: Optional[int] = None,
) -> list[Candidate]:
    """환경 조정 후보 생성.

    작기 단계를 고려:
      - 우선 변수를 단계별로 앞배치
      - mid(개화기) 구간은 델타 스케일을 줄여 세밀한 후보 생성
      - VPD 최적 범위 이탈 시 VPD 타겟 후보 추가

    Args:
        current:          현재 환경 스냅샷
        max_simultaneous: 1=단변수, 2=2변수 콤보 포함
        crop_ko:          작물명(한국어)
        month:            현재 월 (None이면 today 사용)
    """
    import datetime as _dt
    if month is None:
        month = _dt.date.today().month

    stage      = get_season_stage(crop_ko, month)
    adj_deltas = get_adjustment_deltas(crop_ko, stage)
    bounds     = get_bounds(crop_ko)
    priority   = _STAGE_PRIORITY_VARS.get(stage, _STAGE_PRIORITY_VARS["unknown"])

    candidates: list[Candidate] = []
    seen: set[frozenset] = set()

    def _add(changes: dict[str, float], desc: str,
             ttype: str = "single") -> None:
        key = frozenset((k, round(v, 4)) for k, v in changes.items())
        if key in seen:
            return
        seen.add(key)
        candidates.append(Candidate(
            changes=changes, description_ko=desc,
            stage=stage, target_type=ttype,
        ))

    # ── 1. 단변수 후보 (우선 변수 먼저) ─────────────────────────────────────
    ordered_vars = list(dict.fromkeys(priority + list(adj_deltas.keys())))
    for var in ordered_vars:
        deltas = adj_deltas.get(var, [])
        if not deltas:
            continue
        current_val = current.values.get(var)
        if current_val is None:
            continue
        lo, hi = bounds.get(var, (-1e9, 1e9))
        for delta in deltas:
            new_val = round(current_val + delta, 4)
            if not (lo <= new_val <= hi):
                continue
            _add({var: new_val}, _format_delta(var, delta))

    # ── 2. VPD 타겟 후보 (온도+습도 복합, VPD 이탈 시) ──────────────────────
    vpd_cands = _vpd_target_candidates(crop_ko, current, stage, bounds)
    for vc in vpd_cands:
        key = frozenset((k, round(v, 4)) for k, v in vc.changes.items())
        if key not in seen:
            seen.add(key)
            candidates.append(vc)

    # ── 3. 2변수 콤보 후보 ───────────────────────────────────────────────────
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
                    desc = (f"{_format_delta(var_a, da)} + "
                            f"{_format_delta(var_b, db)}")
                    _add({var_a: new_a, var_b: new_b}, desc, ttype="combo")

    # ── 4. 배액률 이탈 시 관수 공급량 조정 후보 ──────────────────────────────────
    drain_cands = _drain_fraction_candidates(current, stage)
    for dc in drain_cands:
        key = frozenset((k, round(v, 4)) for k, v in dc.changes.items())
        if key not in seen:
            seen.add(key)
            candidates.append(dc)

    logger.debug(
        "[what_if_simulator] crop=%s stage=%s month=%d candidates=%d "
        "(single=%d vpd=%d combo=%d irr=%d)",
        crop_ko, stage, month, len(candidates),
        sum(1 for c in candidates if c.target_type == "single"),
        sum(1 for c in candidates if c.target_type == "vpd_target"),
        sum(1 for c in candidates if c.target_type == "combo"),
        sum(1 for c in candidates if c.target_type == "irrigation"),
    )
    return candidates
