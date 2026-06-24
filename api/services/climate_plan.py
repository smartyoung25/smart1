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
import urllib.parse
import urllib.request
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


def current_period_key(hour: int, periods: list | None = None) -> str:
    for p in (periods or PERIODS):
        f, t = p["from"], p["to"]
        if f < t:
            if f <= hour < t:
                return p["key"]
        else:  # 야간처럼 자정을 넘는 구간
            if hour >= f or hour < t:
                return p["key"]
    return "day"


# ── 환경관리 EP1~EP6 구간 정의 ────────────────────────────────────────────────
# 관수 P1~P6과 대칭되는 환경 Period. 기존 4구간(night/dawn/day/prenight)에
# 매핑(period_map)되어 전략표 목표값을 재사용한다.
ENV_PERIODS = [
    {"id": "EP1", "label": "EP1", "name": "야간",
     "from": 20, "to": 4,
     "period_map": "night",
     "icon": "🌙",
     "desc": "HNT 야간온도 유지 · CO₂ 자연 감소 · 건조 dry-down",
     "targets": {"temp_key": "야간 최저 유지", "vpd_guide": "0.3~0.6 kPa", "co2_guide": "자연(400~600 ppm)"}},
    {"id": "EP2", "label": "EP2", "name": "새벽",
     "from": 4, "to": 6,
     "period_map": "dawn",
     "icon": "🌅",
     "desc": "승온 준비 · 환기 개방 시작",
     "targets": {"temp_key": "서서히 승온", "vpd_guide": "0.4~0.7 kPa", "co2_guide": "CO₂ 공급 시작"}},
    {"id": "EP3", "label": "EP3", "name": "오전",
     "from": 6, "to": 12,
     "period_map": "day",
     "icon": "☀️",
     "desc": "광연동 승온 실행 · CO₂ 최고 농도 유지",
     "targets": {"temp_key": "광연동 +Δ℃", "vpd_guide": "0.8~1.2 kPa", "co2_guide": "800~1200 ppm"}},
    {"id": "EP4", "label": "EP4", "name": "정오",
     "from": 12, "to": 15,
     "period_map": "day",
     "icon": "🌤️",
     "desc": "고일사·고온 VPD 관리 · 환기 최대",
     "targets": {"temp_key": "VPD 상한 주의", "vpd_guide": "1.0~1.4 kPa", "co2_guide": "환기 시 자연 감소"}},
    {"id": "EP5", "label": "EP5", "name": "오후",
     "from": 15, "to": 18,
     "period_map": "prenight",
     "icon": "🌇",
     "desc": "온도 완만 강하 · 환기 축소 · CO₂ 감량",
     "targets": {"temp_key": "완만 강하", "vpd_guide": "0.6~1.0 kPa", "co2_guide": "서서히 감량"}},
    {"id": "EP6", "label": "EP6", "name": "초저녁",
     "from": 18, "to": 20,
     "period_map": "night",
     "icon": "🌆",
     "desc": "야간 목표 전환 준비 · 마지막 환기",
     "targets": {"temp_key": "야간 목표로 강하", "vpd_guide": "0.4~0.7 kPa", "co2_guide": "공급 중단"}},
]

# EP 시각 기반 동적 경계 보정 (일출·일몰 연동)
def env_periods_for_sun(sunrise: float, sunset: float) -> list:
    """일출·일몰로 EP 경계 동적 산출."""
    sr = max(3.0, min(sunrise, 8.0))
    ss = max(16.0, min(sunset, 22.0))
    ep2_start = max(3, int(sr) - 2)
    ep5_end   = max(int(ss) - 2, 15)
    ep6_end   = min(int(ss), 20)
    result = []
    for ep in ENV_PERIODS:
        ep = dict(ep)
        if ep["id"] == "EP1":
            ep["from"] = ep6_end; ep["to"] = ep2_start
        elif ep["id"] == "EP2":
            ep["from"] = ep2_start; ep["to"] = int(sr)
        elif ep["id"] == "EP3":
            ep["from"] = int(sr); ep["to"] = 12
        elif ep["id"] == "EP5":
            ep["from"] = 15; ep["to"] = ep5_end
        elif ep["id"] == "EP6":
            ep["from"] = ep5_end; ep["to"] = ep6_end
        result.append(ep)
    return result


def current_env_period(hour: int, sunrise: float | None = None,
                        sunset: float | None = None) -> dict:
    """현재 시각 → 해당 ENV_PERIOD dict 반환."""
    eps = env_periods_for_sun(sunrise, sunset) if (sunrise and sunset) else ENV_PERIODS
    for ep in eps:
        f, t = ep["from"], ep["to"]
        if f < t:
            if f <= hour < t:
                return ep
        else:
            if hour >= f or hour < t:
                return ep
    return ENV_PERIODS[0]


