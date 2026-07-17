"""제품 보유 도메인 규칙 → 지식베이스 청크 (교재 청크와 동일 스키마).

왜 필요한가(실측 근거):
  교재(449쪽)는 병해충·환경엔 강하지만 이 제품의 핵심 관수 지식이 전혀 없다 —
  배액률 0회 · 슬랩 0회 · dry-back 0회 · 일사적산 0회 · P1~P6 0회 · DLI 0회.
  즉 P1~P6 일사적산 관수·G3 센서범위·KPI 는 교재로 대체 불가한 차별 자산이다.

단일 출처 원칙:
  손으로 옮겨 적지 않는다. 규칙이 사는 코드에서 추출한다 —
    · components/data.js      → scripts/dump_domain_rules.js 가 JSON 덤프(P1~P6·트리거·PDCA)
    · api/services/climate_plan.py → 직접 import(PERIODS·_RECOMMEND·_LIGHT_BOOST·vpd)
  코드가 바뀌면 재생성만으로 지식베이스가 따라온다(수기 사본이면 조용히 어긋난다).

사용:
  node scripts/dump_domain_rules.js > out/kb_rules_raw.json   # 선행
  python scripts/build_kb_rules.py            # 미리보기
  python scripts/build_kb_rules.py --write    # out/kb_rules_chunks.json 저장
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RAW = ROOT / "out" / "kb_rules_raw.json"
OUT = ROOT / "out" / "kb_rules_chunks.json"
# ★ 서빙본은 api/data/kb/ 다 — out/ 은 .gitignore 대상이라 배포 서버에 안 올라간다.
#   여기 함께 쓰지 않으면 재생성해도 챗봇이 보는 지식베이스는 그대로다(조용히 어긋남).
KB_SERVE = ROOT / "api" / "data" / "kb"
# 검색용 청크(텍스트)와 별개로, 프로그램이 목표값을 직접 읽는 구조체
STRUCT = KB_SERVE / "domain_rules.json"


SRC_LABEL = "KAASA Farmingsight 제품 도메인 규칙"
COPYRIGHT = "㈜이암허브·한국스마트농업AI협회"


def _rng(d: dict | None, unit: str = "") -> str:
    if not d:
        return "—"
    lo, hi = d.get("min"), d.get("max")
    if lo is None and hi is None:
        return "—"
    if lo == hi:
        return f"{lo}{unit}"
    return f"{lo}~{hi}{unit}"


def chunks_from_periods(raw: dict) -> list[dict]:
    """P1~P6 관수 Period — 각 Period 를 독립 검색 단위로."""
    out = []
    starts = (raw.get("IRRIGATION_START") or {}).get("byPeriod", {})
    for p in raw["PERIODS"]:
        t = p.get("targets") or {}
        lines = [
            f"시간대: {p.get('timeRange','—')}",
            f"일사 적산 트리거: {p.get('radiationTrigger','—')}",
            f"설명: {p.get('description','—')}",
            "",
            "[목표값]",
            f"  배액률: {_rng(t.get('drainPct'), '%')}",
            f"  배액 EC: {_rng(t.get('ecDrain'), ' dS/m')}",
            f"  dry-back: {_rng(t.get('drybackPct'), '%')}",
            # supply 는 0(무관수) 또는 None(해당 없음) 이 의미를 가지므로 그대로 노출하지 않는다
            f"  급액: {('무관수' if t.get('supply') == 0 else (t.get('supply') if t.get('supply') is not None else '—'))}",
            "",
            f"[스티어링] {p.get('steering','—')}",
        ]
        sc = starts.get(p["id"]) or []
        if sc:
            lines += ["", "[관수 시작 조건]"] + [f"  · {s}" for s in sc]
        ar = p.get("alertRules") or []
        if ar:
            lines += ["", "[경보 규칙]"]
            for a in ar:
                bounds = " ".join(f"{k}={a[k]}" for k in ("min", "max") if a.get(k) is not None)
                lines.append(f"  · {a.get('metric')} {bounds} [{a.get('severity')}] {a.get('msg','')}")
        out.append({
            "title": f"{p['id']} {p.get('name','')} — 관수 Period",
            "text": "\n".join(lines),
            "path": "관수 관리 > P1~P6 일사적산 Period",
            "tags": ["관수", "일사적산", "배액률", "dry-back", "EC", p["id"]],
        })
    return out


def chunk_start_priority(raw: dict) -> dict:
    pr = (raw.get("IRRIGATION_START") or {}).get("priority", [])
    lines = ["관수 시작 조건은 아래 우선순위로 판정한다(일사 적산 우선, 시각은 폴백).", ""]
    for i, x in enumerate(pr, 1):
        lines.append(f"{i}. {x.get('name_ko')} — {x.get('desc')}")
    return {
        "title": "관수 시작 조건 우선순위 (일사 적산 우선)",
        "text": "\n".join(lines),
        "path": "관수 관리 > 시작 조건",
        "tags": ["관수", "일사적산", "증산", "함수율", "트리거"],
    }


def chunk_pdca(raw: dict) -> dict:
    th = raw.get("PDCA_THRESHOLDS") or {}
    lines = ["실측값이 아래 범위를 벗어나면 주의(warn)·위험(crit)으로 판정한다.", "",
             f"{'지표':<14}{'단위':<8}{'주의(warn)':<18}{'위험(crit)'}"]
    for k, v in th.items():
        lines.append(f"{v.get('label', k):<14}{v.get('unit', '—'):<8}"
                     f"{str(v.get('warn')):<18}{v.get('crit')}")
    return {
        "title": "환경·관수 임계값 (PDCA 경보 기준)",
        "text": "\n".join(lines),
        "path": "모니터링 > 임계값",
        "tags": ["임계값", "경보", "VPD", "EC", "배액률", "CO2", "온도"],
    }


def chunks_from_climate() -> list[dict]:
    from api.services.climate_plan import (PERIODS, ENV_PERIODS, _LIGHT_BOOST,
                                           _RECOMMEND, _BENCH_METHOD, vpd)
    out = []
    # 하루 4구간
    lines = ["환경관리 전략표는 '생육시기 × 하루 4구간' 2축으로 목표(온도·습도·CO₂)를 정의한다.", ""]
    for p in PERIODS:
        lines.append(f"· {p['label']}({p['key']}) {p['from']}~{p['to']}시 — {p['desc']}")
    lines += ["", f"벤치마크: {_BENCH_METHOD}",
              "", "[광연동 승온(Priva lichtverhoging)]",
              f"  기준 일사 {_LIGHT_BOOST['ref_wm2']} W/m² 초과분 100W/m² 당 "
              f"+{_LIGHT_BOOST['slope_per_100wm2']}℃, 상한 +{_LIGHT_BOOST['cap_c']}℃"]
    out.append({
        "title": "환경관리 전략표 — 하루 4구간과 광연동 승온",
        "text": "\n".join(lines),
        "path": "환경 관리 > 전략표",
        "tags": ["환경관리", "전략표", "광연동", "승온", "구간"],
    })

    # 작목별 권장 밴드
    for crop, v in _RECOMMEND.items():
        if crop == "_default":
            continue
        lines = [f"{crop}의 생육단계별 24시간 평균기온(avg24)·VPD 권장 밴드.", ""]
        for st, ko in (("establish", "활착기"), ("veg", "생장기"),
                       ("flower", "착과·개화기"), ("harvest", "수확기")):
            a, d = v["avg24"].get(st), v["vpd"].get(st)
            if a or d:
                lines.append(f"· {ko}({st}): avg24 {a}℃ · VPD {d} kPa")
        note = ("겨울 시설 촉성 기준 — 야간 저온으로 화아분화를 유도한다."
                if crop == "딸기" else
                "출처: 스마트농업컨설턴트 교재 [별첨1] 작목별 스마트팜 환경 제어값 기준표.")
        lines += ["", f"※ {note}"]
        out.append({
            "title": f"{crop} 생육단계별 환경 권장 밴드 (avg24·VPD)",
            "text": "\n".join(lines),
            "path": "환경 관리 > 작목별 권장값",
            "tags": ["환경관리", "avg24", "VPD", crop],
            "crops": [crop],
        })

    # VPD 계산법
    ex = [(22, 70), (25, 60), (18, 85)]
    lines = ["VPD(수증기압차)는 증산·병해 관리의 핵심 지표다.", "",
             "계산: SVP = 0.6108 × exp(17.27T / (T+237.3)),  VPD = SVP × (1 − RH/100)", "",
             "[예시]"]
    for t, rh in ex:
        lines.append(f"  {t}℃ · {rh}% → VPD {vpd(t, rh)} kPa")
    lines += ["", "낮으면 과습(환기 강화), 높으면 증산 과다(급액 보완)."]
    out.append({
        "title": "VPD 계산법과 해석",
        "text": "\n".join(lines),
        "path": "환경 관리 > VPD",
        "tags": ["VPD", "증산", "습도", "환기"],
    })
    return out


def build() -> list[dict]:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    items = chunks_from_periods(raw) + [chunk_start_priority(raw), chunk_pdca(raw)] + chunks_from_climate()
    for i, c in enumerate(items):
        c["id"] = f"kb_rule_{i:03d}"
        c["source"] = SRC_LABEL
        c["copyright"] = COPYRIGHT
        c.setdefault("crops", [])
        c["chars"] = len(c["text"])
        c["origin"] = raw.get("_source") if i < len(raw["PERIODS"]) + 2 else "api/services/climate_plan.py"
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    ch = build()
    print(f"규칙 청크 {len(ch)}개 | 총 {sum(c['chars'] for c in ch):,}자\n")
    for c in ch:
        print(f"  [{c['id']}] {c['chars']:>4}자  {c['title'][:52]:<54}{c['path']}")
    print("\n=== 샘플: P4 (교재에 없는 지식) ===")
    p4 = next((c for c in ch if c["title"].startswith("P4")), None)
    if p4:
        print(p4["text"][:420])

    if a.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        _blob = json.dumps(ch, ensure_ascii=False, indent=2)
        OUT.write_text(_blob, encoding="utf-8")
        KB_SERVE.mkdir(parents=True, exist_ok=True)
        (KB_SERVE / OUT.name).write_text(_blob, encoding="utf-8")  # 서빙본 동기화

        # ★ 기계 판독용 구조체도 서버로 — 청크는 '검색'용 텍스트라 P1~P6 목표값을
        #   프로그램이 쓸 수 없다. 작업추천은 targets.drainPct 같은 값을 직접 읽어야 한다.
        #   data.js 를 단일 출처로 두고 여기서 파생시킨다(수기 사본이면 조용히 어긋난다).
        raw = json.loads(RAW.read_text(encoding="utf-8"))
        (KB_SERVE / STRUCT.name).write_text(
            json.dumps({k: raw[k] for k in
                        ("_source", "PERIODS", "IRRIGATION_START", "PDCA_THRESHOLDS")
                        if k in raw}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"구조체: {KB_SERVE / STRUCT.name}")
        print(f"\n저장: {OUT} ({OUT.stat().st_size:,} bytes)")
    else:
        print("\n(미리보기 — 저장하려면 --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
