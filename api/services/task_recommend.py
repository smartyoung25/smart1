"""일일·주간 작업추천 — 규칙 기반.

연구개발계획서 과업④ "주간/일일작업추천시스템" 구현.

★ 왜 규칙 기반인가:
  · LLM 없이 동작해야 한다. 외부 LLM 은 비용·크레딧·장애에 묶여 있고(실측: 크레딧
    소진으로 챗봇이 규칙 폴백 중), 작업추천은 매일 떠야 하는 기본 기능이다.
  · 추천 근거가 코드로 설명 가능해야 농가가 신뢰한다("왜 지금 관수?" → 일사 적산).

★ 재료는 이미 있다 — 새로 만들지 않고 조립한다:
    climate_plan.evaluate()       전략표 목표 대비 실측 편차 → 환경 처방
    climate_plan.PERIODS/sun_times 하루 4구간·일출일몰
    api/data/kb/domain_rules.json  P1~P6 관수 Period·PDCA 임계 (data.js 파생, 단일 출처)
    farmer_irrigation             일사 기반 관수 횟수·총량

★ 정직성:
  · 데이터가 없으면 추천을 지어내지 않는다 — 대신 '기록하기' 작업을 낸다.
    (근거 없는 작업 지시는 농가를 잘못된 조치로 이끈다.)
  · 각 작업에 why(근거)를 함께 반환해 화면이 근거를 보여줄 수 있게 한다.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ★ 컨테이너는 UTC 로 돈다(TZ 미설정 — 실측: 호스트 16:08 KST 인데 컨테이너 now() 는 07:08).
#   naive datetime.now() 를 쓰면 Period 판정이 9시간 어긋나 운영에서 조용히 틀린다.
#   로컬 개발기는 KST 라 이 버그가 드러나지 않는다 — 반드시 KST 를 명시할 것.
#   (같은 이유로 main.py 의 KAMIS 스케줄러·kma_service 도 tz 를 명시한다.)
_KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    """농장 기준 현재시각(KST). tz-naive 로 돌려준다 — 이후 계산은 시각 산술만 한다."""
    return datetime.now(tz=_KST).replace(tzinfo=None)

ROOT = Path(__file__).resolve().parents[2]
_RULES_PATH = ROOT / "api" / "data" / "kb" / "domain_rules.json"

# 우선순위 — 화면 정렬·색상에 쓴다
CRIT, WARN, INFO = "crit", "warn", "info"
_ORDER = {CRIT: 0, WARN: 1, INFO: 2}

_rules_cache: dict | None = None


def _rules() -> dict:
    """P1~P6·PDCA 임계 구조체. 없으면 빈 dict — 호출측이 관수 작업을 건너뛴다."""
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache
    try:
        _rules_cache = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        # 조용히 비면 관수 작업이 통째로 사라지므로 눈에 띄게 남긴다.
        logger.error("[task_recommend] 도메인 규칙 없음(%s): %s — "
                     "scripts/build_kb_rules.py --write 로 생성 필요", _RULES_PATH, e)
        _rules_cache = {}
    return _rules_cache


def _task(kind: str, icon: str, title: str, why: str, sev: str = INFO,
          when: str = "", screen: str = "") -> dict:
    """작업 1건. why 는 반드시 채운다 — 근거 없는 지시를 만들지 않기 위함."""
    return {"kind": kind, "icon": icon, "title": title, "why": why,
            "severity": sev, "when": when, "screen": screen}


def _hhmm(h: float) -> str:
    return f"{int(h):02d}:{int(round((h - int(h)) * 60)):02d}"


# ── 관수 (P1~P6) ─────────────────────────────────────────────────────────────

def _current_period(hour: float, sunrise: float, sunset: float) -> Optional[dict]:
    """지금 몇 번 Period 인가.

    ★ 경계는 제품 구현(components/data.js 의 getCurrentPeriod)과 동일하게 유지한다.
      화면과 추천이 서로 다른 Period 를 말하면 농가가 신뢰하지 않는다.
        P6: hour>=19 또는 <5 / P1: <7 / P2: <10 / P3: <12 / P4: <15 / P5: 그 외
    ★ timeRange 문자열을 파싱하면 안 된다 — 숫자 범위인 것은 P1·P4 뿐이고 나머지는
      "일출 후 2~3h"·"15:00~일몰" 같은 서술이라 P2·P3·P5·P6 가 통째로 안 잡힌다
      (실측: 16:08 에 Period=None).
    ★ 트리거 원칙(CLAUDE.md)은 일사 적산 우선·시각 폴백이다. 여기서는 실시간 적산을
      받지 못해 시각으로만 판정하며, 그 사실을 why 에 밝힌다(일사 기반이라 하면 거짓).
    """
    periods = _rules().get("PERIODS") or []
    if len(periods) < 6:
        return None
    by_id = {p.get("id"): p for p in periods}
    if hour >= 19 or hour < 5:
        return by_id.get("P6")
    if hour < 7:
        return by_id.get("P1")
    if hour < 10:
        return by_id.get("P2")
    if hour < 12:
        return by_id.get("P3")
    if hour < 15:
        return by_id.get("P4")
    return by_id.get("P5")


def _irrigation_tasks(farm_id: str, crop: str, hour: float,
                      sunrise: float, sunset: float, env: dict) -> list[dict]:
    p = _current_period(hour, sunrise, sunset)
    if not p:
        return []
    out = []
    tgt = p.get("targets") or {}
    drain = (tgt.get("drainPct") or {})
    label = f"{p['id']} {p.get('name', '')}"

    out.append(_task(
        "irrigation", p.get("icon", "💧"),
        f"{label} — {p.get('radiationTrigger') or '관수 관리'}",
        f"{p.get('timeRange')} 구간 · {p.get('description', '')[:80]}"
        + " (시각 기준 판정 — 일사 적산 연동 시 정밀도 향상)",
        WARN if p["id"] in ("P3", "P4") else INFO,
        when=p.get("timeRange", ""), screen="g3_period.html",
    ))

    # 실측이 있으면 목표 대비 편차로 즉시 조치를 낸다. 없으면 지어내지 않고 기록을 유도.
    dr = env.get("drain_pct")
    if dr is None:
        out.append(_task("record", "📝", "오늘 배액률·EC 기록하기",
                         "배액 실측이 없어 목표 대비 판정을 할 수 없다. 기록하면 다음 추천부터 반영된다.",
                         INFO, screen="g3_period.html"))
    elif drain.get("min") is not None and dr < drain["min"]:
        out.append(_task("irrigation", "⚠️", f"급액량 상향 — 배액률 {dr}% (목표 {drain['min']}~{drain['max']}%)",
                         f"{p['id']} 목표 하한 미달 — 근권 염류 집적·수분 부족 위험", CRIT,
                         screen="g3_period.html"))
    elif drain.get("max") is not None and dr > drain["max"]:
        out.append(_task("irrigation", "⚠️", f"급액량 하향 — 배액률 {dr}% (목표 {drain['min']}~{drain['max']}%)",
                         f"{p['id']} 목표 상한 초과 — 양액·비료 손실", WARN,
                         screen="g3_period.html"))
    return out


# ── 환경 (전략표 편차) ────────────────────────────────────────────────────────

def _env_tasks(farm_id: str, crop: str, env: dict, hour: float,
               sunrise: float, sunset: float) -> list[dict]:
    """climate_plan.evaluate() 처방을 작업으로 변환. 새 판단을 만들지 않는다.

    ★ 키 이름이 다르다: 농장 환경 데이터는 temp_internal·humidity_int·co2_ppm 인데
      evaluate() 는 temp·rh·co2 를 읽는다(measured.get("temp")). 매핑하지 않으면
      편차가 전부 빈 값이 되어 처방이 조용히 0건이 된다 — 실제로 31.5℃ 고온에도
      냉방 처방이 나오지 않았다.
    """
    measured = {}
    for src, dst in (("temp_internal", "temp"), ("humidity_int", "rh"), ("co2_ppm", "co2")):
        if env.get(src) is not None:
            measured[dst] = env[src]
    if not measured:
        return []
    measured["sunrise"], measured["sunset"] = sunrise, sunset
    try:
        from api.services.climate_plan import evaluate
        ev = evaluate(farm_id, crop=crop, measured=measured, hour=int(hour),
                      solar=env.get("solar_rad"))
    except Exception as e:
        logger.warning("[task_recommend] 환경 처방 실패: %s", e)
        return []
    out = []
    # _presc() 는 severity 가 아니라 level 키를 쓴다("danger"|"warn").
    _sev = {"danger": CRIT, "warn": WARN}
    for p in (ev.get("prescriptions") or []):
        out.append(_task("env", p.get("icon", "🌡️"),
                         p.get("action") or p.get("title") or "환경 조치",
                         p.get("reason") or "전략표 목표 대비 편차",
                         _sev.get(p.get("level"), INFO),
                         screen="g2_env.html"))
    return out


# ── 데이터 품질 ──────────────────────────────────────────────────────────────

def _record_tasks(env: dict) -> list[dict]:
    """오늘 비어 있는 실측을 채우도록 유도 — 추천 품질이 곧 입력 품질이다."""
    missing = [ko for key, ko in
               (("temp_internal", "내부온도"), ("humidity_int", "내부습도"),
                ("co2_ppm", "CO₂"), ("ec_feed", "급액 EC"))
               if env.get(key) is None]
    if not missing:
        return []
    return [_task("record", "📝", f"오늘 {'·'.join(missing)} 기록하기",
                  f"{len(missing)}개 항목이 비어 있어 그만큼 추천 근거가 줄어든다.",
                  INFO, screen="g2_env.html")]


# ── 공개 API ─────────────────────────────────────────────────────────────────

def daily_tasks(farm_id: str, crop: str = "딸기", env: dict | None = None,
                now: datetime | None = None,
                sun: tuple[float, float] | None = None) -> dict:
    """오늘의 작업 목록. 심각도 순 정렬."""
    env = env or {}
    now = now or now_kst()
    hour = now.hour + now.minute / 60
    sunrise, sunset = sun or (6.0, 19.0)

    tasks: list[dict] = []
    tasks += _irrigation_tasks(farm_id, crop, hour, sunrise, sunset, env)
    tasks += _env_tasks(farm_id, crop, env, hour, sunrise, sunset)
    tasks += _record_tasks(env)
    tasks.sort(key=lambda t: _ORDER.get(t["severity"], 9))

    return {
        "farm_id": farm_id, "crop": crop, "date": now.date().isoformat(),
        "sunrise": _hhmm(sunrise), "sunset": _hhmm(sunset),
        "period": (_current_period(hour, sunrise, sunset) or {}).get("id"),
        "counts": {s: sum(1 for t in tasks if t["severity"] == s)
                   for s in (CRIT, WARN, INFO)},
        "tasks": tasks,
        # 근거 없는 추천을 하지 않았음을 화면이 알 수 있게 한다
        "has_measurement": bool(env),
    }


def weekly_tasks(farm_id: str, crop: str = "딸기",
                 today: date | None = None) -> dict:
    """이번 주 작업 — 요일별 고정 점검 + 작기 진행.

    ★ 작목별 농작업 캘린더(적엽·유인·수분 등)는 보유 데이터가 아니다.
      지어내면 잘못된 영농 지시가 되므로, 여기서는 제품이 근거를 갖는 항목만 낸다:
      관수 Period 점검·환경 전략표 대비 주간 리뷰·기록 완결성.
      작목별 농작업은 교재 지식베이스 연계로 별도 확장한다(미구현).
    """
    today = today or now_kst().date()   # UTC 로 돌면 자정 전후로 주가 어긋난다
    monday = today - timedelta(days=today.weekday())
    plan = []
    for i in range(7):
        d = monday + timedelta(days=i)
        items = []
        if d.weekday() == 0:
            items.append("주간 목표 확인 — 환경 전략표 대비 지난주 편차 리뷰")
        if d.weekday() in (0, 3):
            items.append("급액·배액 EC/pH 점검 (P1 일출 前 기준값)")
        if d.weekday() == 4:
            items.append("주간 기록 완결성 점검 — 누락 항목 보완")
        if d.weekday() == 6:
            items.append("차주 관수 전략 검토 (일사 예보 기반 급액 조정)")
        plan.append({"date": d.isoformat(), "dow": "월화수목금토일"[d.weekday()],
                     "items": items, "is_today": d == today})
    return {
        "farm_id": farm_id, "crop": crop,
        "week_of": monday.isoformat(), "days": plan,
        "note": "작목별 농작업 캘린더(적엽·유인 등)는 미연동 — 관수·환경·기록 항목만 제공",
    }
