"""PDCA 경영관리 엔진 — 적기적작 효과성·효율성·성장가능성 3대 지수

계산 체계:
  효과성   = (수량 진척률) × (EP 환경 준수율)          0.0~1.0
  효율성   = 예상 수익 / 총비용                         비율 (>1 = 흑자)
  성장가능성 = 추세점수(0~100) × (1 - 위험패널티)      0~100

PDCA 루프:
  일일 → 주간 → 작기 3개 시간 축으로 각각 Plan/Do/Check/Act 요약 반환
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 임계값 기준 (data.js PDCA_THRESHOLDS와 동기화) ────────────────────────────
THRESHOLDS: Dict[str, Dict] = {
    "temp_internal": {"warn": [16, 30], "crit": [12, 35], "unit": "°C", "label": "내부 온도"},
    "vpd":           {"warn": [0.4, 1.5], "crit": [0.2, 2.0], "unit": "kPa", "label": "VPD"},
    "co2_ppm":       {"warn": [400, 1500], "crit": [300, 2000], "unit": "ppm", "label": "CO₂"},
    "ec_feed":       {"warn": [2.0, 4.0], "crit": [1.5, 4.5], "unit": "dS/m", "label": "급액 EC"},
    "drain_pct":     {"warn": [15, 40], "crit": [10, 50], "unit": "%", "label": "배액률"},
    "humidity_int":  {"warn": [60, 90], "crit": [50, 95], "unit": "%", "label": "내부 습도"},
}

# EP 환경 준수 허용 편차
_EP_ALLOW = {"temp": 2.0, "vpd": 0.2, "co2": 150}

# ── 내부 유틸 ──────────────────────────────────────────────────────────────────

def _farm_meta(farm_id: str) -> Dict:
    try:
        from api.data.farm_registry import FARM_REGISTRY
        return FARM_REGISTRY.get(farm_id) or {}
    except Exception:
        return {}


def _days_since(dt_str: Optional[str]) -> int:
    if not dt_str:
        return 0
    try:
        d = date.fromisoformat(dt_str[:10])
        return max(0, (date.today() - d).days)
    except Exception:
        return 0


def _season_length_days(crop: str) -> int:
    """작목별 표준 작기 일수."""
    _MAP = {
        "딸기": 210, "방울토마토": 180, "완숙토마토": 180,
        "파프리카": 270, "오이": 120, "참외": 150,
    }
    for k, v in _MAP.items():
        if k in (crop or ""):
            return v
    return 180


# ── 효과성 계산 ───────────────────────────────────────────────────────────────

def calc_effectiveness(farm_id: str, crop: str, transplant_date: Optional[str]) -> Dict:
    """효과성 = 수량 진척률 × EP 준수율."""
    meta = _farm_meta(farm_id)
    crop = crop or meta.get("crop_ko") or meta.get("crop") or "딸기"
    td = transplant_date or meta.get("transplant_date")
    days_elapsed = _days_since(td)
    season_days = _season_length_days(crop)

    # 수량 진척률
    yield_progress = 0.5  # 기본 폴백
    try:
        from api.services.model_loader import predict_yield_bounds
        from api.data.stats_loader import get_yield_kg_m2
        area = meta.get("area_m2", 1000)
        env_dict = {"temp_internal": 22.0, "humidity_int": 70.0, "solar_rad": 200.0}
        bounds = predict_yield_bounds(crop, env_dict)
        predicted = bounds.get("predicted_yield_kg", 0) or 0
        target_total = get_yield_kg_m2(crop) * area
        # 선형 기대값 대비 진척률
        expected_so_far = target_total * min(days_elapsed / max(season_days, 1), 1.0)
        yield_progress = min(predicted / max(target_total, 1), 1.0) if target_total else 0.5
        # 경과 기간 가중
        if days_elapsed > 0 and season_days > 0:
            progress_ratio = days_elapsed / season_days
            yield_progress = 0.5 + (yield_progress - 0.5) * min(progress_ratio * 2, 1.0)
    except Exception as e:
        logger.debug("효과성 수량 계산 실패: %s", e)

    # EP 준수율 (advisory 이력 기반 추정)
    ep_compliance = _calc_ep_compliance(farm_id)

    score = round(min(yield_progress * ep_compliance, 1.0), 3)
    return {
        "score": score,
        "pct": round(score * 100, 1),
        "yield_progress": round(yield_progress, 3),
        "ep_compliance": round(ep_compliance, 3),
        "days_elapsed": days_elapsed,
        "season_days": season_days,
        "status": _score_status(score),
    }


def _calc_ep_compliance(farm_id: str) -> float:
    """최근 advisory 이력에서 환경 관련 권고 수 기반 준수율 추정."""
    try:
        from api.services import persistence
        advices = persistence.get_advisories(farm_id, limit=50)
        if not advices:
            return 0.75  # 데이터 없으면 중간값
        env_fields = {"temp_internal", "humidity_int", "vpd", "co2_ppm"}
        env_alerts = sum(
            1 for a in advices
            for item in (a.get("advices") or [])
            if (item.get("field") or item.get("metric", "")) in env_fields
        )
        total = max(len(advices), 1)
        alert_rate = env_alerts / (total * 3)  # 권고당 평균 3개 항목 가정
        return max(0.3, min(1.0 - alert_rate * 0.5, 1.0))
    except Exception:
        return 0.75


# ── 효율성 계산 ───────────────────────────────────────────────────────────────

def calc_efficiency(farm_id: str) -> Dict:
    """효율성 = 예상 수익 / 총비용."""
    meta = _farm_meta(farm_id)
    crop = meta.get("crop_ko") or meta.get("crop") or "딸기"

    revenue = 0.0
    total_cost = 1.0
    benchmark_pct = 50.0

    try:
        from api.data.stats_loader import get_price_krw_kg, get_yield_kg_m2
        from api.services.model_loader import predict_revenue_per_m2
        area = meta.get("area_m2", 1000)
        env_dict = {"temp_internal": 22.0, "humidity_int": 70.0, "solar_rad": 200.0}
        rev_m2 = predict_revenue_per_m2(crop, env_dict)
        if rev_m2:
            revenue = rev_m2 * area
        else:
            revenue = get_yield_kg_m2(crop) * get_price_krw_kg(crop) * area
    except Exception as e:
        logger.debug("효율성 수익 계산 실패: %s", e)
        revenue = 5_000_000

    try:
        from api.routers.farmer import _compute_costs
        cb = _compute_costs(farm_id)
        total_cost = max(cb.total_cost_krw or 1, 1)
    except Exception as e:
        logger.debug("효율성 비용 계산 실패: %s", e)
        total_cost = 3_000_000

    ratio = revenue / total_cost
    # 효율성 0~1 정규화: 1.0 = 수익=비용(손익분기), 1.5이상 = 우수
    score = min(ratio / 1.5, 1.0)

    # 벤치마크 백분위 (단순 추정: ratio 1.0 = 50th)
    benchmark_pct = min(round((ratio - 0.5) / 1.5 * 100, 1), 99.0)
    benchmark_pct = max(benchmark_pct, 1.0)

    return {
        "score": round(score, 3),
        "pct": round(score * 100, 1),
        "revenue_krw": round(revenue),
        "total_cost_krw": round(total_cost),
        "revenue_cost_ratio": round(ratio, 3),
        "benchmark_pct": benchmark_pct,
        "status": _score_status(score),
    }


# ── 성장가능성 계산 ───────────────────────────────────────────────────────────

def calc_growth_potential(farm_id: str, crop: str) -> Dict:
    """성장가능성 = 추세점수 × (1 - 위험패널티)."""
    meta = _farm_meta(farm_id)
    crop = crop or meta.get("crop_ko") or meta.get("crop") or "딸기"

    # 드리프트 위험 패널티
    drift_penalty = 0.0
    drift_detail = []
    try:
        from api.services.drift_monitor import compute_drift, summary_badge
        stats = compute_drift(crop)
        badge = summary_badge(stats)
        level = badge.get("level", "green")
        drift_penalty = {"green": 0.0, "yellow": 0.15, "red": 0.30}.get(level, 0.0)
        drift_detail.append({"crop": crop, "level": level, "mape": stats.mape})
    except Exception as e:
        logger.debug("드리프트 조회 실패: %s", e)

    # 추세 점수 (advisory 이력 기반: 최근 5건 vs 이전 5건 비교)
    trend_score = _calc_trend_score(farm_id)

    raw = trend_score * (1.0 - drift_penalty)
    score = round(min(max(raw, 0.0), 1.0), 3)

    return {
        "score": score,
        "pct": round(score * 100, 1),
        "trend_score": round(trend_score, 3),
        "drift_penalty": round(drift_penalty, 3),
        "drift_detail": drift_detail,
        "status": _score_status(score),
    }


def _calc_trend_score(farm_id: str) -> float:
    """최근 advisory 이력 추세 분석 → 0.0~1.0."""
    try:
        from api.services import persistence
        advices = persistence.get_advisories(farm_id, limit=20)
        if len(advices) < 4:
            return 0.65
        # 심각도 레이블이 있으면 활용
        def _severity(a):
            items = a.get("advices") or []
            crit = sum(1 for i in items if i.get("severity") in ("critical", "danger"))
            return crit
        recent = [_severity(a) for a in advices[:10]]
        older  = [_severity(a) for a in advices[10:20]]
        avg_r = sum(recent) / max(len(recent), 1)
        avg_o = sum(older)  / max(len(older), 1)
        # 경보가 줄었으면 추세 상승
        if avg_o == 0:
            return 0.7
        delta = (avg_o - avg_r) / max(avg_o, 1)  # 양수 = 개선
        return round(min(max(0.5 + delta * 0.5, 0.0), 1.0), 3)
    except Exception:
        return 0.65


# ── 임계값 경보 ───────────────────────────────────────────────────────────────

def get_threshold_alerts(farm_id: str, env: Optional[Dict] = None) -> List[Dict]:
    """현재 환경값과 임계값 비교 → 경보 항목 목록."""
    if env is None:
        env = _latest_env(farm_id)

    alerts = []
    for field, cfg in THRESHOLDS.items():
        val = env.get(field)
        if val is None:
            continue
        lo_c, hi_c = cfg["crit"]
        lo_w, hi_w = cfg["warn"]
        if val < lo_c or val > hi_c:
            severity = "danger"
        elif val < lo_w or val > hi_w:
            severity = "warn"
        else:
            continue

        normal_lo, normal_hi = lo_w, hi_w
        if val < normal_lo:
            diff = normal_lo - val
            direction = "낮음"
        else:
            diff = val - normal_hi
            direction = "높음"

        alerts.append({
            "field": field,
            "label": cfg["label"],
            "value": round(val, 2),
            "unit": cfg["unit"],
            "severity": severity,
            "direction": direction,
            "diff": round(diff, 2),
            "normal_range": [lo_w, hi_w],
            "action": _alert_action(field, direction),
        })

    alerts.sort(key=lambda a: 0 if a["severity"] == "danger" else 1)
    return alerts


def _latest_env(farm_id: str) -> Dict:
    try:
        from api.routers.farmer import _load_environment_data
        data = _load_environment_data(farm_id)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _alert_action(field: str, direction: str) -> str:
    _MAP = {
        "temp_internal": {"낮음": "난방 출력 증가 또는 보온 점검", "높음": "환기창 개방 또는 차광 적용"},
        "vpd":           {"낮음": "환기 개방 또는 온도 상승", "높음": "분무·관수 또는 온도 강하"},
        "co2_ppm":       {"낮음": "CO₂ 공급 시작 또는 증량", "높음": "환기 개방으로 자연 배기"},
        "ec_feed":       {"낮음": "양액 농도 상향 조정", "높음": "희석 공급 또는 EC 낮춤"},
        "drain_pct":     {"낮음": "급액 횟수 또는 급액량 증가", "높음": "급액 간격 연장"},
        "humidity_int":  {"낮음": "분무 또는 가습기 가동", "높음": "환기 개방 또는 난방 증가"},
    }
    return _MAP.get(field, {}).get(direction, "관리자 점검 필요")


# ── PDCA 일일/주간/작기 요약 ──────────────────────────────────────────────────

def pdca_daily(farm_id: str) -> Dict:
    """오늘의 PDCA 4단계 요약."""
    meta = _farm_meta(farm_id)
    crop = meta.get("crop_ko") or meta.get("crop") or "딸기"
    td = meta.get("transplant_date")

    # Plan: 오늘 EP 목표
    plan_summary = _today_plan(farm_id, crop)
    # Do: 실측 환경 현황
    env = _latest_env(farm_id)
    do_summary = _today_do(env)
    # Check: 임계값 경보
    alerts = get_threshold_alerts(farm_id, env)
    check_summary = {
        "alert_count": len(alerts),
        "danger_count": sum(1 for a in alerts if a["severity"] == "danger"),
        "warn_count": sum(1 for a in alerts if a["severity"] == "warn"),
        "alerts": alerts[:5],
    }
    # Act: 다음 EP 준비 제안
    act_summary = _today_act(farm_id, crop, alerts)

    return {
        "date": date.today().isoformat(),
        "plan": plan_summary,
        "do": do_summary,
        "check": check_summary,
        "act": act_summary,
    }


def _today_plan(farm_id: str, crop: str) -> Dict:
    try:
        from api.services.climate_plan import active_setpoint, current_env_period
        from datetime import datetime as dt
        hour = dt.now().hour
        sp = active_setpoint(farm_id, crop, hour)
        t = sp.get("target") or {}
        ep = sp.get("ep_name", "—")
        return {
            "ep": sp.get("ep_id", "—"),
            "ep_name": ep,
            "target_temp": t.get("temp_adj") or t.get("temp"),
            "target_rh": t.get("rh"),
            "target_co2": t.get("co2"),
            "target_vpd": t.get("vpd"),
            "stage": sp.get("stage_label", "—"),
        }
    except Exception:
        return {"ep": "—", "ep_name": "—"}


def _today_do(env: Dict) -> Dict:
    return {
        "temp": env.get("temp_internal"),
        "rh": env.get("humidity_int"),
        "co2": env.get("co2_ppm"),
        "vpd": env.get("vpd"),
        "solar_rad": env.get("solar_rad"),
        "has_data": bool(env),
    }


def _today_act(farm_id: str, crop: str, alerts: List[Dict]) -> Dict:
    suggestions = []
    if any(a["field"] == "vpd" for a in alerts):
        suggestions.append("VPD 이탈 — 환기·가습 즉시 조정 후 EP 준수율 확인")
    if any(a["field"] == "co2_ppm" for a in alerts):
        suggestions.append("CO₂ 이탈 — 공급량 재설정 (EP3 오전 목표 800~1200 ppm)")
    if any(a["field"] == "temp_internal" for a in alerts):
        suggestions.append("온도 이탈 — 광연동 승온 파라미터 또는 야간 최저온 점검")
    if not suggestions:
        suggestions.append("현재 환경 양호 — 전략표 목표 유지")
    suggestions.append("내일 EP2 새벽 환기 개방 시각 사전 확인")
    return {"suggestions": suggestions[:3]}


def pdca_weekly(farm_id: str, week_offset: int = 0) -> Dict:
    """주간 PDCA 체크포인트 (week_offset=0 = 이번 주)."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) - timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)

    meta = _farm_meta(farm_id)
    crop = meta.get("crop_ko") or meta.get("crop") or "딸기"
    td = meta.get("transplant_date")
    days_elapsed = _days_since(td)
    week_num = max(1, days_elapsed // 7)

    eff = calc_effectiveness(farm_id, crop, td)
    effi = calc_efficiency(farm_id)
    gp = calc_growth_potential(farm_id, crop)

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "week_num": week_num,
        "week_offset": week_offset,
        "plan": {
            "summary": f"작기 {week_num}주차 — EP 전략표 준수·수량 목표 달성",
            "ep_focus": "EP3·EP4 광합성 최대화, VPD 1.0~1.4 kPa 유지",
        },
        "do": {
            "ep_compliance_pct": round(eff["ep_compliance"] * 100, 1),
            "days_monitored": min(7, days_elapsed),
        },
        "check": {
            "effectiveness": eff,
            "efficiency": effi,
            "growth_potential": gp,
            "overall_score": round((eff["score"] + effi["score"] + gp["score"] / 100) / 3, 3),
        },
        "act": _weekly_act(eff, effi, gp),
    }


