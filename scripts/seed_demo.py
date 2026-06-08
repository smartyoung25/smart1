# -*- coding: utf-8 -*-
"""시연용 농장 데이터 시딩 — 기자재·운영기록·관수(무게) 풍부 적재."""
import json, urllib.request, urllib.error, sys
B = "http://localhost:8000"
FARM = sys.argv[1] if len(sys.argv) > 1 else "farm_001"

def tok():
    r = urllib.request.urlopen(urllib.request.Request(f"{B}/api/v1/auth/token",
        data=json.dumps({"username":"admin","password":"1250"}).encode(),
        headers={"Content-Type":"application/json"}))
    return json.load(r)["access_token"]
T = tok()
def post(path, body):
    try:
        urllib.request.urlopen(urllib.request.Request(f"{B}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type":"application/json","Authorization":"Bearer "+T}), timeout=10)
        return True
    except urllib.error.HTTPError as e:
        print("  실패", path, e.code, e.read().decode()[:80]); return False

# ── 1) 기자재 (핵심 표준변수 + 물리 캘리브레이션) ──────────────────────────
EQUIP = [
    ("ENV-TH-01","sensor","온습도 센서","프리바","1동 1구역","Modbus-TCP",
        [{"tag":"reg_40001","canonical_name":"temp_internal","unit":"°C","scale":0.1,"poll_interval":60},
         {"tag":"reg_40002","canonical_name":"humidity_int","unit":"%","scale":0.1,"poll_interval":60}]),
    ("ENV-CO2-01","sensor","CO₂ 센서","씨드로닉스","1동 1구역","Modbus-RTU(RS485)",
        [{"tag":"reg_30010","canonical_name":"co2_ppm","unit":"ppm","poll_interval":60}]),
    ("IRR-EC-01","irrigation","양액기(EC/pH)","그린씨에스","양액실","MQTT",
        [{"tag":"nutri/ec","canonical_name":"ec_dsm","unit":"dS/m","poll_interval":30},
         {"tag":"nutri/ph","canonical_name":"ph","unit":"-","poll_interval":30},
         {"tag":"nutri/drain","canonical_name":"drain_pct","unit":"%","poll_interval":60}]),
    ("ACT-VENT-01","env_actuator","천창 개폐기","우성하이텍","1동","Modbus-TCP",
        [{"tag":"coil_01","canonical_name":"vent_open_pct","unit":"%","rw":"read/write",
          "actuator_response_s":45,"cmd_feedback_offset":2.0}]),
    ("ACT-HEAT-01","env_actuator","난방기","신한에이텍","기계실","디지털접점(DI/DO)",
        [{"tag":"do_03","canonical_name":"heating_temp_set","unit":"°C","rw":"write",
          "actuator_response_s":120,"cmd_feedback_offset":1.5}]),
    ("PWR-01","energy","전력량계","LS일렉트릭","수전반","Modbus-TCP",
        [{"tag":"reg_50001","canonical_name":"power_kwh","unit":"kWh","poll_interval":300}]),
]
ne = 0
for did, cat, dtype, maker, loc, proto, dps in EQUIP:
    if post(f"/api/farms/{FARM}/equipment", {"device_id":did,"category":cat,"device_type":dtype,
            "maker":maker,"location":loc,"protocol":proto,"datapoints":dps}): ne += 1

# ── 2) 운영 기록 (다양한 kind, 일자 분산) ──────────────────────────────────
ACTS = [
    ("irrigation","2번 베드 관개","12.5","점적관개 · 12.5mm · 06-01"),
    ("irrigation","2번 베드 관개","9.0","점적관개 · 9mm · 06-02"),
    ("disease_check","방제: 잿빛곰팡이 예방","","약제 보트리스 · 1000배 · 06-01"),
    ("disease_check","현장확인: 1구역","","이상없음 · 06-02"),
    ("harvest","1번 베드 수확","320","320kg · 등급 상 · 06-01"),
    ("harvest","2번 베드 수확","285","285kg · 등급 특 · 06-03"),
    ("growth","생육 측정","148","초장 148cm · 엽수 19 · 화방 6 · 06-02"),
    ("growth","생육 측정","152","초장 152cm · 엽수 20 · 화방 7 · 06-04"),
    ("env_setpoint","환경 설정값","","난방 18℃ · 환기 30% · CO₂ 800ppm · 06-01"),
    ("todo","작업 계획: 방제","","2026-06-05 · 2구역 우선"),
    ("education","스마트팜 운영 교육 이수","","관수 EC 관리 과정"),
    ("consult","전문가 예약: 재배기술","","6/6 미팅 신청"),
]
na = 0
for kind, item, val, detail in ACTS:
    v = float(val) if val else None
    if post(f"/api/farms/{FARM}/activity", {"kind":kind,"item":item,"value":v,"detail":detail}): na += 1

# ── 3) 관수 기록(슬랩 무게) — dry-back/밴드차트용 ───────────────────────────
ni = 0
for date, mx, ss, mn in [("2026-06-01",14.9,13.6,11.6),("2026-06-02",14.7,13.4,11.5),("2026-06-03",15.0,13.7,11.8)]:
    ok = post(f"/api/farms/{FARM}/irrigation", {"crop":"오이","date":date,"slab_vol_l":15,
        "max_wt_kg":mx,"sunset_wt_kg":ss,"min_wt_kg":mn,
        "periods":[{"period":3,"supply_ml":420,"drain_ml":110,"ec":3.2,"ph":6.0}]})
    if ok: ni += 1

print(f"\n[{FARM}] 시딩 완료 — 기자재 {ne}대 · 운영기록 {na}건 · 관수일 {ni}일")
# 진단 결과
d = json.load(urllib.request.urlopen(urllib.request.Request(f"{B}/api/farms/{FARM}/diagnosis",headers={"Authorization":"Bearer "+T})))
print(f"  → 종합진단 {d['overall_score']}점 ({d['grade']}) · 장비{d['stats']['devices']} 연동변수{d['stats']['mapped_vars']} 캘리브{d['stats']['calib_points']}")
