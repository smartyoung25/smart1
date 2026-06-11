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


# ── 선진사례 벤치마크 파라미터 ────────────────────────────────────────────────
#   Priva/Hoogendoorn 광연동 승온(lichtverhoging): 일사 ref 초과분 100W/m²당 +Δ℃, 상한 cap
_LIGHT_BOOST = {"ref_wm2": 200, "slope_per_100wm2": 0.6, "cap_c": 3.0}
#   Het Nieuwe Telen 24h 평균기온·VPD 권장 밴드 (작물군별, 단계키 기준)
_RECOMMEND = {
    "딸기":     {"avg24": {"establish": [13, 15], "veg": [12, 15], "flower": [11, 14], "harvest": [12, 14]},
                "vpd":   {"establish": [0.4, 0.7], "veg": [0.6, 0.9], "flower": [0.7, 1.0], "harvest": [0.6, 0.9]}},
    "_default": {"avg24": {"establish": [17, 20], "veg": [18, 21], "flower": [18, 21], "harvest": [17, 20]},
                "vpd":   {"establish": [0.4, 0.8], "veg": [0.6, 1.0], "flower": [0.8, 1.2], "harvest": [0.7, 1.1]}},
}
_BENCH_METHOD = ("Het Nieuwe Telen(차세대 재배)·Plant Empowerment · "
                 "Priva 광연동 승온 · 농진청 시설표준")


def _period_hours() -> dict:
    out = {}
    for p in PERIODS:
        f, t = p["from"], p["to"]
        out[p["key"]] = (t - f) if f < t else (24 - f + t)
    return out


def segment_metrics(seg: dict) -> dict:
    """전략표 한 행의 24h 평균기온·DIF(주야차)를 계산(선진 온도적산 관리)."""
    hrs = _period_hours()
    per = seg.get("periods", {})
    tot_h = sum(hrs.values()) or 24
    avg24 = sum((per.get(k, {}).get("temp") or 0) * h for k, h in hrs.items()) / tot_h
    day_t = (per.get("day", {}) or {}).get("temp")
    night_t = (per.get("night", {}) or {}).get("temp")
    dif = (day_t - night_t) if (day_t is not None and night_t is not None) else None
    return {"avg24": round(avg24, 1), "dif": round(dif, 1) if dif is not None else None}


def _recommend_for(crop: str) -> dict:
    for k in _RECOMMEND:
        if k != "_default" and k in (crop or ""):
            return _RECOMMEND[k]
    return _RECOMMEND["_default"]


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
            "benchmark": {"method": _BENCH_METHOD, "light_boost": dict(_LIGHT_BOOST),
                          "recommend": _recommend_for(crop)},
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


def _presc(pid, icon, title, level, action, reason, conf):
    return {"id": pid, "icon": icon, "title": title, "level": level,
            "action": action, "reason": reason, "conf": conf, "source": "plan"}