def _weekly_act(eff: Dict, effi: Dict, gp: Dict) -> Dict:
    actions = []
    if eff["score"] < 0.6:
        actions.append("효과성 부족 — EP 준수율 점검, 전략표 온도·VPD 목표 재검토")
    if effi["score"] < 0.5:
        actions.append("효율성 저하 — 에너지·노동 비용 항목 점검, 최적 작업 시간대 재배치")
    if gp["score"] < 50:
        actions.append("성장가능성 하락 — 드리프트 경보 작목 재학습 또는 폴백 모델 확인")
    if not actions:
        actions.append("전체 지수 양호 — 다음 주 EP5·EP6 건조 dry-back 목표 강화")
    return {"next_week_actions": actions}


def pdca_season(farm_id: str) -> Dict:
    """작기 전체 PDCA 누계 요약."""
    meta = _farm_meta(farm_id)
    crop = meta.get("crop_ko") or meta.get("crop") or "딸기"
    td = meta.get("transplant_date")
    days = _days_since(td)
    season = _season_length_days(crop)
    weeks_done = days // 7
    weeks_total = season // 7

    eff = calc_effectiveness(farm_id, crop, td)
    effi = calc_efficiency(farm_id)
    gp = calc_growth_potential(farm_id, crop)

    return {
        "crop": crop,
        "transplant_date": td,
        "days_elapsed": days,
        "season_days": season,
        "weeks_done": weeks_done,
        "weeks_total": weeks_total,
        "progress_pct": round(min(days / max(season, 1), 1.0) * 100, 1),
        "effectiveness": eff,
        "efficiency": effi,
        "growth_potential": gp,
        "overall_grade": _overall_grade(eff["score"], effi["score"], gp["score"] / 100),
    }


def _overall_grade(eff: float, effi: float, gp: float) -> str:
    avg = (eff + effi + gp) / 3
    if avg >= 0.8:  return "A (우수)"
    if avg >= 0.65: return "B (양호)"
    if avg >= 0.5:  return "C (보통)"
    return "D (개선 필요)"


def _score_status(score: float) -> str:
    if score >= 0.7: return "ok"
    if score >= 0.5: return "warn"
    return "danger"
