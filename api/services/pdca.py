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


# ── 컨설턴트 개입 트리거 ──────────────────────────────────────────────────────

# 작목별 착과기 진입 주차 (정식 기준)
_FRUIT_SET_WEEK: Dict[str, int] = {
    "딸기": 5, "방울토마토": 6, "완숙토마토": 6,
    "파프리카": 7, "참외": 5, "오이": 4,
}

# 착과기 체크리스트 (작목별)
FRUIT_SET_CHECKLIST: Dict[str, List[str]] = {
    "딸기": [
        "EC 2.8 → 3.2 dS/m 상향 (착과 촉진)",
        "야간온도 12 → 10°C 하향 (화아 자극)",
        "관수량 10% 감량 (근권 건조 유도)",
        "통풍 강화 — 내부 습도 85% 미만 유지",
        "적엽 — 하위 노화 잎 2~3매 제거",
    ],
    "방울토마토": [
        "EC 3.0 → 3.5 dS/m 상향",
        "전동 진동기 또는 인공 수분 보조",
        "VPD 0.8 → 1.0 kPa 상향",
        "관수 횟수 1~2회 감량",
        "CO₂ 800~1,000 ppm 유지",
    ],
    "완숙토마토": [
        "EC 3.0 → 3.5 dS/m",
        "VPD 1.0 kPa 목표",
        "착과 호르몬 처리 검토 (저일조 시)",
        "1회 급액량 증가·빈도 감량",
        "1화방 착과 확인 후 유인 조정",
    ],
    "참외": [
        "주간온도 28 → 30°C 상향",
        "야간온도 16 → 18°C 유지",
        "EC 2.5 → 3.0 dS/m",
        "수분 곤충 방사 타이밍 확인",
        "자방 비대 관찰 — 착과절 표시",
    ],
    "파프리카": [
        "EC 3.0 → 3.5 dS/m",
        "야간 18°C 유지 (저온 착과 불량 방지)",
        "착과 부위 주변 적심 검토",
        "관수 일몰 전 종료 (야간 습도 억제)",
        "꽃 수정 상태 매일 점검",
    ],
    "오이": [
        "EC 2.5 → 3.0 dS/m",
        "주간 VPD 1.0~1.2 kPa",
        "적엽 — 착과절 아래 잎 제거",
        "관수 빈도 유지, 1회량 조절",
    ],
}


def _phenology_stage(crop: str, weeks_done: int) -> Dict:
    """착과기·비대기·수확기 등 생육 시기 단계 반환."""
    fw = _FRUIT_SET_WEEK.get(crop, 6)
    days_until_fruit = (fw - weeks_done) * 7

    if 0 <= days_until_fruit <= 3:
        stage = "pre_fruit_set"
        label = f"착과기 진입 D-{days_until_fruit}"
        urgent = True
    elif -7 <= days_until_fruit < 0:
        stage = "fruit_set"
        label = "착과기 진행 중"
        urgent = False
    elif weeks_done < fw - 1:
        stage = "vegetative"
        label = "영양생장기"
        urgent = False
    else:
        stage = "ripening"
        label = "과실 비대·수확기"
        urgent = False

    return {
        "stage": stage,
        "label": label,
        "weeks_done": weeks_done,
        "fruit_set_week": fw,
        "days_until_fruit_set": days_until_fruit,
        "urgent": urgent,
        "checklist": FRUIT_SET_CHECKLIST.get(crop, []) if stage in ("pre_fruit_set",) else [],
    }


def _drift_summary_all() -> Dict:
    """전체 5작목 드리프트 현황 집계."""
    crops_all = ["딸기", "방울토마토", "완숙토마토", "참외", "파프리카"]
    red, yellow, green = [], [], []
    try:
        from api.services.drift_monitor import compute_drift, summary_badge
        for c in crops_all:
            try:
                stats = compute_drift(c)
                badge = summary_badge(stats)
                level = badge.get("level", "green")
                if level == "red":    red.append(c)
                elif level == "yellow": yellow.append(c)
                else:                   green.append(c)
            except Exception:
                green.append(c)
    except Exception:
        pass
    return {
        "red_count": len(red),
        "yellow_count": len(yellow),
        "red_crops": red,
        "yellow_crops": yellow,
        "needs_correction": len(red) >= 2,
    }


def consult_triggers(farm_id: str) -> Dict:
    """컨설턴트 개입 트리거 목록 반환."""
    meta = _farm_meta(farm_id)
    crop = meta.get("crop_ko") or meta.get("crop") or "딸기"
    td = meta.get("transplant_date")
    days = _days_since(td)
    weeks_done = days // 7

    eff = calc_effectiveness(farm_id, crop, td)
    phenology = _phenology_stage(crop, weeks_done)
    drift = _drift_summary_all()

    triggers = []

    # 트리거 1: 효과성 위험 (< 40%)
    if eff["score"] < 0.4:
        triggers.append({
            "id": "effectiveness_danger",
            "severity": "danger",
            "icon": "📉",
            "title": f"효과성 위험 — {eff['pct']}%",
            "desc": "수량 진척 × EP 준수율이 40% 미만입니다. 즉각 점검이 필요합니다.",
            "action": "전문가 원격 점검 요청",
        })
    elif eff["score"] < 0.6:
        triggers.append({
            "id": "effectiveness_warn",
            "severity": "warn",
            "icon": "⚠️",
            "title": f"효과성 주의 — {eff['pct']}%",
            "desc": "효과성이 60% 미만입니다. 2주 연속 하강 시 전문가 점검을 권고합니다.",
            "action": "추세 모니터링 강화",
        })

    # 트리거 2: 착과기 D-3 이내
    if phenology["urgent"]:
        triggers.append({
            "id": "pre_fruit_set",
            "severity": "phenology",
            "icon": "🌸",
            "title": phenology["label"],
            "desc": f"{crop} 착과기 진입 직전입니다. EC·관수·온도 체크리스트를 즉시 확인하세요.",
            "action": "착과기 체크리스트 확인",
            "checklist": phenology["checklist"],
        })

    # 트리거 3: 드리프트 🔴 2작목 이상
    if drift["needs_correction"]:
        triggers.append({
            "id": "drift_correction",
            "severity": "warn",
            "icon": "🔬",
            "title": f"예측 정확도 저하 ({drift['red_count']}개 작목 🔴)",
            "desc": f"드리프트 감지: {', '.join(drift['red_crops'])} — 농장 보정값 수동 조정이 필요합니다.",
            "action": "보정값 조정",
        })

    return {
        "triggers": triggers,
        "trigger_count": len(triggers),
        "has_danger": any(t["severity"] == "danger" for t in triggers),
        "has_phenology": any(t["severity"] == "phenology" for t in triggers),
        "drift": drift,
        "phenology": phenology,
        "effectiveness_pct": eff["pct"],
    }