def ep_targets(farm_id: str, crop: str, stage_key: str, ep_id: str) -> dict:
    """EP ID → 기존 4구간 전략표 목표값 반환."""
    ep = next((e for e in ENV_PERIODS if e["id"] == ep_id), ENV_PERIODS[0])
    pkey = ep["period_map"]
    plan = load_plan(farm_id, crop)
    segs = plan.get("segments", [])
    seg = next((s for s in segs if s["key"] == stage_key), segs[0] if segs else {})
    cell = (seg or {}).get("periods", {}).get(pkey, {})
    return {
        "ep_id": ep_id, "period_map": pkey,
        "temp": cell.get("temp"), "rh": cell.get("rh"), "co2": cell.get("co2"),
        "vpd": vpd(cell["temp"], cell["rh"]) if cell.get("temp") and cell.get("rh") else None,
    }


# ── ② 일출·일몰 기준 동적 구간 경계 (기상 API) ────────────────────────────────
def _sun_path(lat: float, lon: float) -> Path:
    d = Path(__file__).resolve().parents[1] / "data" / "sun_times"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{lat:.2f}_{lon:.2f}.json"


def sun_times(lat: float, lon: float, today: str | None = None) -> tuple[float, float]:
    """오늘 일출·일몰 시각(시 단위 실수). Open-Meteo(무키)·일 1회 캐시. 실패 시 (6.0,19.0)."""
    today = today or datetime.now().strftime("%Y-%m-%d")
    cp = _sun_path(lat, lon)
    if cp.exists():
        try:
            c = json.loads(cp.read_text(encoding="utf-8"))
            if c.get("date") == today:
                return c["sunrise"], c["sunset"]
        except Exception:
            pass
    sr, ss = 6.0, 19.0
    try:
        qs = urllib.parse.urlencode({"latitude": lat, "longitude": lon,
                                     "daily": "sunrise,sunset", "timezone": "Asia/Seoul",
                                     "forecast_days": 1})
        raw = json.loads(urllib.request.urlopen(
            f"https://api.open-meteo.com/v1/forecast?{qs}", timeout=8).read())
        dy = raw.get("daily", {})
        def _hh(s):  # "2026-06-12T05:12" → 5.2
            t = s.split("T")[1]; h, m = t.split(":")[:2]; return int(h) + int(m) / 60.0
        sr = round(_hh(dy["sunrise"][0]), 2); ss = round(_hh(dy["sunset"][0]), 2)
        cp.write_text(json.dumps({"date": today, "sunrise": sr, "sunset": ss}), encoding="utf-8")
    except Exception:
        pass
    return sr, ss


def periods_for_sun(sunrise: float, sunset: float) -> list:
    """일출·일몰로 4구간 경계 동적 산출. 일출 후 3h=완만승온, 일몰 전 3h=예비강하."""
    sr, ss = int(round(sunrise)), int(round(sunset))
    day_start = min(sr + 3, ss)
    pren_start = max(ss - 3, day_start)
    return [
        {"key": "night",    "label": "야간",   "from": ss, "to": sr, "desc": "일몰~일출"},
        {"key": "dawn",     "label": "일출",   "from": sr, "to": day_start, "desc": f"일출({sr}시) 후 완만 승온"},
        {"key": "day",      "label": "주간",   "from": day_start, "to": pren_start, "desc": "고일사·광합성 최대"},
        {"key": "prenight", "label": "일몰전", "from": pren_start, "to": ss, "desc": f"일몰({ss}시) 전 예비 강하"},
    ]


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


# ── ③ 온도적산(HNT temperature integration) ──────────────────────────────────
_TI_WINDOW = 5      # 적산 윈도우(일)
_TI_BAND = 2.0      # 누적 보정 상한(±℃)


def _ti_path(farm_id: str) -> Path:
    d = Path(__file__).resolve().parents[1] / "data" / "temp_integration"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{farm_id}.json"


def _ti_load(farm_id: str) -> dict:
    fp = _ti_path(farm_id)
    if fp.exists():
        try: return json.loads(fp.read_text(encoding="utf-8"))
        except Exception: pass
    return {"days": {}}


