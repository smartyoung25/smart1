# -*- coding: utf-8 -*-
"""역량 단계별 핵심 서비스 큐레이션 — Capability-based Service Routing.

목적: 농가가 35+ 화면 전부를 헤매지 않도록, **진단된 역량 단계에 맞는 핵심 서비스
3~5개만** 선별해 제시한다. 단계가 오르면 다음 핵심 서비스가 열린다.

벤치마킹(실문서): 스마트농업 현장컨설팅 결과보고서 — 컨설턴트 총평이 농가를
"기반 구축(저울 설치·기준값) → 데이터 측정·관수 밸런스 → 정밀 제어(생육 균형)"
단계로 구분하고 "고도화 기술 전수보다 기본부터"라고 권고한 것을 단계 모델로 정립.

입력: C17 종합진단 결과(overall·tier·6대 도메인 점수).
출력: 역량 단계 + 단계별 핵심 서비스(딥링크) + 다음 단계 진입 핵심 과제.
"""
from __future__ import annotations

# 서비스 카탈로그 — 화면별 역량 태그(이 단계 농가에게 핵심인가)
# stage: 1 기반구축 / 2 데이터정착 / 3 정밀제어 / 4 경영고도화
SERVICE_CATALOG = {
    1: {  # 기반구축기 — "측정 기반부터"
        "name": "기반 구축기",
        "slogan": "측정 기반부터 — 장비 연결과 기본 데이터 확보",
        "focus": "센서·장비를 연결하고 매일 데이터가 쌓이게 만드는 단계입니다. 고급 기능보다 기본부터.",
        "services": [
            {"title": "시설 기자재 등록·연동", "target": "c16_equipment.html", "why": "센서 표준변수 매핑 — 모든 데이터의 출발점"},
            {"title": "시스템 종합진단", "target": "c17_diagnosis.html", "why": "현재 역량·취약점 파악"},
            {"title": "환경 모니터링", "target": "g2_env.html", "why": "온습도·CO₂ 기본 확인 습관화"},
            {"title": "현장 문진 체크리스트", "target": "c18_checklist.html", "why": "센서 외 항목(원수·필터) 현장 점검"},
        ],
    },
    2: {  # 데이터정착기 — "측정→기록→밸런스"
        "name": "데이터 정착기",
        "slogan": "관수 밸런스와 생육 기록 — 데이터로 농사 짓기",
        "focus": "배액·EC·생육을 기록하고 관수 밸런스를 잡는 단계입니다. 폐루프 기록을 정착시키세요.",
        "services": [
            {"title": "관수·양액 Period 관리", "target": "g3_period.html", "why": "P1~P6 배액률 20~30% 밸런스"},
            {"title": "생육 측정 기록", "target": "g4_growth.html", "why": "초장·착과수 주차별 기록"},
            {"title": "월간 경영성과 리포트", "target": "c14_report.html", "why": "성과지표·학습 기여 확인"},
            {"title": "AI 진단·개선 추천", "target": "c4_diagnosis.html", "why": "이상 감지·1차 추천 수용"},
        ],
    },
    3: {  # 정밀제어기 — "정밀 제어·예측"
        "name": "정밀 제어기",
        "slogan": "정밀 관수·환경 제어와 수확 예측",
        "focus": "데이터 기반 정밀 제어와 예측으로 생식/영양 균형을 조절하는 단계입니다.",
        "services": [
            {"title": "오늘의 의사결정(DecisionDeck)", "target": "c3_home.html", "why": "이상감지+AI추천 원탭 실행"},
            {"title": "수확량 예측", "target": "g6_harvest.html", "why": "신뢰구간 기반 출하 계획"},
            {"title": "병해·IPM 조기경보", "target": "g5_disease.html", "why": "결로·병해 선제 대응"},
            {"title": "16일 장기예보·재해 대비", "target": "f3_weather.html", "why": "ET₀·재해 선행 의사결정"},
        ],
    },
    4: {  # 경영고도화기 — "수익·판로·환원"
        "name": "경영 고도화기",
        "slogan": "수익 최적화·판로 다변화·데이터 환원",
        "focus": "경영 성과를 극대화하고 데이터를 자산화하는 단계입니다. 공동출하·벤치마킹·보상 활용.",
        "services": [
            {"title": "공동출하 운영", "target": "c12_joint.html", "why": "교섭력·물류 효율로 수익 방어"},
            {"title": "우수농가 벤치마킹", "target": "c9_benchmark.html", "why": "상위농가 대비 격차 개선"},
            {"title": "수익성·ERP 분석", "target": "c5_erp.html", "why": "이익률·원가 정밀 관리"},
            {"title": "데이터 환원·보상", "target": "c7_reward.html", "why": "학습 기여 → 보상 자산화"},
            {"title": "클러스터 작황 모니터링", "target": "f8_cluster.html", "why": "다수필지·광역 무센서 작황·이상알림"},
        ],
    },
}


def _stage_of(overall, scores, trank):
    """역량 단계 판정 — 종합점수 + 기반(센서·데이터) 충족 여부 + 등급 보정."""
    sensor = scores.get("sensor", 0)
    data = scores.get("data", 0)
    # 기반(센서/데이터) 미충족이면 점수가 높아도 1단계로 묶어 기본부터
    if overall < 45 or sensor < 40 or data < 40:
        return 1
    if overall < 65:
        return 2
    if overall < 80:
        return 3
    return 4


def build_capability(diag: dict) -> dict:
    """C17 진단 결과 → 역량 단계 + 핵심 서비스 + 다음 단계 과제."""
    overall = diag.get("overall_score", 0)
    trank = 1
    tier = diag.get("tier", "basic")
    _rank = {"basic": 1, "smart": 2, "pro": 3, "enterprise": 4}
    trank = _rank.get(tier, 1)
    scores = {d["key"]: d["score"] for d in diag.get("domains", [])}
    stage = _stage_of(overall, scores, trank)
    cat = SERVICE_CATALOG[stage]

    # 다음 단계 진입 핵심 과제 = 진단 우선처방 상위 2건(취약 영역)
    next_tasks = []
    for p in (diag.get("priority_decisions") or [])[:2]:
        next_tasks.append({"title": p.get("title"), "detail": p.get("detail"),
                           "domain": p.get("domain"), "target": p.get("target")})

    # 진행도: 현 단계 내 위치(다음 단계까지 점수 갭)
    thresholds = {1: 45, 2: 65, 3: 80, 4: 100}
    nxt = thresholds[stage]
    prev = {1: 0, 2: 45, 3: 65, 4: 80}[stage]
    progress = round((overall - prev) / max(nxt - prev, 1) * 100) if stage < 4 else 100
    progress = max(0, min(100, progress))

    return {
        "stage": stage, "stage_name": cat["name"], "slogan": cat["slogan"], "focus": cat["focus"],
        "overall": overall, "tier": tier,
        "core_services": cat["services"],
        "next_tasks": next_tasks,
        "progress_pct": progress,
        "next_stage": (SERVICE_CATALOG.get(stage + 1, {}) or {}).get("name") if stage < 4 else None,
        "note": "진단 역량 단계에 맞춘 핵심 서비스입니다. 다음 단계 과제를 해결하면 새 서비스가 열립니다.",
    }
