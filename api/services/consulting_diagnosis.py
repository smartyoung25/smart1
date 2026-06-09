# -*- coding: utf-8 -*-
"""현장컨설팅 종합진단 — 도메인별 진단·의사결정 엔진.

벤치마킹 출처(실문서):
  · RDA/이암허브 '스마트농업 현장컨설팅 체크리스트(2024-08-13)'
    — 경영·운영 / 시설·자동화 / 기기·장비(센서·환기·냉난방·스크린·양액·원수) /
      환경·생육관리 / 데이터 관리·분석 / 유통·마케팅
  · '스마트농업 통합관제 지역대표농가 현장컨설팅 최종결과보고서'
    — 사전진단→총평→농가별 개선방향(처방) 형식
  · 소득333 프로젝트 농가 사례(안성·고양·가평) — 컨설팅 희망분야 분류

설계 원칙:
  - 텔레메트리(장비·이행기록·환경·관수·경영)가 있으면 실측 점수화.
  - 데이터가 없으면 '점검필요(체크리스트)' 항목으로 정직하게 노출(허위 점수 금지).
  - 각 도메인은 점수 + 진단 findings + 원탭 의사결정(decisions)을 생성.

decisions[].target = 딥링크 화면, .record = RecordSheet kind(이행기록 폐루프).
"""
from __future__ import annotations
from typing import Optional

# ── 체크리스트 기반 표준 변수 분류 ──────────────────────────────
SENSOR_VARS = {
    "temp_internal": "내부온도", "humidity_int": "내부습도", "co2_ppm": "CO₂",
    "solar_rad": "일사/PAR", "ec_dsm": "급액EC", "ph": "급액pH",
    "water_content_pct": "배지함수율", "drain_pct": "배액률",
    "temp_external": "외부온도", "wind_speed_ext": "풍속", "rainfall_detect": "감우",
    "soil_temp": "지온",
}
# 핵심(없으면 데이터농업 불가) — 가중
SENSOR_CRITICAL = {"temp_internal", "humidity_int", "ec_dsm", "ph", "drain_pct"}

# 구동기(액추에이터) 하위영역 → 표준 명령/연동 변수 (체크리스트 환기·냉난방·스크린·양액)
ACTUATOR_GROUPS = {
    "환기": {"cmd": "vent_open_pct", "devices": ["천창", "측창", "환기팬", "유동팬"], "target": "g2_env.html"},
    "보온·냉난방": {"cmd": "heating_temp_set", "devices": ["난방기", "튜브레일", "FCU", "히트펌프"], "target": "g2_env.html"},
    "스크린": {"cmd": "screen_pct", "devices": ["보온스크린", "차광스크린", "측면스크린"], "target": "g2_env.html"},
    "양액·관수": {"cmd": "irrigation_run", "devices": ["양액기", "도징펌프", "구역밸브", "원수·필터"], "target": "g3_period.html"},
}


def _status(score: float) -> str:
    return "good" if score >= 75 else "warn" if score >= 45 else "bad"


def _domain(key, name, score, findings, decisions):
    return {"key": key, "name": name, "score": int(round(score)),
            "status": _status(score), "findings": findings, "decisions": decisions}


