"""환경 이상 감지 서비스 v2

개선 사항 (2026-05-20):
  - VPD(증기압포차) 계산 및 작목별 최적 범위 이탈 감지 추가
  - 작기 단계(초기/중기/후기)별 차등 임계값 적용
  - 계절(월) 기반 정상 범위 동적 조정

engine/env_stats.json의 p5/p95 정상 범위 + mean/std로
현재 센서값의 이상 여부를 감지한다.

심각도:
  - critical : p5 미만 / p95 초과
  - major    : mean-2std 미만 / mean+2std 초과 (단, critical 아닐 때)
  - minor    : mean-1std 미만 / mean+1std 초과 (단, major 아닐 때)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_ENV_STATS_PATH = Path(__file__).parent.parent.parent / "engine" / "env_stats.json"

_VAR_LABELS_KO = {
    "temp_internal": "내부 온도",
    "humidity_int":  "내부 습도",
    "co2_ppm":       "CO2 농도",
    "solar_rad":     "일사량",
    "ec_dsm":        "EC",
    "soil_temp":     "지온",
    "vpd":           "증기압포차(VPD)",
}
_UNITS = {
    "temp_internal": "℃",
    "humidity_int":  "%",
    "co2_ppm":       "ppm",
    "solar_rad":     "W/m²",
    "ec_dsm":        "dS/m",
    "soil_temp":     "℃",
    "vpd":           "kPa",
}

# ── 작목별 최적 VPD 범위 (kPa) ────────────────────────────────────────────────
# 출처: 작목별 스마트팜 표준 재배지침 (농촌진흥청)
# 작기 단계: early(정식~활착), mid(생장·개화), late(수확기)
_VPD_OPTIMAL: dict[str, dict[str, tuple[float, float]]] = {
    "딸기":     {"early": (0.4, 0.8), "mid": (0.6, 1.0), "late": (0.5, 0.9)},
    "방울토마토": {"early": (0.6, 1.0), "mid": (0.8, 1.4), "late": (0.8, 1.2)},
    "완숙토마토": {"early": (0.6, 1.0), "mid": (0.8, 1.4), "late": (0.8, 1.2)},
    "참외":     {"early": (0.5, 0.9), "mid": (0.7, 1.2), "late": (0.6, 1.0)},
    "파프리카":  {"early": (0.6, 1.0), "mid": (0.8, 1.2), "late": (0.7, 1.1)},
}

# ── 작목별 작기 단계 월 기준 ─────────────────────────────────────────────────
# {crop: {stage: [months]}}
_SEASON_STAGES: dict[str, dict[str, list[int]]] = {
    "딸기":     {"early": [9, 10],    "mid": [11, 12, 1, 2], "late": [3, 4, 5]},
    "방울토마토": {"early": [2, 3],     "mid": [4, 5, 6, 7],   "late": [8, 9, 10]},
    "완숙토마토": {"early": [2, 3],     "mid": [4, 5, 6, 7],   "late": [8, 9, 10]},
    "참외":     {"early": [3, 4],     "mid": [5, 6],          "late": [7, 8]},
    "파프리카":  {"early": [1, 2],     "mid": [3, 4, 5, 6, 7], "late": [8, 9, 10]},
}

# ── 작기 단계별 이상 감지 민감도 조정 계수 ────────────────────────────────────
# 임계값을 단계별로 좁힘: 개화기(mid)에 가장 엄격
_STAGE_SENSITIVITY: dict[str, float] = {
    "early": 1.2,   # 활착기: 약간 느슨하게
    "mid":   0.85,  # 개화·착과기: 가장 엄격 (수확량 직결)
    "late":  1.1,   # 수확기: 약간 느슨하게
    "unknown": 1.0,
}


@dataclass
class EnvAlert:
    variable:      str
    variable_ko:   str
    current_value: float
    normal_min:    float
    normal_max:    float
    unit:          str
    severity:      str       # "minor" | "major" | "critical"
    message_ko:    str
    season_stage:  str = "unknown"   # "early" | "mid" | "late"


# ── VPD 계산 ─────────────────────────────────────────────────────────────────

def calc_vpd(temp_c: float, humidity_pct: float) -> float:
    """증기압포차(VPD) 계산 (kPa).

    VPD = 포화수증기압 × (1 - 상대습도/100)
    포화수증기압(kPa) = 0.6108 × exp(17.27 × T / (T + 237.3))
    """
    if humidity_pct <= 0 or humidity_pct > 100:
        return float("nan")
    svp = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
    return round(svp * (1.0 - humidity_pct / 100.0), 4)


def get_season_stage(crop_ko: str, month: int) -> str:
    """현재 월 기반 작기 단계 반환."""
    stages = _SEASON_STAGES.get(crop_ko, {})
    for stage, months in stages.items():
        if month in months:
            return stage
    return "unknown"


@lru_cache(maxsize=None)
def _load_stats() -> dict:
    if _ENV_STATS_PATH.exists():
        try:
            return json.loads(_ENV_STATS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[anomaly] env_stats.json 로드 실패: %s", e)
    logger.warning("[anomaly] env_stats.json 없음: %s", _ENV_STATS_PATH)
    return {}


def _check_vpd(
    crop_ko: str,
    temp: float,
    humidity: float,
    stage: str,
) -> Optional[EnvAlert]:
    """VPD 이상 감지. 작기 단계별 최적 범위 기준."""
    vpd = calc_vpd(temp, humidity)
    if math.isnan(vpd):
        return None

    optimal_ranges = _VPD_OPTIMAL.get(crop_ko, _VPD_OPTIMAL.get("방울토마토"))
    vpd_min, vpd_max = optimal_ranges.get(stage, optimal_ranges.get("mid", (0.6, 1.2)))

    if vpd < vpd_min * 0.6 or vpd > vpd_max * 1.5:
        severity = "critical"
        direction = "너무 낮음 (과습·증산 억제)" if vpd < vpd_min else "너무 높음 (과건·수분 스트레스)"
        msg = (f"[CRITICAL] VPD {vpd:.3f}kPa — "
               f"최적 범위({vpd_min:.1f}~{vpd_max:.1f}kPa) {direction}")
    elif vpd < vpd_min or vpd > vpd_max:
        severity = "major"
        direction = "낮음 (습도 과잉·병해 위험)" if vpd < vpd_min else "높음 (증산 과다)"
        msg = (f"[MAJOR] VPD {vpd:.3f}kPa — "
               f"최적 범위({vpd_min:.1f}~{vpd_max:.1f}kPa) {direction}")
    else:
        return None

    return EnvAlert(
        variable="vpd",
        variable_ko="증기압포차(VPD)",
        current_value=vpd,
        normal_min=vpd_min,
        normal_max=vpd_max,
        unit="kPa",
        severity=severity,
        message_ko=msg,
        season_stage=stage,
    )


def detect_anomalies(
    crop_ko: str,
    env_values: dict[str, float],
    month: Optional[int] = None,
) -> list[EnvAlert]:
    """현재 환경값에서 이상치를 감지하여 EnvAlert 리스트 반환.

    Args:
        crop_ko:    작물 한국어명
        env_values: 현재 센서값 dict
        month:      현재 월 (1~12). None이면 작기단계 감지 비활성화.

    env_stats.json 구조:
        {crop: {var: {mean, std, min, max, p5, p95, delta_step, unit}}}

    심각도 기준 (작기단계별 sensitivity 계수 적용):
        critical : val < p5 또는 val > p95
        major    : val < mean-2*std*k 또는 val > mean+2*std*k  (p5~p95 내)
        minor    : val < mean-1*std*k 또는 val > mean+1*std*k  (±2std 내)
        여기서 k = _STAGE_SENSITIVITY[stage]
    """
    import datetime as _dt
    if month is None:
        month = _dt.date.today().month

    stage = get_season_stage(crop_ko, month)
    k     = _STAGE_SENSITIVITY.get(stage, 1.0)

    stats      = _load_stats()
    crop_stats = stats.get(crop_ko, {})
    if not crop_stats:
        logger.debug("[anomaly] 작물 통계 없음: %s", crop_ko)
        crop_stats = {}

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

        stage_note = f" [{stage}기]" if stage != "unknown" else ""

        if val < p5 or val > p95:
            severity  = "critical"
            direction = "너무 낮음" if val < p5 else "너무 높음"
            msg = (f"[CRITICAL] {label} {val}{unit}{stage_note} — "
                   f"정상 범위({p5:.1f}~{p95:.1f}{unit}) {direction}")
            alerts.append(EnvAlert(
                variable=var, variable_ko=label,
                current_value=val, normal_min=p5, normal_max=p95,
                unit=unit, severity=severity, message_ko=msg,
                season_stage=stage,
            ))
        elif val < mean - 2 * std * k or val > mean + 2 * std * k:
            severity  = "major"
            direction = "낮음" if val < mean else "높음"
            msg = (f"[MAJOR] {label} {val}{unit}{stage_note} — "
                   f"평균({mean:.1f}{unit}) 대비 크게 {direction}")
            alerts.append(EnvAlert(
                variable=var, variable_ko=label,
                current_value=val,
                normal_min=round(mean - 2 * std * k, 1),
                normal_max=round(mean + 2 * std * k, 1),
                unit=unit, severity=severity, message_ko=msg,
                season_stage=stage,
            ))
        elif val < mean - std * k or val > mean + std * k:
            severity  = "minor"
            direction = "낮음" if val < mean else "높음"
            msg = (f"[MINOR] {label} {val}{unit}{stage_note} — "
                   f"평균({mean:.1f}{unit}) 대비 {direction}")
            alerts.append(EnvAlert(
                variable=var, variable_ko=label,
                current_value=val,
                normal_min=round(mean - std * k, 1),
                normal_max=round(mean + std * k, 1),
                unit=unit, severity=severity, message_ko=msg,
                season_stage=stage,
            ))

    # ── VPD 이상 감지 (온도 + 습도 동시 존재 시) ──────────────────────────────
    temp = env_values.get("temp_internal")
    humi = env_values.get("humidity_int")
    if temp is not None and humi is not None:
        vpd_alert = _check_vpd(crop_ko, temp, humi, stage)
        if vpd_alert is not None:
            alerts.append(vpd_alert)

    _order = {"critical": 0, "major": 1, "minor": 2}
    alerts.sort(key=lambda a: _order.get(a.severity, 9))
    return alerts
