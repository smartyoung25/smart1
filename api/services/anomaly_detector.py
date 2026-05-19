"""환경 이상 감지 서비스

engine/env_stats.json의 p5/p95 정상 범위 + mean/std로
현재 센서값의 이상 여부를 감지한다.

심각도:
  - critical : p5 미만 / p95 초과
  - major    : mean-2std 미만 / mean+2std 초과 (단, critical 아닐 때)
  - minor    : mean-1std 미만 / mean+1std 초과 (단, major 아닐 때)
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# engine/env_stats.json 이 권위 있는 소스
_ENV_STATS_PATH = Path(__file__).parent.parent.parent / "engine" / "env_stats.json"

_VAR_LABELS_KO = {
    "temp_internal": "내부 온도",
    "humidity_int":  "내부 습도",
    "co2_ppm":       "CO2 농도",
    "solar_rad":     "일사량",
    "ec_dsm":        "EC",
    "soil_temp":     "지온",
}
_UNITS = {
    "temp_internal": "도C",
    "humidity_int":  "%",
    "co2_ppm":       "ppm",
    "solar_rad":     "W/m2",
    "ec_dsm":        "dS/m",
    "soil_temp":     "도C",
}


@dataclass
class EnvAlert:
    variable:      str
    variable_ko:   str
    current_value: float
    normal_min:    float
    normal_max:    float
    unit:          str
    severity:      str     # "minor" | "major" | "critical"
    message_ko:    str


@lru_cache(maxsize=None)
def _load_stats() -> dict:
    if _ENV_STATS_PATH.exists():
        try:
            return json.loads(_ENV_STATS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[anomaly] env_stats.json 로드 실패: %s", e)
    logger.warning("[anomaly] env_stats.json 없음: %s", _ENV_STATS_PATH)
    return {}


def detect_anomalies(crop_ko: str, env_values: dict[str, float]) -> list[EnvAlert]:
    """현재 환경값에서 이상치를 감지하여 EnvAlert 리스트 반환.

    env_stats.json 구조:
        {crop: {var: {mean, std, min, max, p5, p95, delta_step, unit}}}

    심각도 기준:
        critical : val < p5 또는 val > p95
        major    : val < mean-2*std 또는 val > mean+2*std  (p5~p95 내)
        minor    : val < mean-1*std 또는 val > mean+1*std  (±2std 내)
    """
    stats = _load_stats()
    crop_stats = stats.get(crop_ko, {})
    if not crop_stats:
        logger.debug("[anomaly] 작물 통계 없음: %s", crop_ko)
        return []

    alerts: list[EnvAlert] = []

    for var, val in env_values.items():
        vstat = crop_stats.get(var)
        if vstat is None:
            continue

        p5   = float(vstat.get("p5",  vstat.get("min", -1e9)))
        p95  = float(vstat.get("p95", vstat.get("max",  1e9)))
        mean = float(vstat.get("mean", (p5 + p95) / 2))
        std  = float(vstat.get("std",  (p95 - p5) / 4))

        label = _VAR_LABELS_KO.get(var, var)
        unit  = _UNITS.get(var, vstat.get("unit", ""))

        if val < p5 or val > p95:
            severity  = "critical"
            direction = "너무 낮음" if val < p5 else "너무 높음"
            msg = (f"[CRITICAL] {label} {val}{unit} — "
                   f"정상 범위({p5:.1f}~{p95:.1f}{unit}) {direction}")
            alerts.append(EnvAlert(
                variable=var, variable_ko=label,
                current_value=val, normal_min=p5, normal_max=p95,
                unit=unit, severity=severity, message_ko=msg,
            ))
        elif val < mean - 2 * std or val > mean + 2 * std:
            severity  = "major"
            direction = "낮음" if val < mean else "높음"
            msg = (f"[MAJOR] {label} {val}{unit} — "
                   f"평균({mean:.1f}{unit}) 대비 크게 {direction}")
            alerts.append(EnvAlert(
                variable=var, variable_ko=label,
                current_value=val, normal_min=round(mean - 2*std, 1),
                normal_max=round(mean + 2*std, 1),
                unit=unit, severity=severity, message_ko=msg,
            ))
        elif val < mean - std or val > mean + std:
            severity  = "minor"
            direction = "낮음" if val < mean else "높음"
            msg = (f"[MINOR] {label} {val}{unit} — "
                   f"평균({mean:.1f}{unit}) 대비 {direction}")
            alerts.append(EnvAlert(
                variable=var, variable_ko=label,
                current_value=val, normal_min=round(mean - std, 1),
                normal_max=round(mean + std, 1),
                unit=unit, severity=severity, message_ko=msg,
            ))

    _order = {"critical": 0, "major": 1, "minor": 2}
    alerts.sort(key=lambda a: _order.get(a.severity, 9))
    return alerts