def build_domains(*, eq, acts, month_acts, meta, trank,
                  irr=None, costs=None, revenue_pm2=None, margin_pct=None) -> list:
    """현장컨설팅 6대 도메인 진단. 모든 입력은 상위(farmer.py)에서 수집해 전달."""
    eq = eq or []; acts = acts or []; month_acts = month_acts or []; meta = meta or {}
    # 장비 데이터포인트 → 매핑된 표준변수 / 카테고리
    mapped = {dp.get("canonical_name") for i in eq for dp in (i.get("datapoints") or []) if dp.get("canonical_name")}
    cats = {}
    for i in eq:
        c = i.get("category") or "기타"; cats[c] = cats.get(c, 0) + 1
    cal_pts = sum(1 for i in eq for dp in (i.get("datapoints") or [])
                  if dp.get("actuator_response_s") or dp.get("cmd_feedback_offset"))
    kinds = {}
    for a in month_acts:
        k = a.get("kind", ""); kinds[k] = kinds.get(k, 0) + 1

    domains = []

    # ① 센서 계측 ──────────────────────────────────────────────
    have = mapped & set(SENSOR_VARS)
    miss = set(SENSOR_VARS) - mapped
    miss_crit = SENSOR_CRITICAL - mapped
    s_sensor = round(len(have) / len(SENSOR_VARS) * 100) if SENSOR_VARS else 0
    if miss_crit: s_sensor = min(s_sensor, 55)  # 핵심 결측 시 상한
    f_sensor = [f"연동 센서 {len(have)}/{len(SENSOR_VARS)}종"]
    if miss: f_sensor.append("미연동: " + ", ".join(SENSOR_VARS[m] for m in sorted(miss))[:80])
    if not eq: f_sensor = ["장비 미등록 — 센서 보유현황 점검필요(체크리스트)"]
    d_sensor = []
    if miss_crit:
        d_sensor.append({"severity": "danger", "title": "핵심 센서 연동 보강",
                         "detail": "데이터농업 필수: " + ", ".join(SENSOR_VARS[m] for m in sorted(miss_crit)),
                         "action": "표준변수 매핑", "target": "c16_equipment.html", "record": "env_setpoint"})
    elif miss:
        d_sensor.append({"severity": "warn", "title": "보조 센서 연동 확대",
                         "detail": "정밀도 향상: " + ", ".join(SENSOR_VARS[m] for m in sorted(miss)),
                         "action": "센서 추가 매핑", "target": "c16_equipment.html", "record": "env_setpoint"})
    domains.append(_domain("sensor", "센서 계측", s_sensor, f_sensor, d_sensor))

    # ② 구동기·제어 (환기·보온·냉난방·스크린·양액) ───────────────
    grp_scores = []; f_act = []; d_act = []
    for gname, g in ACTUATOR_GROUPS.items():
        connected = g["cmd"] in mapped
        # 해당 그룹 장비 등록 여부(디바이스명 부분일치)
        reg = any(any(dv[:2] in (str(i.get("name", "")) + str(i.get("category", ""))) for dv in g["devices"]) for i in eq)
        sc = (60 if connected else 0) + (40 if reg else 0)
        grp_scores.append(sc)
        mark = "🟢" if sc >= 75 else "🟡" if sc >= 40 else "🔴"
        f_act.append(f"{mark} {gname}: {'제어연동' if connected else '수동/미연동'}{' ·등록' if reg else ''}")
        if sc < 45:
            d_act.append({"severity": "warn", "title": f"{gname} 제어 연동",
                          "detail": f"{gname} 자동제어 명령({g['cmd']}) 미연동 — 설정·실반응 점검",
                          "action": f"{gname} 연동·보정", "target": g["target"], "record": "env_setpoint"})
    s_act = round(sum(grp_scores) / len(grp_scores)) if grp_scores else 0
    if cal_pts == 0 and s_act > 0:
        f_act.append("⚠ 물리 캘리브레이션(명령-실반응 편차) 미입력")
        d_act.append({"severity": "info", "title": "액추에이터 물리 캘리브레이션",
                      "detail": "제어명령 대비 실제 반응·응답시간 보정 → 과/부족 제어 손실 절감",
                      "action": "캘리브레이션 입력", "target": "c16_equipment.html", "record": "env_setpoint"})
    if not eq: f_act = ["장비 미등록 — 구동기(환기·냉난방·양액) 보유현황 점검필요"]
    domains.append(_domain("actuator", "구동기·제어", s_act, f_act, d_act))

    # ③ 재배·생육 (관수밸런스·환경적정·생육측정) ─────────────────
    f_cul = []; d_cul = []; cul_parts = []
    dr = None
    try:
        dr = ((irr or {}).get("summary", {}).get("dr_pct_mean", {}) or {}).get("latest")
    except Exception:
        dr = None
    if dr is not None:
        dev = abs(dr - 25)
        sc_dr = max(0, 100 - dev * 5)
        cul_parts.append(sc_dr)
        f_cul.append(f"배액률 {dr:.0f}% (목표 20~30%)" + ("" if 18 <= dr <= 32 else " — 이탈"))
        if not (18 <= dr <= 32):
            d_cul.append({"severity": "warn", "title": "배액률 교정",
                          "detail": f"현재 {dr:.0f}% → 목표 20~30%. {'급액량 증대' if dr<20 else '급액량/횟수 조정'}",
                          "action": "관수 전략 조정", "target": "g3_period.html", "record": "irrigation"})
    else:
        f_cul.append("배액 데이터 없음 — 배지저울·배액 기록 도입 권장")
        d_cul.append({"severity": "info", "title": "기초 생육데이터 기록 습관화",
                      "detail": "배액·EC·무게(델타) 측정으로 영양/생식 균형 진단 기반 확보",
                      "action": "생육측정 기록", "target": "g4_growth.html", "record": "growth"})
    growth_n = kinds.get("growth", 0)
    cul_parts.append(min(100, growth_n * 25))
    f_cul.append(f"이달 생육측정 {growth_n}건")
    if growth_n == 0:
        d_cul.append({"severity": "info", "title": "주차별 생육 진단 도입",
                      "detail": "초장·관부직경·착과수·수확수 정기 측정 → 생육단계별 처방",
                      "action": "생육측정 시작", "target": "g4_growth.html", "record": "growth"})
    s_cul = round(sum(cul_parts) / len(cul_parts)) if cul_parts else 30
    domains.append(_domain("cultivation", "재배·생육", s_cul, f_cul, d_cul))

    # ④ 경영·노동 (운영성숙·작업이행·적기성) ─────────────────────
    work_n = sum(kinds.get(k, 0) for k in ("irrigation", "disease_check", "env_setpoint", "harvest", "todo"))
    s_oper = min(100, trank * 22 + min(40, work_n * 5))
    f_oper = [f"운영 등급 rank {trank}", f"이달 작업이행 {work_n}건"]
    d_oper = []
    if work_n < 5:
        f_oper.append("작업 기록 부족 — 적기성·노동효율 진단 데이터 미흡")
        d_oper.append({"severity": "warn", "title": "작업·노동 기록 정착",
                       "detail": "관수·방제·환경설정·수확 이행을 기록해 노동 배분·적기성 진단 기반 확보",
                       "action": "작업 기록", "target": "c3_home.html", "record": "todo"})
    if trank < 3:
        d_oper.append({"severity": "info", "title": "경영분석 기능(pro) 검토",
                       "detail": "이익률·노무비·ROI 분석 잠금 해제로 경영 의사결정 고도화",
                       "action": "등급 안내", "target": "/smartos", "record": None})
    domains.append(_domain("operation", "경영·노동", s_oper, f_oper, d_oper))

    # ⑤ 유통·판매 (마진·판로·상품화) ─────────────────────────────
    f_sal = []; d_sal = []; sal_parts = []
    if margin_pct is not None:
        sc_m = max(0, min(100, margin_pct * 2.2))  # 마진 45%≈100
        sal_parts.append(sc_m)
        f_sal.append(f"영업이익률 {margin_pct:.0f}%")
        if margin_pct < 25:
            d_sal.append({"severity": "warn", "title": "수익성 개선 — 채널·원가 점검",
                          "detail": "마진 낮음. 공동출하/직거래 비중 확대·에너지원가 절감 검토",
                          "action": "출하 채널 분석", "target": "c12_joint.html", "record": "joint_ship"})
    joint_n = kinds.get("joint_ship", 0)
    sal_parts.append(min(100, 40 + joint_n * 30))
    f_sal.append(f"공동출하 기록 {joint_n}건")
    if joint_n == 0:
        d_sal.append({"severity": "info", "title": "판로 다변화(공동출하)",
                      "detail": "출하 공백기 매출 방어 — 공동출하 풀 참여로 교섭력·물류 효율화",
                      "action": "공동출하 보기", "target": "c12_joint.html", "record": "joint_ship"})
    if not sal_parts: sal_parts = [35]
    s_sal = round(sum(sal_parts) / len(sal_parts))
    domains.append(_domain("sales", "유통·판매", s_sal, f_sal, d_sal))

    # ⑥ 데이터·연동 (축적·재학습·표준화) ─────────────────────────
    s_data = min(100, len(month_acts) * 10 + (len(mapped) * 4))
    f_data = [f"이달 이행기록 {len(month_acts)}건", f"표준변수 매핑 {len(mapped)}종"]
    d_data = []
    if len(month_acts) < 6:
        d_data.append({"severity": "info", "title": "데이터 축적(재학습 임계)",
                       "detail": "기록 누적 시 농장 맞춤모델 재학습 → 추천 정확도 향상",
                       "action": "기록 확대", "target": "c14_report.html", "record": "todo"})
    domains.append(_domain("data", "데이터·연동", s_data, f_data, d_data))

    return domains


def summarize(domains: list) -> dict:
    """도메인 점수 → 종합점수·등급·최우선 처방(ROI 우선순위)."""
    if not domains:
        return {"overall": 0, "grade": "개선필요", "priority": []}
    overall = round(sum(d["score"] for d in domains) / len(domains))
    grade = "우수" if overall >= 75 else "보통" if overall >= 45 else "개선필요"
    # 우선순위: 점수 낮은 도메인의 danger>warn>info 결정부터
    sev_rank = {"danger": 0, "warn": 1, "info": 2}
    prio = []
    for d in sorted(domains, key=lambda x: x["score"]):
        for dec in sorted(d["decisions"], key=lambda x: sev_rank.get(x.get("severity"), 3)):
            prio.append({**dec, "domain": d["name"], "domain_score": d["score"]})
    return {"overall": overall, "grade": grade, "priority": prio[:8]}
