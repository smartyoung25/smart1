"""환경관리 전략표(Climate Setpoint Plan) — 2축(생육시기 × 하루 구간) 설정값.

- 행(생육시기): 정식일(transplant_date) 기준 경과 → 생육단계 / 주별 / 월별 모드
- 열(하루 구간): 야간 · 일출 · 주간 · 일몰전 (4구간)
- 셀: 온도(℃) · 습도(%) · CO₂(ppm) → VPD 는 온습도에서 자동 계산

GET  /environment/climate-plan          저장된 전략표(없으면 작물 기본 템플릿)
POST /environment/climate-plan          전략표 저장
GET  /environment/climate-plan/active   정식일+현재시각 → 지금 적용 목표값
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

# ── 하루 구간 정의 (열) ───────────────────────────────────────────────────────
#   (key, 라벨, 시작시각, 끝시각, 설명)
PERIODS = [
    {"key": "night",    "label": "야간",   "from": 20, "to": 5,  "desc": "일몰~일출 · 호흡·생식 조절"},
    {"key": "dawn",     "label": "일출",   "from": 5,  "to": 9,  "desc": "일출 후 2~3h · 완만 승온"},
    {"key": "day",      "label": "주간",   "from": 9,  "to": 16, "desc": "고일사 · 광합성 최대"},
    {"key": "prenight", "label": "일몰전", "from": 16, "to": 20, "desc": "일몰 2~3h 전 · 예비 강하(DROP)"},
]


def current_period_key(hour: int) -> str:
    for p in PERIODS:
        f, t = p["from"], p["to"]
        if f < t:
            if f <= hour < t:
                return p["key"]
        else:  # 야간처럼 자정을 넘는 구간
            if hour >= f or hour < t:
                return p["key"]
    return "day"


# ── 작물별 생육단계 × 구간 기본 템플릿 ────────────────────────────────────────
#   각 stage: key,label,week_from,week_to, periods{night/dawn/day/prenight:{temp,rh,co2}}
def _stage(key, label, wf, wt, n, d, day, pn):
    def cell(temp, rh, co2): return {"temp": temp, "rh": rh, "co2": co2}
    return {"key": key, "label": label, "week_from": wf, "week_to": wt,
            "periods": {"night": cell(*n), "dawn": cell(*d), "day": cell(*day), "prenight": cell(*pn)}}


# (temp, rh, co2) 튜플 — 겨울 시설 딸기 기준(외부기온 민감, 야간 저온 화아분화)
_BASE = {
    "딸기": [
        _stage("establish", "활착기",      0,  2, (10, 85, 450), (14, 80, 700), (20, 70, 900), (13, 80, 600)),
        _stage("veg",       "영양생장기",  2,  6, (8,  80, 450), (13, 75, 800), (23, 65, 1000),(12, 78, 600)),
        _stage("flower",    "개화·착과기", 6, 12, (6,  78, 450), (12, 72, 800), (24, 62, 1000),(10, 75, 600)),
        _stage("harvest",   "수확기",     12, 99, (7,  78, 450), (12, 72, 800), (23, 63, 900), (10, 76, 600)),
    ],
    "_default": [
        _stage("establish", "활착기",      0,  2, (16, 85, 450), (19, 80, 700), (25, 70, 900), (18, 80, 600)),
        _stage("veg",       "영양생장기",  2,  6, (15, 80, 450), (19, 75, 800), (27, 65, 1000),(17, 78, 600)),
        _stage("flower",    "개화·착과기", 6, 12, (15, 78, 450), (18, 72, 800), (27, 62, 1000),(16, 75, 600)),
        _stage("harvest",   "수확기",     12, 99, (15, 78, 450), (18, 72, 800), (26, 63, 900), (16, 76, 600)),
    ],
}
# 작물 alias → _default 재사용 (작물별 미세값은 추후 보강)
_CROP_ALIAS = {"방울토마토", "완숙토마토", "토마토", "오이", "파프리카", "참외"}


def _base_stages(crop: str):
    c = (crop or "").strip()
    if c in _BASE:
        return _BASE[c]
    # 접미사/괄호 포함(예: '딸기(제주)') 부분일치 보완
    for k in _BASE:
        if k != "_default" and k in c:
            return _BASE[k]
    return _BASE["_default"]


def vpd(temp: float, rh: float) -> float:
    """포화수증기압차(kPa) — 잎-공기 근사(잎온=기온 가정)."""
    svp = 0.6108 * math.exp(17.27 * temp / (temp + 237.3))
    return round(svp * (1 - rh / 100.0), 2)


def _plan_path(farm_id: str) -> Path:
    d = Path(__file__).resolve().parents[1] / "data" / "climate_plan"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{farm_id}.json"


def _value_at_week(stages, week: int) -> dict:
    for s in stages:
        if s["week_from"] <= week < s["week_to"]:
            return s
    return stages[-1]


def build_template(crop: str, mode: str = "stage", transplant_date: str = "") -> dict:
    """작물·모드별 기본 전략표 생성. mode: stage | weekly | monthly."""
    stages = _base_stages(crop)
    segments = []
    if mode == "stage":
        for s in stages:
            segments.append({"key": s["key"], "label": s["label"],
                             "week_from": s["week_from"], "week_to": s["week_to"],
                             "periods": json.loads(json.dumps(s["periods"]))})
    elif mode == "weekly":
        for wk in range(0, 16):
            base = _value_at_week(stages, wk)
            segments.append({"key": f"w{wk+1}", "label": f"{wk+1}주차",
                             "week_from": wk, "week_to": wk + 1,
                             "periods": json.loads(json.dumps(base["periods"]))})
    else:  # monthly
        for m in range(0, 4):
            wf, wt = m * 4, (m + 1) * 4
            base = _value_at_week(stages, wf)
            segments.append({"key": f"m{m+1}", "label": f"{m+1}개월차",
                             "week_from": wf, "week_to": wt,
                             "periods": json.loads(json.dumps(base["periods"]))})
    return {"crop": crop, "basis": "transplant", "transplant_date": transplant_date,
            "mode": mode, "periods_def": PERIODS, "segments": segments,
            "source": "template"}


def load_plan(farm_id: str, crop: str = "딸기") -> dict:
    fp = _plan_path(farm_id)
    if fp.exists():
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
            d["periods_def"] = PERIODS   # 항상 최신 구간 정의 주입
            return d
        except Exception:
            pass
    return build_template(crop, "stage")


def save_plan(farm_id: str, plan: dict) -> dict:
    fp = _plan_path(farm_id)
    plan["updated_at"] = datetime.now(timezone.utc).isoformat()
    plan["source"] = "user"
    fp.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def _weeks_since(transplant_date: str) -> int | None:
    if not transplant_date:
        return None
    try:
        td = datetime.fromisoformat(transplant_date[:10])
        now = datetime.now()
        return max(0, (now - td).days // 7)
    except Exception:
        return None


def active_setpoint(farm_id: str, crop: str = "딸기", hour: int | None = None) -> dict:
    """정식일 경과 + 현재시각 → 지금 적용할 목표 셀."""
    plan = load_plan(farm_id, crop)
    if hour is None:
        hour = datetime.now().hour
    pkey = current_period_key(hour)
    wk = _weeks_since(plan.get("transplant_date", ""))

    seg = None
    segs = plan.get("segments", [])
    if wk is not None:
        for s in segs:
            if s["week_from"] <= wk < s["week_to"]:
                seg = s
                break
    if seg is None and segs:
        seg = segs[0]   # 정식일 미설정 시 첫 구간

    cell = (seg or {}).get("periods", {}).get(pkey, {}) if seg else {}
    temp, rh, co2 = cell.get("temp"), cell.get("rh"), cell.get("co2")
    return {
        "farm_id": farm_id, "crop": crop,
        "weeks_since_transplant": wk,
        "stage_key": (seg or {}).get("key"), "stage_label": (seg or {}).get("label"),
        "period_key": pkey,
        "period_label": next((p["label"] for p in PERIODS if p["key"] == pkey), pkey),
        "target": {"temp": temp, "rh": rh, "co2": co2,
                   "vpd": vpd(temp, rh) if (temp is not None and rh is not None) else None},
        "transplant_date": plan.get("transplant_date", ""),
        "mode": plan.get("mode", "stage"),
    }