def evaluate(farm_id: str, crop: str = "딸기", measured: dict | None = None,
             hour: int | None = None, solar: float | None = None) -> dict:
    """전략표 목표값을 기준선으로 실측 편차를 계산해 제어 처방을 생성.
    (고정 임계값이 아니라 '지금 생육시기·구간의 목표' 대비 편차로 판단)"""
    measured = measured or {}
    act = active_setpoint(farm_id, crop, hour, solar)
    tgt = act.get("target", {})
    metrics = act.get("metrics", {})
    t_target = tgt.get("temp_adj") if tgt.get("temp_adj") is not None else tgt.get("temp")
    co2_target = tgt.get("co2")
    vpd_band = metrics.get("vpd_band")

    mt, mrh, mco2 = measured.get("temp"), measured.get("rh"), measured.get("co2")
    presc, dev = [], {}

    # ① 온도 — 목표(광연동 보정 포함) 대비 편차
    if mt is not None and t_target is not None:
        d = round(mt - t_target, 1); dev["temp"] = d
        if d <= -3:
            presc.append(_presc("heating", "🔥", "난방 제어", "danger",
                                 f"난방 긴급 가동 (목표 {t_target}℃)",
                                 f"실측 {mt}℃ — 목표 대비 {d}℃ (임계 저온)", 0.95))
        elif d <= -1.5:
            presc.append(_presc("heating", "🔥", "난방 제어", "warn",
                                 f"난방 ON (목표 {t_target}℃)",
                                 f"실측 {mt}℃ — 목표 대비 {d}℃ 낮음", 0.88))
        elif d >= 3:
            presc.append(_presc("cooling", "🌬️", "환기·냉방", "danger",
                                 f"환기 최대 + 차광 (목표 {t_target}℃)",
                                 f"실측 {mt}℃ — 목표 대비 +{d}℃ (고온)", 0.90))
        elif d >= 1.5:
            presc.append(_presc("cooling", "🌬️", "환기 제어", "warn",
                                 f"환기 강화 (목표 {t_target}℃)",
                                 f"실측 {mt}℃ — 목표 대비 +{d}℃", 0.82))

    # ② 습도/VPD — 권장 밴드 대비
    if mt is not None and mrh is not None:
        mvpd = vpd(mt, mrh); dev["vpd"] = mvpd
        if vpd_band:
            if mvpd < vpd_band[0] - 0.2:
                presc.append(_presc("humid", "💧", "제습·환기", "warn",
                                     f"제습/환기 (VPD 목표 {vpd_band[0]}~{vpd_band[1]})",
                                     f"실측 VPD {mvpd}kPa — 과습(결로·병 위험)", 0.80))
            elif mvpd > vpd_band[1] + 0.3:
                presc.append(_presc("humid", "💧", "가습·관수", "warn",
                                     f"가습/관수 (VPD 목표 {vpd_band[0]}~{vpd_band[1]})",
                                     f"실측 VPD {mvpd}kPa — 증산 과다", 0.80))

    # ③ CO₂ — 목표 대비 부족 / 과농도 안전
    if mco2 is not None:
        dev["co2"] = (round(mco2 - co2_target) if co2_target is not None else None)
        if mco2 > 1500:
            presc.append(_presc("co2", "🌿", "CO₂ 안전", "danger", "환기 즉시 강화",
                                 f"CO₂ {int(mco2)}ppm — 과농도", 0.92))
        elif co2_target is not None and mco2 < co2_target - 200:
            presc.append(_presc("co2", "🌿", "CO₂ 시비", "suggest",
                                 f"CO₂ 시비 (목표 {co2_target}ppm)",
                                 f"실측 {int(mco2)}ppm — 목표 대비 {int(mco2-co2_target)}ppm 부족", 0.75))

    return {"active": act, "prescriptions": presc, "deviation": dev,
            "target_available": t_target is not None}


def _weeks_since(transplant_date: str) -> int | None:
    if not transplant_date:
        return None
    try:
        td = datetime.fromisoformat(transplant_date[:10])
        now = datetime.now()
        return max(0, (now - td).days // 7)
    except Exception:
        return None


def active_setpoint(farm_id: str, crop: str = "딸기", hour: int | None = None,
                    solar: float | None = None) -> dict:
    """정식일 경과 + 현재시각 → 지금 적용할 목표 셀.
    선진 기법 적용: 광연동 승온(주간 일사 보정) · 24h 평균기온/DIF · VPD 권장밴드."""
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

    # ① 광연동 승온(Priva lichtverhoging): 주간·일출 구간에서 일사 ref 초과분만큼 설정온도 상향
    bench = plan.get("benchmark", {})
    lb = bench.get("light_boost", _LIGHT_BOOST)
    boost = 0.0
    if temp is not None and pkey in ("day", "dawn") and solar is not None:
        over = max(0.0, float(solar) - lb.get("ref_wm2", 200))
        boost = min(lb.get("cap_c", 3.0), lb.get("slope_per_100wm2", 0.6) * over / 100.0)
        boost = round(boost, 1)
    adj_temp = round(temp + boost, 1) if temp is not None else None

    # ② 24h 평균기온·DIF (온도적산 관리)  ③ VPD 권장밴드
    metrics = segment_metrics(seg) if seg else {"avg24": None, "dif": None}
    rec = bench.get("recommend") or _recommend_for(crop)
    skey = (seg or {}).get("key")
    avg24_band = (rec.get("avg24", {}) or {}).get(skey)
    vpd_band = (rec.get("vpd", {}) or {}).get(skey)

    return {
        "farm_id": farm_id, "crop": crop,
        "weeks_since_transplant": wk,
        "stage_key": skey, "stage_label": (seg or {}).get("label"),
        "period_key": pkey,
        "period_label": next((p["label"] for p in PERIODS if p["key"] == pkey), pkey),
        "target": {"temp": temp, "rh": rh, "co2": co2,
                   "temp_adj": adj_temp, "light_boost": boost,
                   "vpd": vpd(temp, rh) if (temp is not None and rh is not None) else None},
        "metrics": {"avg24": metrics["avg24"], "dif": metrics["dif"],
                    "avg24_band": avg24_band, "vpd_band": vpd_band},
        "benchmark_method": bench.get("method", _BENCH_METHOD),
        "transplant_date": plan.get("transplant_date", ""),
        "mode": plan.get("mode", "stage"),
    }