def record_daily_temp(farm_id: str, sample_temp: float, target_avg24: float | None = None,
                      date: str | None = None) -> dict:
    """오늘 실측 기온 샘플 누적 → 일 평균(running mean) 갱신. 적산 관리 입력."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    st = _ti_load(farm_id)
    days = st.setdefault("days", {})
    d = days.setdefault(date, {"sum": 0.0, "n": 0, "target": target_avg24})
    d["sum"] += float(sample_temp); d["n"] += 1
    if target_avg24 is not None:
        d["target"] = target_avg24
    d["realized"] = round(d["sum"] / d["n"], 2)
    # 최근 _TI_WINDOW+2 일만 보존
    for k in sorted(days.keys())[:-(_TI_WINDOW + 2)]:
        days.pop(k, None)
    _ti_path(farm_id).write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"date": date, "realized": d["realized"], "n": d["n"]}


def integration_state(farm_id: str, target_avg24: float | None, today: str | None = None) -> dict:
    """최근 윈도우의 (목표-실측) 누적 부족분 → 오늘 목표 보정량(±band) 산출.
    HNT: 누적이 추웠으면(+) 오늘 목표를 올려 적산을 회복(catch-up)."""
    today = today or datetime.now().strftime("%Y-%m-%d")
    st = _ti_load(farm_id)
    days = st.get("days", {})
    # 오늘 이전 완료일들로 누적 부족분 계산
    past = sorted(k for k in days.keys() if k < today)[-_TI_WINDOW:]
    deficit = 0.0; used = []
    for k in past:
        d = days[k]
        tgt = d.get("target") if d.get("target") is not None else target_avg24
        rz = d.get("realized")
        if tgt is not None and rz is not None:
            deficit += (tgt - rz)
            used.append({"date": k, "target": tgt, "realized": rz, "delta": round(tgt - rz, 1)})
    corr = max(-_TI_BAND, min(_TI_BAND, round(deficit, 1)))
    return {"correction": corr, "cumulative_deficit": round(deficit, 1),
            "window_days": len(used), "detail": used}


def _presc(pid, icon, title, level, action, reason, conf):
    return {"id": pid, "icon": icon, "title": title, "level": level,
            "action": action, "reason": reason, "conf": conf, "source": "plan"}


def evaluate(farm_id: str, crop: str = "딸기", measured: dict | None = None,
             hour: int | None = None, solar: float | None = None) -> dict:
    """전략표 목표값을 기준선으로 실측 편차를 계산해 제어 처방을 생성.
    (고정 임계값이 아니라 '지금 생육시기·구간의 목표' 대비 편차로 판단)"""
    measured = measured or {}
    act = active_setpoint(farm_id, crop, hour, solar,
                          measured.get("sunrise"), measured.get("sunset"))
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
                    solar: float | None = None,
                    sunrise: float | None = None, sunset: float | None = None) -> dict:
    """정식일 경과 + 현재시각 → 지금 적용할 목표 셀.
    선진 기법 적용: 광연동 승온 · 24h 평균기온/DIF · VPD 밴드
    · ② 일출·일몰 동적 구간 · ③ 온도적산 익일 보정."""
    plan = load_plan(farm_id, crop)
    if hour is None:
        hour = datetime.now().hour
    # ② 일출·일몰 동적 경계 (제공 시) — 없으면 고정 PERIODS
    if sunrise is not None and sunset is not None:
        periods_used = periods_for_sun(sunrise, sunset)
    else:
        periods_used = PERIODS
    pkey = current_period_key(hour, periods_used)
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

    # ③ 온도적산 익일 보정 — 누적 부족분만큼 오늘 목표 온도 보정
    ti = integration_state(farm_id, metrics.get("avg24"))
    ti_corr = ti["correction"]
    temp_integrated = round(adj_temp + ti_corr, 1) if (adj_temp is not None and ti_corr) else adj_temp

    # EP 판정 (일출·일몰 동적 보정 포함)
    ep = current_env_period(hour, sunrise, sunset)

    return {
        "farm_id": farm_id, "crop": crop,
        "weeks_since_transplant": wk,
        "stage_key": skey, "stage_label": (seg or {}).get("label"),
        "period_key": pkey,
        "period_label": next((p["label"] for p in periods_used if p["key"] == pkey), pkey),
        "ep_id": ep["id"], "ep_name": ep["name"], "ep_desc": ep["desc"],
        "env_periods": ENV_PERIODS,
        "target": {"temp": temp, "rh": rh, "co2": co2,
                   "temp_adj": temp_integrated, "light_boost": boost,
                   "temp_base": adj_temp, "integration_corr": ti_corr,
                   "vpd": vpd(temp, rh) if (temp is not None and rh is not None) else None},
        "metrics": {"avg24": metrics["avg24"], "dif": metrics["dif"],
                    "avg24_band": avg24_band, "vpd_band": vpd_band},
        "integration": ti,
        "sun": ({"sunrise": sunrise, "sunset": sunset,
                 "periods": periods_used} if sunrise is not None else None),
        "benchmark_method": bench.get("method", _BENCH_METHOD),
        "transplant_date": plan.get("transplant_date", ""),
        "mode": plan.get("mode", "stage"),
    }
