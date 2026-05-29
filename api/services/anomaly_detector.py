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

# ── 관수 지표 메타데이터 (Priva 표준 + 관수통합관리시스템.xlsx 기준) ───────────────
_IRR_LABELS_KO: dict[str, str] = {
    "uptake_efficiency_ml_j": "흡수효율",
    "dr_pct_mean":            "배액률",
    "nl_pct":                 "야간소실률",
    "wc_mean":                "함수율",
}
_IRR_UNITS: dict[str, str] = {
    "uptake_efficiency_ml_j": "ml/J",
    "dr_pct_mean":            "%",
    "nl_pct":                 "%",
    "wc_mean":                "%",
}
# {var: (normal_min, normal_max, critical_min, critical_max)}
# 정상 범위: 운영 목표 구간 / critical 범위: 즉시 대응 필요 경계
_IRR_THRESHOLDS: dict[str, tuple[float, float, float, float]] = {
    "uptake_efficiency_ml_j": (1.0,  2.5,  0.7,  3.0),   # ml/J
    "dr_pct_mean":            (20.0, 40.0, 10.0, 55.0),   # %
    "nl_pct":                 (3.0,  7.0,  1.0,  10.0),   # %
    "wc_mean":                (65.0, 85.0, 55.0, 90.0),   # %
}
_IRR_ADVICE_KO: dict[str, dict[str, str]] = {
    "uptake_efficiency_ml_j": {
        "low":  "흡수효율 저하 — 공급 EC 점검, 근권 온도 확인, 드리퍼 막힘 여부 점검",
        "high": "흡수효율 과다 — 공급량 과다 또는 배액량 부족, 관수 프로그램 재검토",
    },
    "dr_pct_mean": {
        "low":  "배액률 부족 — 공급량 10~20% 증량 또는 관수 횟수 추가 검토",
        "high": "배액률 과다 — 공급량 10~20% 감량 또는 관수 간격 연장 검토",
    },
    "nl_pct": {
        "low":  "야간 소실 부족 — 야간 온도 낮춤 또는 환기 증가로 뿌리압 회복 유도",
        "high": "야간 소실 과다 — 야간 온도 2℃ 낮춤, 습도 상향으로 과증산 억제",
    },
    "wc_mean": {
        "low":  "함수율 저하 — 관수 트리거 임계값 낮춤 또는 1회 공급량 증량",
        "high": "함수율 과다 — 관수 간격 연장, 배액 채널 점검",
    },
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


def reload_stats() -> None:
    """env_stats.json 갱신 후 캐시를 강제 초기화한다."""
    _load_stats.cache_clear()


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


def _check_irrigation_metrics(
    irr_values: dict[str, float],
    stage: str,
) -> list[EnvAlert]:
    """관수 지표(흡수효율·배액률·야간소실률·함수율) 이상 감지.

    env_stats.json과 독립된 고정 Priva 기준 임계값을 사용.
    Args:
        irr_values: 관수 canonical 변수 dict (예: dr_pct_mean=28.5, nl_pct=5.1 …)
        stage:      작기 단계 ("early"|"mid"|"late"|"unknown")
    """
    alerts: list[EnvAlert] = []
    stage_note = f" [{stage}기]" if stage != "unknown" else ""

    for var, val in irr_values.items():
        if var not in _IRR_THRESHOLDS:
            continue
        norm_min, norm_max, crit_min, crit_max = _IRR_THRESHOLDS[var]
        label = _IRR_LABELS_KO[var]
        unit  = _IRR_UNITS[var]
        advice = _IRR_ADVICE_KO.get(var, {})

        if val < crit_min or val > crit_max:
            severity  = "critical"
            direction = "너무 낮음" if val < crit_min else "너무 높음"
            hint      = advice.get("low" if val < crit_min else "high", "")
            msg = (f"[CRITICAL] {label} {val:.2f}{unit}{stage_note} — "
                   f"허용 범위({crit_min}~{crit_max}{unit}) {direction}. {hint}")
        elif val < norm_min or val > norm_max:
            severity  = "major"
            direction = "낮음" if val < norm_min else "높음"
            hint      = advice.get("low" if val < norm_min else "high", "")
            msg = (f"[MAJOR] {label} {val:.2f}{unit}{stage_note} — "
                   f"정상 범위({norm_min}~{norm_max}{unit}) {direction}. {hint}")
        else:
            continue

        alerts.append(EnvAlert(
            variable=var,
            variable_ko=label,
            current_value=round(val, 3),
            normal_min=norm_min,
            normal_max=norm_max,
            unit=unit,
            severity=severity,
            message_ko=msg,
            season_stage=stage,
        ))

    return alerts


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
    # 별칭 정규화: "딸기(설향)" → "딸기" 등
    _CROP_ALIASES = {"딸기(설향)": "딸기"}
    crop_lookup = _CROP_ALIASES.get(crop_ko, crop_ko)
    crop_stats = stats.get(crop_lookup) or stats.get("_all", {})
    if not stats.get(crop_lookup):
        logger.debug("[anomaly] 작물 통계 없음: %s → _all 사용", crop_ko)

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

    # ── 관수 지표 이상 감지 (관수 canonical 변수 존재 시) ──────────────────────
    IRR_VARS = set(_IRR_THRESHOLDS.keys())
    irr_values = {k: v for k, v in env_values.items() if k in IRR_VARS}
    if irr_values:
        irr_alerts = _check_irrigation_metrics(irr_values, stage)
        alerts.extend(irr_alerts)

    _order = {"critical": 0, "major": 1, "minor": 2}
    alerts.sort(key=lambda a: _order.get(a.severity, 9))
    return alerts
